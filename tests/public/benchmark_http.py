"""Measure bounded public reads through a real localhost HTTP server.

Run from the checkout root with ``python -m tests.public.benchmark_http`` so
imports resolve against that checkout instead of another editable installation.
"""

import argparse
import asyncio
import hashlib
import json
import os
import platform
import socket
import sqlite3
import threading
import time
import urllib.request
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from statistics import median
from tempfile import TemporaryDirectory
from time import perf_counter
from typing import Any
from unittest.mock import patch

import uvicorn
from fastapi.testclient import TestClient

from app.public.database import open_readonly
from app.public.publication import initialize
from app.public.queries import feed
from app.public.server import create_public_app


def percentile(values: list[float], percentile_value: float) -> float:
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(len(ordered) * percentile_value) - 1))
    return ordered[index]


def seed(path: Path, records: int) -> float:
    detail_template: dict[str, Any] = {
        "portfolio_id": "live",
        "mode": "live",
        "ticker": "NVDA",
        "company_name": "NVIDIA Corporation",
        "created_at": "2026-06-10T20:00:00+00:00",
        "decision": "BUY",
        "public_summary": "Recorded demand and valuation review. " * 12,
        "policy_outcome": "approved",
        "schema_outcome": "passed",
        "lifecycle": "broker_filled",
        "regime": "GREEN",
        "theme": "AI infrastructure",
        "narrative_status": "approved_public_stages",
        "narrative": {
            "stages": [
                {
                    "stage": stage,
                    "summary": "Published evidence and counter-evidence were reviewed. " * 8,
                    "claim_ids": ["claim_public"],
                }
                for stage in (
                    "initial_thesis",
                    "counter_thesis",
                    "adversarial_refinement",
                    "what_is_priced_in",
                    "refined_thesis",
                )
            ],
            "claims": [
                {
                    "public_id": "claim_public",
                    "claim": "Public company results support the recorded demand observation.",
                    "source_ids": ["source_public"],
                }
            ],
            "sources": [
                {
                    "public_id": "source_public",
                    "title": "Quarterly results",
                    "publisher": "Company IR",
                    "url": "https://example.com/results",
                }
            ],
        },
        "policy_evaluation": {
            "status": "available",
            "checks": [
                {
                    "rule_id": "single_name_exposure",
                    "name": "Single-name exposure",
                    "result": "passed",
                    "observed": "0.12",
                    "threshold": "0.20",
                    "headroom": "0.08",
                }
            ],
        },
        "execution": {
            "status": "available",
            "quantity": "1.250000000000000000",
            "gross_notional": "250.00",
            "fees": "0.00",
            "items": [],
        },
        "milestones": [
            {"stage": "schema_validated", "occurred_at": "2026-06-10T20:00:01+00:00"},
            {"stage": "policy_approved", "occurred_at": "2026-06-10T20:00:02+00:00"},
        ],
    }
    compact_template = {
        key: detail_template[key]
        for key in (
            "portfolio_id",
            "mode",
            "ticker",
            "company_name",
            "created_at",
            "decision",
            "public_summary",
            "policy_outcome",
            "schema_outcome",
            "lifecycle",
            "regime",
            "theme",
        )
    }
    compact_template["public_run_id"] = None
    compact_template["summary_truncated"] = False
    overview = {
        "portfolio_id": "live",
        "name": "BouStrategy",
        "mode": "live",
        "is_default": True,
        "status": "available",
        "reason": None,
        "data_as_of": "2026-06-10T20:00:00+00:00",
        "equity": "10000.00",
        "cash": "7500.00",
        "return_percent": "1.250000",
        "decision_counts": {"approved": records, "rejected": 0, "unavailable": 0},
        "decision_count_date": "2026-06-10",
        "decisions_today": records,
        "positions": [],
        "history": [],
        "capabilities": {"returns": True, "cash": True, "quantities": True},
    }
    conn = initialize(path)
    started = perf_counter()
    try:
        conn.execute(
            "INSERT INTO public_portfolios VALUES ('live', ?)",
            (json.dumps(overview, sort_keys=True),),
        )

        def rows() -> Any:
            for index in range(records):
                public_id = f"dec_{index:032x}"
                detail = json.dumps({**detail_template, "public_id": public_id}, sort_keys=True)
                compact = json.dumps({**compact_template, "public_id": public_id}, sort_keys=True)
                yield (
                    f"source-{index}",
                    public_id,
                    "live",
                    detail_template["created_at"],
                    detail_template["ticker"],
                    detail_template["decision"],
                    detail_template["policy_outcome"],
                    detail_template["lifecycle"],
                    detail_template["public_summary"],
                    detail,
                    compact,
                )

        conn.executemany(
            "INSERT INTO public_decisions (source_key, public_id, portfolio_id, created_at, "
            "ticker, action, policy, lifecycle, summary, content, feed_content) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows(),
        )
        conn.execute(
            "UPDATE publication_meta SET revision=1, updated_at='2026-06-10T20:00:00+00:00'"
        )
        conn.commit()
    finally:
        conn.close()
    return perf_counter() - started


def request(url: str) -> tuple[float, int]:
    started = perf_counter()
    with urllib.request.urlopen(url, timeout=30) as response:
        body = response.read()
        assert response.status == 200
        assert response.headers["Cache-Control"] == "no-store"
    return (perf_counter() - started) * 1000, len(body)


def measure(url: str, requests: int, clients: int) -> tuple[list[float], int]:
    with ThreadPoolExecutor(max_workers=clients) as pool:
        results = list(pool.map(lambda _: request(url), range(requests)))
    return [item[0] for item in results], max(item[1] for item in results)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--records", type=int, default=100_000)
    parser.add_argument("--requests", type=int, default=100)
    parser.add_argument("--clients", type=int, default=20)
    args = parser.parse_args()
    if args.records < 1 or args.requests < 1 or args.clients < 1:
        parser.error("record, request and client counts must be positive")

    with TemporaryDirectory(prefix="bou-public-http-") as folder:
        root = Path(folder)
        public = root / "public.db"
        seed_seconds = seed(public, args.records)
        statements: list[str] = []
        with open_readonly(public) as conn:
            conn.set_trace_callback(statements.append)
            result = feed(conn, portfolio_id="live")
            query_count = len(statements)
            plan = [
                row[3]
                for row in conn.execute(
                    "EXPLAIN QUERY PLAN SELECT public_id FROM public_decisions "
                    "WHERE portfolio_id='live' AND revoked=0 AND withdrawn=0 "
                    "ORDER BY created_at DESC, public_id DESC LIMIT 25"
                )
            ]
        query_payload_bytes = len(json.dumps(result).encode())
        overview_statements: list[str] = []

        @contextmanager
        def traced_readonly(
            path: str | Path, *, allow_wal: bool = False
        ) -> Iterator[sqlite3.Connection]:
            with open_readonly(path, allow_wal=allow_wal) as conn:
                conn.set_trace_callback(overview_statements.append)
                yield conn

        with patch("app.public.server.open_readonly", traced_readonly):
            overview_response = TestClient(create_public_app(public, root / "no-ui")).get(
                "/api/public/v2/portfolios/live/overview"
            )
        overview_response.raise_for_status()
        overview_query_count = len(overview_statements)
        before = hashlib.sha256(public.read_bytes()).hexdigest()
        listener = socket.socket()
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 0))
        listener.listen(128)
        port = listener.getsockname()[1]
        app = create_public_app(public, root / "no-ui")
        config = uvicorn.Config(app, log_level="error", access_log=False, lifespan="off")
        server = uvicorn.Server(config)
        thread = threading.Thread(
            target=lambda: asyncio.run(server.serve(sockets=[listener])), daemon=True
        )
        thread.start()
        deadline = time.monotonic() + 10
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.01)
        if not server.started:
            raise RuntimeError("local benchmark server did not start")
        base = f"http://127.0.0.1:{port}"
        try:
            feed_times, feed_bytes = measure(
                base + "/api/public/v2/decisions?portfolio_id=live&limit=25",
                args.requests,
                args.clients,
            )
            overview_times, overview_bytes = measure(
                base + "/api/public/v2/portfolios/live/overview",
                args.requests,
                args.clients,
            )
        finally:
            server.should_exit = True
            thread.join(timeout=10)
            listener.close()
        after = hashlib.sha256(public.read_bytes()).hexdigest()
        assert before == after
        assert not Path(str(public) + "-wal").exists()
        assert not Path(str(public) + "-shm").exists()
        print(
            json.dumps(
                {
                    "platform": platform.platform(),
                    "python": platform.python_version(),
                    "logical_cpus": os.cpu_count(),
                    "records": args.records,
                    "requests_per_route": args.requests,
                    "concurrent_clients": args.clients,
                    "seed_seconds": round(seed_seconds, 3),
                    "feed_http_p50_ms": round(median(feed_times), 3),
                    "feed_http_p95_ms": round(percentile(feed_times, 0.95), 3),
                    "feed_max_response_bytes": feed_bytes,
                    "overview_http_p50_ms": round(median(overview_times), 3),
                    "overview_http_p95_ms": round(percentile(overview_times, 0.95), 3),
                    "overview_max_response_bytes": overview_bytes,
                    "direct_feed_sql_statements": query_count,
                    "direct_feed_rows": len(result["items"]),
                    "direct_feed_response_bytes": query_payload_bytes,
                    "direct_overview_sql_statements": overview_query_count,
                    "query_plan": plan,
                    "database_unchanged_by_http_gets": before == after,
                },
                sort_keys=True,
            )
        )


if __name__ == "__main__":
    main()
