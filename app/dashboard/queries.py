import json
import sqlite3
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from app.paper.broker import STARTING_CASH, cash_balance
from app.x.posts import MAX_MONTHLY_POST_READS


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
        ).fetchone()
        is not None
    )


def rows(conn: sqlite3.Connection, table: str, query: str) -> list[dict[str, Any]] | None:
    if not table_exists(conn, table):
        return None
    cursor = conn.execute(query)
    names = [item[0] for item in cursor.description]
    return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]


def overview(conn: sqlite3.Connection, digest_dir: Path) -> dict[str, Any]:
    result: dict[str, Any] = {}
    positions = rows(
        conn,
        "paper_positions",
        "SELECT ticker, shares FROM paper_positions ORDER BY ticker",
    )
    if positions is not None and table_exists(conn, "daily_prices"):
        value = 0.0
        for position in positions:
            latest = conn.execute(
                "SELECT close FROM daily_prices WHERE ticker = ? ORDER BY bar_date DESC LIMIT 1",
                (position["ticker"],),
            ).fetchone()
            if latest:
                value += position["shares"] * latest[0]
        cash = cash_balance(conn)
        result["paper"] = {"cash": cash, "equity": cash + value, "starting": STARTING_CASH}
    regime = rows(
        conn,
        "regime_snapshots",
        """
        SELECT snapshot_date, regime, score FROM regime_snapshots
        ORDER BY snapshot_date DESC LIMIT 1
        """,
    )
    result["regime"] = regime[0] if regime else None
    if table_exists(conn, "x_post_reads"):
        month = datetime.now(UTC).strftime("%Y-%m")
        row = conn.execute(
            "SELECT post_reads FROM x_post_reads WHERE month = ?", (month,)
        ).fetchone()
        used = row[0] if row else 0
        result["x_reads"] = {"used": used, "remaining": MAX_MONTHLY_POST_READS - used}
    for key, table in (
        ("pending_triggers", "trigger_events"),
        ("pending_articles", "x_article_queue"),
    ):
        if table_exists(conn, table):
            result[key] = conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE status = 'pending'"
            ).fetchone()[0]
    digests = sorted(digest_dir.glob("*.md"), reverse=True) if digest_dir.exists() else []
    result["last_digest"] = digests[0].name if digests else None
    if table_exists(conn, "status_events"):
        result["decision_statuses"] = dict(
            conn.execute(
                """
                SELECT status, COUNT(*) FROM status_events s
                WHERE subject_type = 'decision' AND event_id = (
                    SELECT MAX(event_id) FROM status_events s2 WHERE s2.subject_id = s.subject_id
                ) GROUP BY status
                """
            ).fetchall()
        )
    if table_exists(conn, "order_intents") and table_exists(conn, "broker_execution_records"):
        result["live_intents_awaiting_execution"] = conn.execute(
            """
            SELECT COUNT(*) FROM order_intents o
            LEFT JOIN broker_execution_records b ON b.order_intent_id = o.order_intent_id
            WHERE o.execution_mode = 'LIVE' AND b.broker_execution_record_id IS NULL
            """
        ).fetchone()[0]
    return result


def portfolio(conn: sqlite3.Connection) -> dict[str, Any]:
    positions = None
    intents = None
    if table_exists(conn, "paper_positions") and table_exists(conn, "daily_prices"):
        positions = rows(
            conn,
            "paper_positions",
            """
            SELECT p.ticker, p.shares, p.avg_cost, p.primary_theme_id,
                   (SELECT close FROM daily_prices d WHERE d.ticker = p.ticker
                    ORDER BY bar_date DESC LIMIT 1) AS latest_close
            FROM paper_positions p ORDER BY p.ticker
            """,
        )
        if positions:
            positions_value = sum(
                item["shares"] * (item["latest_close"] or 0) for item in positions
            )
            equity = cash_balance(conn) + positions_value
            for item in positions:
                item["value"] = item["shares"] * (item["latest_close"] or 0)
                item["weight"] = item["value"] / equity if equity else 0.0
                item["unrealized_pl"] = item["shares"] * (
                    (item["latest_close"] or 0) - item["avg_cost"]
                )
    if all(
        table_exists(conn, table)
        for table in ("order_intents", "paper_fills", "broker_execution_records")
    ):
        intents = rows(
            conn,
            "order_intents",
            """
            SELECT o.order_intent_id, o.created_at, o.ticker, o.side, o.execution_mode,
                   CASE
                     WHEN p.fill_id IS NOT NULL THEN 'paper_filled'
                     WHEN b.broker_execution_record_id IS NOT NULL THEN b.status
                     WHEN o.execution_mode = 'LIVE' THEN 'awaiting_execution'
                     ELSE 'awaiting_price'
                   END AS status
            FROM order_intents o
            LEFT JOIN paper_fills p ON p.order_intent_id = o.order_intent_id
            LEFT JOIN broker_execution_records b ON b.order_intent_id = o.order_intent_id
            ORDER BY o.created_at DESC
            """,
        )
    return {
        "positions": positions,
        "intents": intents,
        "fills": rows(conn, "paper_fills", "SELECT * FROM paper_fills ORDER BY fill_date DESC"),
        "equity_series": equity_series(conn),
    }


def equity_series(conn: sqlite3.Connection) -> list[float] | None:
    if not table_exists(conn, "paper_fills") or not table_exists(conn, "daily_prices"):
        return None
    dates = [
        row[0]
        for row in conn.execute("SELECT DISTINCT bar_date FROM daily_prices ORDER BY bar_date")
    ]
    series: list[float] = []
    for day in dates:
        cash = STARTING_CASH
        shares: dict[str, float] = {}
        fills = conn.execute(
            "SELECT ticker, side, shares, price FROM paper_fills WHERE fill_date <= ?", (day,)
        ).fetchall()
        for ticker, side, amount, price in fills:
            direction = 1 if side == "BUY" else -1
            shares[ticker] = shares.get(ticker, 0.0) + direction * amount
            cash -= direction * amount * price
        value = cash
        for ticker, amount in shares.items():
            close = conn.execute(
                """
                SELECT close FROM daily_prices WHERE ticker = ? AND bar_date <= ?
                ORDER BY bar_date DESC LIMIT 1
                """,
                (ticker, day),
            ).fetchone()
            if close is not None:
                value += amount * close[0]
        series.append(value)
    return series


def decisions(conn: sqlite3.Connection) -> list[dict[str, Any]] | None:
    items = rows(
        conn,
        "decision_records",
        """
        SELECT decision_id, created_at, ticker, decision, record_json
        FROM decision_records ORDER BY created_at DESC
        """,
    )
    if items is None:
        return None
    for item in items:
        record = json.loads(item["record_json"])
        item["regime"] = record.get("regime_state")
        item["extraordinary"] = record.get("extraordinary_opportunity", False)
        events = (
            conn.execute(
                """
                SELECT status, occurred_at, detail FROM status_events
                WHERE subject_id = ? ORDER BY event_id
                """,
                (item["decision_id"],),
            ).fetchall()
            if table_exists(conn, "status_events")
            else []
        )
        item["events"] = events
        item["final_status"] = events[-1][0] if events else ""
        item["policy_reasons"] = events[-1][2] if events else ""
    return items


def x_data(conn: sqlite3.Connection) -> dict[str, Any]:
    accounts = None
    if all(table_exists(conn, table) for table in ("x_accounts", "x_posts", "x_route_decisions")):
        accounts = rows(
            conn,
            "x_accounts",
            """
            SELECT a.handle, COUNT(p.post_id) AS fetched,
              SUM(CASE WHEN r.rank = 'headline' THEN 1 ELSE 0 END) AS headline,
              SUM(CASE WHEN r.rank = 'notable' THEN 1 ELSE 0 END) AS notable,
              SUM(CASE WHEN r.rank = 'context' THEN 1 ELSE 0 END) AS context
            FROM x_accounts a LEFT JOIN x_posts p ON p.handle = a.handle
            LEFT JOIN x_route_decisions r ON r.post_id = p.post_id GROUP BY a.handle
            """,
        )
    return {
        "runs": rows(conn, "x_runs", "SELECT * FROM x_runs ORDER BY started_at DESC"),
        "accounts": accounts,
        "articles": rows(
            conn, "x_article_queue", "SELECT * FROM x_article_queue ORDER BY queued_at DESC"
        ),
    }


def regime(conn: sqlite3.Connection) -> list[dict[str, Any]] | None:
    return rows(
        conn,
        "regime_snapshots",
        "SELECT * FROM regime_snapshots ORDER BY snapshot_date DESC",
    )


def triggers(conn: sqlite3.Connection) -> list[dict[str, Any]] | None:
    return rows(
        conn,
        "trigger_events",
        "SELECT * FROM trigger_events ORDER BY status, fired_at DESC",
    )


def executions(conn: sqlite3.Connection) -> list[dict[str, Any]] | None:
    return rows(
        conn,
        "broker_execution_records",
        """
        SELECT broker_execution_record_id, order_intent_id, execution_packet_id,
               execution_profile_id, account_alias, submitted_at, ticker, side, status,
               broker_order_id
        FROM broker_execution_records ORDER BY submitted_at DESC
        """,
    )


def execution_events(conn: sqlite3.Connection) -> list[dict[str, Any]] | None:
    return rows(
        conn,
        "broker_execution_events",
        """
        SELECT broker_event_id, broker_execution_record_id, order_intent_id,
               execution_packet_id, execution_profile_id, status, occurred_at, detail
        FROM broker_execution_events ORDER BY occurred_at DESC, rowid DESC
        """,
    )


def execution_packets(conn: sqlite3.Connection) -> list[dict[str, Any]] | None:
    return rows(
        conn,
        "live_execution_packets",
        """
        SELECT execution_packet_id, order_intent_id, execution_profile_id, created_at,
               expires_at, ticker, side, notional, limit_price,
               EXISTS (
                   SELECT 1 FROM broker_execution_records
                   WHERE broker_execution_records.order_intent_id =
                         live_execution_packets.order_intent_id
               ) AS executed
        FROM live_execution_packets ORDER BY created_at DESC
        """,
    )


def live_operator_status(
    conn: sqlite3.Connection,
    profiles: list[dict[str, object]],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    current_time = now or datetime.now(UTC)
    latest_shared = conn.execute(
        """
        SELECT session_date, slot, shared_bundle_sha256, run_json
        FROM reasoning_runs ORDER BY started_at DESC, reasoning_run_id DESC LIMIT 1
        """
    ).fetchone()
    shared = None
    if latest_shared is not None:
        run_json = json.loads(latest_shared[3])
        shared = {
            "session_date": latest_shared[0],
            "slot": latest_shared[1],
            "shared_bundle_path": run_json["shared_bundle_path"],
            "shared_bundle_sha256": latest_shared[2],
        }

    profile_rows = []
    for profile in profiles:
        profile_id = str(profile["execution_profile_id"])
        snapshot_row = conn.execute(
            """
            SELECT snapshot_json FROM live_portfolio_snapshots
            WHERE execution_profile_id = ? ORDER BY captured_at DESC LIMIT 1
            """,
            (profile_id,),
        ).fetchone()
        snapshot = None
        if snapshot_row is not None:
            snapshot_json = json.loads(snapshot_row[0])
            snapshot = {
                "portfolio_snapshot_id": snapshot_json["portfolio_snapshot_id"],
                "captured_at": snapshot_json["captured_at"],
                "account_equity": snapshot_json["account_equity"],
                "buying_power": snapshot_json["buying_power"],
                "positions": [
                    {
                        "ticker": position["ticker"],
                        "market_value": position["market_value"],
                        "primary_theme_id": position["primary_theme_id"],
                    }
                    for position in snapshot_json["positions"]
                ],
            }

        run_row = (
            conn.execute(
                """
                SELECT run_json FROM reasoning_runs
                WHERE execution_profile_id = ? AND session_date = ? AND slot = ?
                ORDER BY started_at DESC, reasoning_run_id DESC LIMIT 1
                """,
                (profile_id, shared["session_date"], shared["slot"]),
            ).fetchone()
            if shared
            else None
        )
        run = None
        if run_row is not None:
            run_json = json.loads(run_row[0])
            run = {
                "reasoning_run_id": run_json["reasoning_run_id"],
                "portfolio_snapshot_id": run_json["portfolio_snapshot_id"],
                "result": run_json["result"],
                "public_summary": run_json["public_summary"],
                "decision_count": len(run_json["decision_ids"]),
            }

        packet_rows = conn.execute(
            """
            SELECT p.execution_packet_id, p.expires_at,
                   EXISTS (
                       SELECT 1 FROM broker_execution_records r
                       WHERE r.order_intent_id = p.order_intent_id
                   )
            FROM live_execution_packets p WHERE p.execution_profile_id = ?
            ORDER BY p.created_at DESC
            """,
            (profile_id,),
        ).fetchall()
        pending_packets = [
            packet
            for packet in packet_rows
            if not packet[2] and datetime.fromisoformat(packet[1]) > current_time
        ]
        event_row = conn.execute(
            """
            SELECT status, detail FROM broker_execution_events
            WHERE execution_profile_id = ? ORDER BY occurred_at DESC, rowid DESC LIMIT 1
            """,
            (profile_id,),
        ).fetchone()
        profile_rows.append(
            {
                "execution_profile_id": profile_id,
                "agent_provider": profile["agent_provider"],
                "enabled": profile["enabled"],
                "account_bound": profile["account_bound"],
                "snapshot": snapshot,
                "run": run,
                "pending_packet_count": len(pending_packets),
                "execution_packet_id": pending_packets[0][0] if pending_packets else None,
                "execution_status": event_row[0] if event_row else None,
                "execution_error": event_row[1] if event_row else "",
            }
        )
    return {"shared": shared, "profiles": profile_rows}


def operator_status(
    conn: sqlite3.Connection, digest_dir: Path, reason_dir: Path, on_date: date
) -> dict[str, Any]:
    day = on_date.isoformat()
    digest_path = digest_dir / f"{day}.md"
    output_dir = reason_dir / day
    receipt_path = output_dir / "preparation.json"
    bundle_path = output_dir / "bundle.md"
    cursor = conn.execute(
        """
        SELECT run_id, slot, posts_fetched, posts_exported, reads_used, status
        FROM x_runs WHERE substr(run_id, 1, 10) = ? ORDER BY started_at, run_id
        """,
        (day,),
    )
    names = [item[0] for item in cursor.description]
    runs = [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]
    receipt = None
    receipt_error = ""
    if receipt_path.is_file():
        try:
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            receipt_error = str(error)
    return {
        "date": day,
        "digest_exists": digest_path.is_file(),
        "digest_path": digest_path.as_posix(),
        "runs": runs,
        "digest_ready": bool(runs)
        and digest_path.is_file()
        and all(run["status"] == "digested" for run in runs),
        "prepared": receipt is not None and bundle_path.is_file(),
        "receipt": receipt,
        "receipt_error": receipt_error,
        "receipt_path": receipt_path.as_posix(),
        "bundle_path": bundle_path.as_posix(),
    }
