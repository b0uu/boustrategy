import argparse
import json
import logging
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

import uvicorn
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from app.dashboard.queries import table_exists
from app.public import activity, queries
from app.public.database import open_readonly
from app.public.exports import decision_csv


def create_public_app(
    public_db_path: str | Path,
    frontend_dir: str | Path = "public-ui/dist",
) -> FastAPI:
    app = FastAPI(
        title="BouStrategy public dashboard", docs_url=None, redoc_url=None, openapi_url=None
    )
    published = Path(public_db_path)
    assets = Path(frontend_dir)
    app.add_middleware(GZipMiddleware, minimum_size=1000, compresslevel=5)

    @app.middleware("http")
    async def private_cache(request: Request, call_next: Any) -> Any:
        response = await call_next(request)
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(sqlite3.Error)
    async def unavailable(request: Request, exc: sqlite3.Error) -> JSONResponse:
        logging.getLogger(__name__).exception("Public store read failed", exc_info=exc)
        return JSONResponse(
            status_code=503,
            content={"detail": "public_data_unavailable"},
            headers={"Retry-After": "30"},
        )

    @app.api_route("/api/public/v2/portfolios", methods=["GET", "HEAD"])
    def portfolios() -> dict[str, Any]:
        with open_readonly(published) as conn:
            return {
                **queries.metadata(conn),
                "default_portfolio_id": "live",
                "items": [
                    {
                        key: value
                        for key, value in (
                            queries.portfolio(conn, scope, refresh_position_links=False) or {}
                        ).items()
                        if key
                        in {"portfolio_id", "name", "mode", "is_default", "status", "capabilities"}
                    }
                    for scope in ("live", "paper")
                ],
            }

    @app.api_route("/api/public/v2/portfolios/{portfolio_id}/overview", methods=["GET", "HEAD"])
    def overview(portfolio_id: str) -> dict[str, Any]:
        with open_readonly(published) as conn:
            result = queries.portfolio(conn, portfolio_id, refresh_position_links=False)
            if result is None:
                raise HTTPException(404, "portfolio_not_found")
            result.pop("positions")
            today = datetime.now(ZoneInfo("America/New_York")).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            if "decision_counts" not in result and table_exists(conn, "public_decisions"):
                result["decision_counts"] = {
                    "approved": 0,
                    "rejected": 0,
                    "unavailable": 0,
                }
                for policy, count in conn.execute(
                    "SELECT policy, COUNT(*) FROM public_decisions WHERE portfolio_id=? AND "
                    "revoked=0 AND withdrawn=0 GROUP BY policy",
                    (portfolio_id,),
                ):
                    result["decision_counts"][policy] = count
            result.setdefault("decision_counts", {"approved": 0, "rejected": 0, "unavailable": 0})
            if result.get("decision_count_date") == today.date().isoformat():
                result["decisions_today"] = result.get("decisions_today", 0)
            elif "decision_count_date" in result:
                result["decisions_today"] = 0
            elif table_exists(conn, "public_decisions"):
                result["decisions_today"] = conn.execute(
                    "SELECT COUNT(*) FROM public_decisions WHERE portfolio_id=? "
                    "AND revoked=0 AND withdrawn=0 AND created_at>=? AND created_at<?",
                    (
                        portfolio_id,
                        today.astimezone(UTC).isoformat(),
                        (today + timedelta(days=1)).astimezone(UTC).isoformat(),
                    ),
                ).fetchone()[0]
            else:
                result["decisions_today"] = 0
            return {**queries.metadata(conn), **result}

    @app.api_route("/api/public/v2/portfolios/{portfolio_id}/runtime", methods=["GET", "HEAD"])
    def runtime(portfolio_id: Literal["live", "paper"]) -> dict[str, Any]:
        with open_readonly(published) as conn:
            return {
                **queries.metadata(conn),
                "portfolio_id": portfolio_id,
                **activity.runtime_status(conn, portfolio_id, datetime.now(UTC)),
            }

    @app.api_route("/api/public/v2/portfolios/{portfolio_id}/activity", methods=["GET", "HEAD"])
    def activity_history(
        portfolio_id: Literal["live", "paper"],
        limit: int = Query(25, ge=1, le=100),
        cursor: str | None = Query(None, max_length=2048),
    ) -> dict[str, Any]:
        with open_readonly(published) as conn:
            try:
                return {
                    **queries.metadata(conn),
                    "portfolio_id": portfolio_id,
                    **activity.history(conn, portfolio_id, limit=limit, cursor=cursor),
                }
            except queries.RestartRequired as exc:
                raise HTTPException(409, str(exc)) from exc
            except (ValueError, UnicodeError) as exc:
                raise HTTPException(422, "invalid_activity_cursor") from exc

    @app.api_route(
        "/api/public/v2/portfolios/{portfolio_id}/activity/{public_id}", methods=["GET", "HEAD"]
    )
    def activity_detail(portfolio_id: Literal["live", "paper"], public_id: str) -> dict[str, Any]:
        with open_readonly(published) as conn:
            row = (
                conn.execute(
                    "SELECT content FROM public_activity WHERE portfolio_id=? AND public_id=?",
                    (portfolio_id, public_id),
                ).fetchone()
                if table_exists(conn, "public_activity")
                else None
            )
            if row is None:
                raise HTTPException(404, "activity_not_found")
            return {**queries.metadata(conn), "portfolio_id": portfolio_id, **json.loads(row[0])}

    @app.api_route("/api/public/v2/portfolios/{portfolio_id}/positions", methods=["GET", "HEAD"])
    def positions(portfolio_id: str) -> dict[str, Any]:
        with open_readonly(published) as conn:
            result = queries.portfolio(conn, portfolio_id)
            if result is None:
                raise HTTPException(404, "portfolio_not_found")
            return {
                **queries.metadata(conn),
                "portfolio_id": portfolio_id,
                "mode": result["mode"],
                "status": result.get("holdings_status", result["status"]),
                "valuation_status": result["status"],
                "reason": None
                if result.get("holdings_status") == "available"
                else result.get("reason"),
                "data_as_of": result["data_as_of"],
                "items": result["positions"],
            }

    @app.api_route("/api/public/v2/portfolios/{portfolio_id}/performance", methods=["GET", "HEAD"])
    def performance(
        portfolio_id: Literal["live", "paper"], range: Literal["1M", "3M", "YTD", "All"] = "All"
    ) -> dict[str, Any]:
        with open_readonly(published) as conn:
            row = (
                conn.execute(
                    "SELECT content FROM public_performance WHERE portfolio_id=? AND range_name=?",
                    (portfolio_id, range),
                ).fetchone()
                if table_exists(conn, "public_performance")
                else None
            )
            payload = (
                json.loads(row[0])
                if row
                else {
                    "range": range,
                    "status": "unavailable",
                    "reason": "reporting_history_missing",
                    "history": [],
                    "return_percent": None,
                }
            )
            return {
                **queries.metadata(conn),
                "portfolio_id": portfolio_id,
                "mode": portfolio_id,
                **payload,
            }

    @app.api_route("/api/public/v2/decisions", methods=["GET", "HEAD"])
    def decisions(
        portfolio_id: Literal["live", "paper"] = "live",
        limit: int = Query(25, ge=1, le=100),
        cursor: str | None = Query(None, max_length=2048),
        q: str = Query("", max_length=200),
        ticker: str | None = Query(None, pattern=r"^[A-Z][A-Z0-9.-]{0,11}$"),
        action: Literal["BUY", "ADD", "TRIM", "SELL", "HOLD", "PASS", "WATCHLIST"] | None = None,
        policy: Literal["approved", "rejected", "unavailable"] | None = None,
        lifecycle: str | None = Query(None, pattern=r"^[a-z_]{1,50}$"),
        since: datetime | None = None,
        until: datetime | None = None,
        run_id: str | None = Query(None, pattern=r"^run_[a-f0-9]{32}$"),
    ) -> dict[str, Any]:
        if any(value and value.tzinfo is None for value in (since, until)):
            raise HTTPException(422, "filter_times_require_timezone")
        if since and until and since >= until:
            raise HTTPException(422, "invalid_date_range")
        with open_readonly(published) as conn:
            try:
                return queries.feed(
                    conn,
                    portfolio_id=portfolio_id,
                    limit=limit,
                    cursor=cursor,
                    q=q,
                    ticker=ticker,
                    action=action,
                    policy=policy,
                    lifecycle=lifecycle,
                    run_id=run_id,
                    since=since.astimezone(UTC).isoformat() if since else None,
                    until=until.astimezone(UTC).isoformat() if until else None,
                )
            except queries.RestartRequired as exc:
                raise HTTPException(409, {"code": "restart_required", "reason": str(exc)}) from exc
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc

    @app.api_route("/api/public/v2/decisions/{public_id}", methods=["GET", "HEAD"])
    def decision_detail(public_id: str) -> dict[str, Any]:
        with open_readonly(published) as conn:
            result = queries.detail(conn, public_id)
            if result is None:
                raise HTTPException(404, "decision_not_found")
            if result.get("status") == "retracted":
                raise HTTPException(410, "decision_retracted")
            return result

    @app.api_route("/api/public/v2/legacy-decisions/{ticker}/{created_at}", methods=["GET", "HEAD"])
    def legacy_link_detail(ticker: str, created_at: str) -> dict[str, Any]:
        try:
            instant = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise HTTPException(404, "decision_not_found") from exc
        if instant.tzinfo is None:
            raise HTTPException(404, "decision_not_found")
        with open_readonly(published) as conn:
            matches = conn.execute(
                "SELECT public_id FROM public_decisions WHERE ticker=? AND created_at=?",
                (ticker, instant.astimezone(UTC).isoformat()),
            ).fetchall()
        if len(matches) != 1:
            raise HTTPException(404, "decision_not_found")
        return decision_detail(matches[0][0])

    @app.api_route("/api/public/v2/portfolios/{portfolio_id}/policy", methods=["GET", "HEAD"])
    def policy(portfolio_id: Literal["live", "paper"]) -> dict[str, Any]:
        with open_readonly(published) as conn:
            return queries.policy_catalog(conn, portfolio_id)

    @app.api_route("/api/public/v2/decisions/{public_id}/export", methods=["GET", "HEAD"])
    def export(public_id: str, format: Literal["json", "csv"] = "json") -> Response:
        result = decision_detail(public_id)
        if format == "json":
            return JSONResponse(
                result, headers={"Content-Disposition": "attachment; filename=decision.json"}
            )
        return Response(
            decision_csv(result),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=decision.csv"},
        )

    @app.api_route("/api/{path_name:path}", methods=["GET", "HEAD"])
    def unknown_api(path_name: str) -> None:
        raise HTTPException(404, "api_route_not_found")

    if assets.is_dir():
        if (assets / "assets").is_dir():
            app.mount("/assets", StaticFiles(directory=assets / "assets"), name="public-assets")

        @app.get("/{path_name:path}", response_class=FileResponse)
        def frontend(path_name: str) -> FileResponse:
            if (
                path_name
                and path_name != "agent-dashboard"
                and not path_name.startswith("decisions/")
            ):
                raise HTTPException(404, "page_not_found")
            return FileResponse(assets / "index.html")

    return app


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.public.server")
    parser.add_argument("--public-db", required=True)
    parser.add_argument("--port", type=int, default=8380)
    args = parser.parse_args()
    uvicorn.run(create_public_app(args.public_db), host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
