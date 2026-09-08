import argparse
import secrets
import sqlite3
from contextlib import closing
from datetime import UTC, date, datetime
from html import escape
from pathlib import Path
from typing import Protocol
from urllib.parse import parse_qs, urlencode
from zoneinfo import ZoneInfo

import uvicorn
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from starlette.concurrency import run_in_threadpool

from app.broker.config import load_live_profiles, public_profile_status
from app.dashboard import queries, views
from app.reason.run import PreparationResult, prepare_session
from app.storage.database import connect

_SLOTS = {"morning", "midday", "close"}
_NEW_YORK = ZoneInfo("America/New_York")


class PreparationRunner(Protocol):
    def __call__(
        self,
        conn: sqlite3.Connection,
        on_date: date,
        out_dir: str | Path,
        *,
        digest_dir: str | Path = "data/digests",
        watchlist_path: str | Path = "docs/watchlist.md",
    ) -> PreparationResult: ...


def create_app(
    db_path: str | Path,
    preparation_runner: PreparationRunner = prepare_session,
    live_config_path: str | Path = "ops/live.local.json",
) -> FastAPI:
    app = FastAPI(title="BouStrategy dashboard")
    path = Path(db_path)
    with closing(connect(path)):
        pass
    digest_dir = path.parent / "digests"
    reason_dir = path.parent / "reason_runs"
    live_config = Path(live_config_path)
    csrf_token = secrets.token_urlsafe(24)

    @app.get("/", response_class=HTMLResponse)
    def overview() -> str:
        with closing(sqlite3.connect(path)) as conn:
            return views.page(
                "Agent dashboard",
                views.dashboard(queries.overview(conn, digest_dir)),
                active="/",
                eyebrow="BouStrategy · recorded state",
            )

    @app.get("/operate", response_class=HTMLResponse)
    def operate(
        run_date: str | None = Query(default=None, alias="date"),
        slot: str = "close",
        notice: str = "",
    ) -> str:
        today = datetime.now(_NEW_YORK).date()
        try:
            selected_date = today if run_date is None else date.fromisoformat(run_date)
        except ValueError:
            selected_date = today
        selected_slot = slot if slot in _SLOTS else "close"
        with closing(sqlite3.connect(path)) as conn:
            status = queries.operator_status(conn, digest_dir, reason_dir, selected_date)
            return views.page(
                "Manual paper cycle",
                views.paper_operator(status, csrf_token, selected_slot, notice=notice),
                active="/operate",
                eyebrow="Operator · paper state",
                wide=True,
            )

    @app.get("/operate/live", response_class=HTMLResponse)
    def operate_live() -> str:
        with closing(sqlite3.connect(path)) as conn:
            profiles = (
                public_profile_status(load_live_profiles(live_config))
                if live_config.is_file()
                else []
            )
            now = datetime.now(UTC)
            payload = queries.live_operator_status(conn, profiles, now=now)
            return views.page(
                "Live operator",
                views.live_operator(payload, now=now),
                active="/operate/live",
                eyebrow="Operator · isolated live state",
                wide=True,
            )

    @app.post("/operate/prepare", response_class=HTMLResponse)
    async def prepare(request: Request) -> Response:
        form = parse_qs((await request.body()).decode("utf-8"), keep_blank_values=True)
        submitted_token = form.get("csrf_token", [""])[0]
        if not secrets.compare_digest(submitted_token, csrf_token):
            raise HTTPException(403, "invalid request token")

        run_date = form.get("date", [""])[0]
        slot = form.get("slot", ["close"])[0]
        selected_slot = slot if slot in _SLOTS else "close"
        try:
            selected_date = date.fromisoformat(run_date)
        except ValueError as error:
            raise HTTPException(400, "invalid session date") from error
        if selected_date > datetime.now(_NEW_YORK).date():
            raise HTTPException(400, "session date can't be in the future")

        def run_preparation() -> Response | None:
            with closing(sqlite3.connect(path)) as conn:
                conn.execute("PRAGMA foreign_keys = ON")
                try:
                    preparation_runner(
                        conn,
                        selected_date,
                        reason_dir / run_date,
                        digest_dir=digest_dir,
                    )
                except Exception as error:
                    status = queries.operator_status(conn, digest_dir, reason_dir, selected_date)
                    return HTMLResponse(
                        views.page(
                            "Manual paper cycle",
                            views.paper_operator(
                                status,
                                csrf_token,
                                selected_slot,
                                error=f"Preparation failed: {type(error).__name__}: {error}",
                            ),
                            active="/operate",
                            eyebrow="Operator · paper state",
                            wide=True,
                        ),
                        status_code=400,
                    )

            return None

        failure = await run_in_threadpool(run_preparation)
        if failure is not None:
            return failure

        query = urlencode(
            {"date": run_date, "slot": selected_slot, "notice": "Preparation completed."}
        )
        return RedirectResponse(f"/operate?{query}", status_code=303)

    @app.get("/portfolio", response_class=HTMLResponse)
    def portfolio() -> str:
        with closing(sqlite3.connect(path)) as conn:
            return views.page(
                "Portfolio",
                views.portfolio(queries.portfolio(conn)),
                active="/portfolio",
                eyebrow="Paper account · persisted state",
            )

    @app.get("/decisions", response_class=HTMLResponse)
    def decisions() -> str:
        with closing(sqlite3.connect(path)) as conn:
            return views.page(
                "Decisions",
                views.decisions(queries.decisions(conn)),
                active="/decisions",
                eyebrow="Investment decision records",
            )

    @app.get("/decisions/{decision_id}", response_class=HTMLResponse)
    def decision_detail(decision_id: str) -> str:
        with closing(sqlite3.connect(path)) as conn:
            payload = queries.decision_detail(conn, decision_id)
            if payload is None:
                raise HTTPException(404, "decision not found")
            ticker = payload["record"].get("ticker", "Decision")
            return views.page(
                f"{ticker} decision trace",
                views.decision_trace(payload),
                active="/decisions",
                eyebrow=f"Decision · {decision_id}",
            )

    @app.get("/executions", response_class=HTMLResponse)
    def executions() -> str:
        with closing(sqlite3.connect(path)) as conn:
            profiles = (
                public_profile_status(load_live_profiles(live_config))
                if live_config.is_file()
                else None
            )
            packets = queries.execution_packets(conn)
            handoffs = queries.execution_handoffs(packets, profiles, now=datetime.now(UTC))
            return views.page(
                "Broker executions",
                views.executions(
                    profiles,
                    packets,
                    handoffs,
                    queries.executions(conn),
                    queries.execution_events(conn),
                ),
                active="/executions",
                eyebrow="Live state · append-only",
                wide=True,
            )

    @app.get("/digests", response_class=HTMLResponse)
    def digests(file: str | None = None) -> str:
        if file is not None:
            selected = digest_dir / Path(file).name
            if not selected.exists():
                raise HTTPException(404, "digest not found")
            digest_text = escape(selected.read_text(encoding="utf-8"))
            body = (
                "<a class='back-link' href='/digests'>← Digest index</a>"
                f"<pre class='prompt' style='max-height:none'>{digest_text}</pre>"
            )
            return views.page(file, body, active="/digests", eyebrow="Rendered digest")
        items = sorted(digest_dir.glob("*.md"), reverse=True) if digest_dir.exists() else []
        listing = (
            "<div class='compact-list'>"
            + "".join(
                "<div class='compact-row'>"
                f"<a href='/digests?file={escape(item.name)}'>{escape(item.name)}</a>"
                f"<span class='quiet'>{item.stat().st_size:,} bytes</span></div>"
                for item in items
            )
            + "</div>"
            if items
            else "<p class='empty'>none yet</p>"
        )
        return views.page("Digests", listing, active="/digests", eyebrow="Research intake")

    @app.get("/x", response_class=HTMLResponse)
    def x_page() -> str:
        with closing(sqlite3.connect(path)) as conn:
            payload = queries.x_data(conn)
            body = "".join(
                "<section class='section'>"
                f"<div class='section-label'>{escape(name)}</div>"
                f"{views.table(value)}</section>"
                for name, value in payload.items()
            )
            return views.page("X", body, active="/x", eyebrow="Curated signal pipeline", wide=True)

    @app.get("/regime", response_class=HTMLResponse)
    def regime() -> str:
        with closing(sqlite3.connect(path)) as conn:
            body = (
                "<div class='mode-strip'><strong>Deterministic output</strong>"
                "<span>Published regime history is displayed as stored. "
                "The dashboard doesn't rescore it.</span></div>"
                f"{views.regime_table(queries.regime(conn))}"
            )
            return views.page("Regime", body, active="/regime", eyebrow="Market posture", wide=True)

    @app.get("/triggers", response_class=HTMLResponse)
    def triggers() -> str:
        with closing(sqlite3.connect(path)) as conn:
            body = (
                "<div class='mode-strip'><strong>Attention signals</strong>"
                "<span>A trigger asks the reasoning agent to inspect evidence. "
                "It doesn't imply a trade.</span></div>"
                f"{views.table(queries.triggers(conn))}"
            )
            return views.page(
                "Triggers", body, active="/triggers", eyebrow="Persisted trigger events", wide=True
            )

    return app


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.dashboard.server")
    parser.add_argument("--db", default="data/boustrategy.db")
    parser.add_argument("--port", type=int, default=8378)
    args = parser.parse_args()
    uvicorn.run(create_app(args.db), host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
