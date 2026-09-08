"""Bounded reads from the published store, with restartable query snapshots."""

import base64
import binascii
import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.dashboard.queries import table_exists


class Cursor(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=0, le=2**63 - 1)
    high_water: int = Field(ge=0, le=2**63 - 1)
    query: str
    created_at: str = Field(min_length=1, max_length=64)
    public_id: str = Field(min_length=1, max_length=200)
    exact_ticker: int = Field(default=0, ge=0, le=1)


class RestartRequired(ValueError):
    pass


def metadata(conn: sqlite3.Connection) -> dict[str, Any]:
    row = (
        conn.execute(
            "SELECT revision, updated_at FROM publication_meta WHERE singleton=1"
        ).fetchone()
        if table_exists(conn, "publication_meta")
        else None
    )
    return {
        "api_version": 2,
        "revision": row[0] if row else 0,
        "published_at": row[1] if row else None,
        "server_now": datetime.now(UTC).isoformat(),
    }


def portfolio(
    conn: sqlite3.Connection, portfolio_id: str, *, refresh_position_links: bool = True
) -> dict[str, Any] | None:
    if portfolio_id not in {"live", "paper"}:
        return None
    row = (
        conn.execute(
            "SELECT content FROM public_portfolios WHERE portfolio_id=?", (portfolio_id,)
        ).fetchone()
        if table_exists(conn, "public_portfolios")
        else None
    )
    if row:
        result = json.loads(row[0])
        # Retractions must also remove any denormalized position links and summaries.
        if refresh_position_links:
            for position in result["positions"]:
                latest = conn.execute(
                    "SELECT public_id, summary FROM public_decisions WHERE portfolio_id=? AND "
                    "ticker=? AND revoked=0 AND withdrawn=0 ORDER BY created_at DESC, "
                    "public_id DESC LIMIT 1",
                    (portfolio_id, position["ticker"]),
                ).fetchone()
                position["latest_decision_id"] = latest[0] if latest else None
                position["latest_public_summary"] = latest[1] if latest else None
        return dict(result)
    return {
        "portfolio_id": portfolio_id,
        "name": "BouStrategy" if portfolio_id == "live" else "BouStrategy paper",
        "mode": portfolio_id,
        "is_default": portfolio_id == "live",
        "status": "unavailable",
        "reason": "not_published",
        "data_as_of": None,
        "equity": None,
        "cash": None,
        "return_percent": None,
        "positions": [],
        "history": [],
        "capabilities": {"returns": False, "cash": False, "quantities": False},
    }


def feed(
    conn: sqlite3.Connection,
    *,
    portfolio_id: str,
    limit: int = 25,
    cursor: str | None = None,
    q: str = "",
    ticker: str | None = None,
    action: str | None = None,
    policy: str | None = None,
    lifecycle: str | None = None,
    since: str | None = None,
    until: str | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    if any(ord(char) < 32 and not char.isspace() or ord(char) == 127 for char in q):
        raise ValueError("invalid_search_control_character")
    q = " ".join(q.split())
    meta = metadata(conn)
    signature = hashlib.sha256(
        json.dumps(
            [portfolio_id, q, ticker, action, policy, lifecycle, since, until, run_id]
        ).encode()
    ).hexdigest()
    after = None
    if cursor:
        try:
            after = Cursor.model_validate_json(base64.urlsafe_b64decode(cursor.encode()).decode())
        except (ValueError, UnicodeError, binascii.Error, ValidationError) as exc:
            raise ValueError("invalid_cursor") from exc
        if after.query != signature:
            raise ValueError("cursor_query_mismatch")
        if after.revision != meta["revision"]:
            raise RestartRequired("publication_changed")
    if not table_exists(conn, "public_decisions"):
        return {**meta, "portfolio_id": portfolio_id, "items": [], "next_cursor": None, "total": 0}
    high_water = (
        after.high_water
        if after
        else conn.execute("SELECT COALESCE(MAX(sequence), 0) FROM public_decisions").fetchone()[0]
    )
    clauses = ["portfolio_id=?", "revoked=0", "withdrawn=0", "sequence<=?"]
    params: list[Any] = [portfolio_id, high_water]
    if run_id:
        clauses.append("json_extract(content, '$.public_run_id')=?")
        params.append(run_id)
    for column, value in (
        ("ticker", ticker),
        ("action", action),
        ("policy", policy),
        ("lifecycle", lifecycle),
    ):
        if value:
            clauses.append(f"{column}=?")
            params.append(value)
    if since:
        clauses.append("created_at>=?")
        params.append(since)
    if until:
        clauses.append("created_at<?")
        params.append(until)
    if q.strip():
        terms = ['"' + term.replace('"', '""') + '"*' for term in q.split()]
        clauses.append("sequence IN (SELECT rowid FROM public_search WHERE public_search MATCH ?)")
        params.append(" AND ".join(terms))
    where = " AND ".join(clauses)
    total = conn.execute(f"SELECT COUNT(*) FROM public_decisions WHERE {where}", params).fetchone()[
        0
    ]
    rank = "CASE WHEN ticker = ? THEN 1 ELSE 0 END" if q.strip() else "0"
    search_ticker = q.strip().upper()
    if after:
        if q.strip():
            where += f" AND ({rank}, created_at, public_id) < (?, ?, ?)"
            params.extend([search_ticker, after.exact_ticker, after.created_at, after.public_id])
        else:
            where += " AND (created_at, public_id) < (?, ?)"
            params.extend([after.created_at, after.public_id])
    ordering = "exact_ticker DESC, " if q.strip() else ""
    if q.strip():
        params.insert(0, search_ticker)
    has_compact = any(
        row[1] == "feed_content" for row in conn.execute("PRAGMA table_info(public_decisions)")
    )
    content_column = "feed_content" if has_compact else "content"
    rows = conn.execute(
        f"SELECT created_at, public_id, {content_column}, {rank} AS exact_ticker "
        f"FROM public_decisions WHERE {where} "
        f"ORDER BY {ordering}created_at DESC, public_id DESC LIMIT ?",
        (*params, limit + 1),
    ).fetchall()
    more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = None
    if more:
        token = Cursor(
            revision=meta["revision"],
            high_water=high_water,
            query=signature,
            created_at=rows[-1][0],
            public_id=rows[-1][1],
            exact_ticker=rows[-1][3],
        )
        next_cursor = base64.urlsafe_b64encode(token.model_dump_json().encode()).decode()
    items = [json.loads(row[2]) for row in rows]
    if not has_compact:
        items = [
            {
                key: value
                for key, value in item.items()
                if key
                in {
                    "ticker",
                    "created_at",
                    "decision",
                    "public_summary",
                    "policy_outcome",
                    "schema_outcome",
                    "lifecycle",
                    "regime",
                    "theme",
                    "public_id",
                    "portfolio_id",
                    "mode",
                    "company_name",
                }
            }
            for item in items
        ]
        for item in items:
            item["summary_truncated"] = len(item.get("public_summary", "")) > 600
            item["public_summary"] = item.get("public_summary", "")[:600]
    return {
        **meta,
        "portfolio_id": portfolio_id,
        "items": items,
        "next_cursor": next_cursor,
        "total": total,
        "snapshot": {"revision": meta["revision"], "high_water": high_water},
    }


def detail(conn: sqlite3.Connection, public_id: str) -> dict[str, Any] | None:
    row = (
        conn.execute(
            "SELECT content, revoked, withdrawn FROM public_decisions WHERE public_id=?",
            (public_id,),
        ).fetchone()
        if table_exists(conn, "public_decisions")
        else None
    )
    if row is None:
        return None
    if row[1] or row[2]:
        return {"status": "retracted", "public_id": public_id}
    return {**metadata(conn), **json.loads(row[0])}


def policy_catalog(conn: sqlite3.Connection, portfolio_id: str) -> dict[str, Any]:
    row = (
        conn.execute(
            "SELECT content FROM public_policy WHERE portfolio_id=?", (portfolio_id,)
        ).fetchone()
        if table_exists(conn, "public_policy")
        else None
    )
    if row is None:
        return {**metadata(conn), "status": "unavailable", "reason": "not_published"}
    payload = json.loads(row[0])
    for rule in payload["decision_rules"]:
        triggered = conn.execute(
            "SELECT d.public_id, t.evaluated_at FROM public_rule_triggers t "
            "JOIN public_decisions d ON d.public_id=t.public_id "
            "WHERE t.portfolio_id=? AND t.rule_id=? AND d.revoked=0 AND d.withdrawn=0 "
            "ORDER BY t.evaluated_at DESC, t.public_id DESC LIMIT 1",
            (portfolio_id, rule["rule_id"]),
        ).fetchone()
        rule["last_triggered"] = (
            {"public_id": triggered[0], "created_at": triggered[1]} if triggered else None
        )
    return {**metadata(conn), "portfolio_id": portfolio_id, "status": "available", **payload}
