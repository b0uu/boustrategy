"""Run with python -m tests.public.benchmark_public. Uses a disposable database."""

import argparse
import json
import platform
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from statistics import median, quantiles
from time import perf_counter

from app.public.database import open_readonly
from app.public.publication import initialize
from app.public.queries import feed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--records", type=int, default=100_000)
    parser.add_argument("--requests", type=int, default=100)
    parser.add_argument("--concurrency", type=int, default=20)
    args = parser.parse_args()
    if args.records < 1 or args.requests < 2 or args.concurrency < 1:
        parser.error("positive records/concurrency and at least two requests are required")
    with tempfile.TemporaryDirectory(prefix="bou-public-benchmark-") as folder:
        path = Path(folder) / "public.db"
        conn = initialize(path)
        compact = {
            "portfolio_id": "live",
            "mode": "live",
            "ticker": "NVDA",
            "created_at": "2026-06-10T12:00:00+00:00",
            "decision": "BUY",
            "policy_outcome": "approved",
            "schema_outcome": "passed",
            "lifecycle": "policy_approved",
            "regime": "GREEN",
            "theme": "ai_compute",
            "company_name": "NVIDIA",
            "summary_truncated": False,
        }
        detail = {
            "narrative": {
                "stages": [
                    {"stage": name, "summary": "Public evidence. " * 25}
                    for name in (
                        "initial_thesis",
                        "counter_thesis",
                        "adversarial_refinement",
                        "refined_thesis",
                        "what_is_priced_in",
                    )
                ],
                "claims": [
                    {"claim": "Recorded evidence. " * 12, "source_ids": ["src_example"]}
                    for _ in range(3)
                ],
            },
            "execution": {"status": "unavailable", "quantity": None, "gross_notional": None},
        }
        try:
            conn.executemany(
                "INSERT INTO public_decisions(source_key,public_id,portfolio_id,created_at,ticker,"
                "action,policy,lifecycle,summary,content,feed_content) VALUES(?,?,'live',"
                "'2026-06-10T12:00:00+00:00','NVDA','BUY','approved','policy_approved',?,?,?)",
                (
                    (
                        str(i),
                        f"dec_{i:06}",
                        f"Company semiconductor {i}",
                        json.dumps(
                            {
                                **compact,
                                **detail,
                                "public_id": f"dec_{i:06}",
                                "public_summary": f"Company semiconductor {i}",
                            }
                        ),
                        json.dumps(
                            {
                                **compact,
                                "public_id": f"dec_{i:06}",
                                "public_summary": f"Company semiconductor {i}",
                            }
                        ),
                    )
                    for i in range(args.records)
                ),
            )
            conn.commit()
        finally:
            conn.close()

        def sample(index: int) -> tuple[float, int, int, int]:
            started = perf_counter()
            with open_readonly(path) as read:
                statements: list[str] = []
                read.set_trace_callback(statements.append)
                result = feed(read, portfolio_id="live")
            assert all(
                item["public_id"].startswith("dec_")
                and item["public_summary"].startswith("Company")
                and "narrative" not in item
                for item in result["items"]
            )
            payload_bytes = len(json.dumps(result).encode())
            assert payload_bytes < 30_000
            return (
                (perf_counter() - started) * 1000,
                len(statements),
                len(result["items"]),
                payload_bytes,
            )

        with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
            samples = list(pool.map(sample, range(args.requests)))
        times = [row[0] for row in samples]
        print(
            json.dumps(
                {
                    "platform": platform.platform(),
                    "python": platform.python_version(),
                    "records": args.records,
                    "concurrency": args.concurrency,
                    "requests": args.requests,
                    "p50_ms": round(median(times), 2),
                    "p95_ms": round(quantiles(times, n=20)[18], 2),
                    "query_counts": sorted({row[1] for row in samples}),
                    "rows": sorted({row[2] for row in samples}),
                    "maximum_payload_bytes": max(row[3] for row in samples),
                }
            )
        )


if __name__ == "__main__":
    main()
