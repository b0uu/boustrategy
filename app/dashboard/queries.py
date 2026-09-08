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
    return selected_rows(conn, query)


def selected_rows(
    conn: sqlite3.Connection,
    query: str,
    parameters: tuple[object, ...] = (),
) -> list[dict[str, Any]]:
    cursor = conn.execute(query, parameters)
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
        complete_prices = True
        for position in positions:
            latest = conn.execute(
                "SELECT close FROM daily_prices WHERE ticker = ? ORDER BY bar_date DESC LIMIT 1",
                (position["ticker"],),
            ).fetchone()
            if latest:
                value += position["shares"] * latest[0]
            else:
                complete_prices = False
        cash = cash_balance(conn)
        result["paper"] = {
            "cash": cash,
            "equity": cash + value if complete_prices else None,
            "starting": STARTING_CASH,
        }
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
        result["policy_outcomes"] = dict(
            conn.execute(
                """
                SELECT status, COUNT(*) FROM status_events
                WHERE subject_type = 'decision'
                  AND status IN ('policy_approved', 'policy_rejected')
                GROUP BY status
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
    result["positions"] = portfolio(conn)["positions"]
    recent_decisions = decisions(conn)
    result["recent_decisions"] = recent_decisions[:8] if recent_decisions else recent_decisions
    result["operational"] = {
        "digest": "available" if result["last_digest"] else "unavailable",
        "regime": "available" if result["regime"] else "unavailable",
        "paper_portfolio": "available" if result.get("paper") else "unavailable",
        "live_handoff": (
            "pending"
            if result.get("live_intents_awaiting_execution", 0)
            else "clear"
            if "live_intents_awaiting_execution" in result
            else "unavailable"
        ),
    }
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
            complete_prices = all(item["latest_close"] is not None for item in positions)
            equity = (
                (
                    cash_balance(conn)
                    + sum(item["shares"] * item["latest_close"] for item in positions)
                )
                if complete_prices
                else None
            )
            for item in positions:
                price = item["latest_close"]
                item["value"] = item["shares"] * price if price is not None else None
                item["weight"] = item["value"] / equity if equity else None
                item["unrealized_pl"] = (
                    item["shares"] * (price - item["avg_cost"]) if price is not None else None
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
    from app.performance.paper import paper_observations
    from app.schemas.reporting import ValuationObservation

    observations, issue = paper_observations(conn)
    if issue:
        return None
    return [
        float(value.equity)
        for value in observations
        if isinstance(value, ValuationObservation) and value.complete and value.equity is not None
    ]


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
        item["public_summary"] = record.get("public_summary", "")
        item["primary_theme"] = record.get("primary_theme_id")
        item["target_weight"] = record.get("final_target_weight")
        item["operating_mode"] = record.get("operating_mode")
        del item["record_json"]
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


def decision_detail(conn: sqlite3.Connection, decision_id: str) -> dict[str, Any] | None:
    if not table_exists(conn, "decision_records"):
        return None
    row = conn.execute(
        "SELECT record_json FROM decision_records WHERE decision_id = ?", (decision_id,)
    ).fetchone()
    if row is None:
        return None
    record = json.loads(row[0])

    status_events = []
    if table_exists(conn, "status_events"):
        status_events = selected_rows(
            conn,
            """
            SELECT status, occurred_at, detail FROM status_events
            WHERE subject_type = 'decision' AND subject_id = ?
            ORDER BY event_id
            """,
            (decision_id,),
        )

    statuses = [event["status"] for event in status_events]
    schema_result = (
        "failed"
        if "schema_failed" in statuses
        else "passed"
        if "schema_validated" in statuses
        else "unavailable"
    )
    policy_result = (
        "rejected"
        if "policy_rejected" in statuses
        else "approved"
        if "policy_approved" in statuses
        else "unavailable"
    )
    policy_reasons = []
    for event in status_events:
        if event["status"] == "policy_rejected":
            policy_reasons = [reason.strip() for reason in event["detail"].split(",") if reason]

    trigger = None
    trigger_id = record.get("trigger_id")
    if trigger_id and table_exists(conn, "trigger_events"):
        trigger_row = conn.execute(
            """
            SELECT trigger_id, trigger_type, subject, fired_at, details_json, status
            FROM trigger_events WHERE trigger_id = ?
            """,
            (trigger_id,),
        ).fetchone()
        if trigger_row is not None:
            trigger_details = json.loads(trigger_row[4])
            trigger = {
                "trigger_id": trigger_row[0],
                "trigger_type": trigger_row[1],
                "subject": trigger_row[2],
                "fired_at": trigger_row[3],
                "details": trigger_details,
                "status": trigger_row[5],
            }

    regime_evidence = None
    created_at = record.get("created_at")
    if created_at and table_exists(conn, "regime_snapshots"):
        regime_row = conn.execute(
            """
            SELECT snapshot_date, regime, raw_regime, score, components_json, computed_at
            FROM regime_snapshots WHERE snapshot_date <= substr(?, 1, 10)
            ORDER BY snapshot_date DESC LIMIT 1
            """,
            (str(created_at),),
        ).fetchone()
        if regime_row is not None:
            regime_evidence = {
                "snapshot_date": regime_row[0],
                "regime": regime_row[1],
                "raw_regime": regime_row[2],
                "score": regime_row[3],
                "components": json.loads(regime_row[4]),
                "computed_at": regime_row[5],
            }

    intent = None
    if table_exists(conn, "order_intents"):
        intent_row = conn.execute(
            """
            SELECT order_intent_id, created_at, ticker, side, execution_mode,
                   execution_profile_id, intent_json
            FROM order_intents WHERE decision_id = ?
            """,
            (decision_id,),
        ).fetchone()
        if intent_row is not None:
            intent_json = json.loads(intent_row[6])
            intent = {
                "order_intent_id": intent_row[0],
                "created_at": intent_row[1],
                "ticker": intent_row[2],
                "side": intent_row[3],
                "execution_mode": intent_row[4],
                "execution_profile_id": intent_row[5],
                "order_type": intent_json.get("order_type"),
                "target_weight": intent_json.get("target_weight"),
                "status": intent_json.get("status", "CREATED"),
            }

    reasoning_run = None
    if all(table_exists(conn, table) for table in ("reasoning_run_decisions", "reasoning_runs")):
        run_row = conn.execute(
            """
            SELECT r.reasoning_run_id, r.session_date, r.slot, r.execution_profile_id,
                   r.model_label, r.result, r.started_at, r.completed_at,
                   l.submission_snapshot_id
            FROM reasoning_run_decisions l
            JOIN reasoning_runs r ON r.reasoning_run_id = l.reasoning_run_id
            WHERE l.decision_id = ?
            """,
            (decision_id,),
        ).fetchone()
        if run_row is not None:
            reasoning_run = {
                "reasoning_run_id": run_row[0],
                "session_date": run_row[1],
                "slot": run_row[2],
                "execution_profile_id": run_row[3],
                "model_label": run_row[4],
                "result": run_row[5],
                "started_at": run_row[6],
                "completed_at": run_row[7],
                "submission_snapshot_id": run_row[8],
            }

    packets = []
    if intent and table_exists(conn, "live_execution_packets"):
        packets = selected_rows(
            conn,
            """
            SELECT execution_packet_id, execution_profile_id, created_at, expires_at,
                   ticker, side, notional, limit_price
            FROM live_execution_packets WHERE order_intent_id = ? ORDER BY created_at
            """,
            (intent["order_intent_id"],),
        )

    executions = []
    if intent and table_exists(conn, "broker_execution_records"):
        executions = selected_rows(
            conn,
            """
            SELECT broker_execution_record_id, execution_packet_id,
                   execution_profile_id, submitted_at, ticker, side, status
            FROM broker_execution_records WHERE order_intent_id = ? ORDER BY submitted_at
            """,
            (intent["order_intent_id"],),
        )

    execution_events = []
    if intent and table_exists(conn, "broker_execution_events"):
        execution_events = selected_rows(
            conn,
            """
            SELECT broker_event_id, broker_execution_record_id, execution_packet_id,
                   execution_profile_id, status, occurred_at
            FROM broker_execution_events WHERE order_intent_id = ?
            ORDER BY occurred_at, rowid
            """,
            (intent["order_intent_id"],),
        )

    return {
        "record": record,
        "status_events": status_events,
        "final_status": statuses[-1] if statuses else "unavailable",
        "schema_result": schema_result,
        "policy_result": policy_result,
        "policy_reasons": policy_reasons,
        "trigger": trigger,
        "regime_evidence": regime_evidence,
        "intent": intent,
        "reasoning_run": reasoning_run,
        "packets": packets,
        "executions": executions,
        "execution_events": execution_events,
    }


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
               execution_packet_id, execution_profile_id, status, occurred_at,
               CASE WHEN detail != '' THEN 'yes' ELSE 'no' END AS detail_available
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
                "shared_bundle_path": run_json["shared_bundle_path"],
                "shared_bundle_sha256": run_json["shared_bundle_sha256"],
                "result": run_json["result"],
                "public_summary": run_json["public_summary"],
                # The legacy row's decision_ids is frozen by the first attempt; a retry
                # links its decisions only through reasoning_run_decisions.
                "decision_count": conn.execute(
                    "SELECT COUNT(*) FROM reasoning_run_decisions WHERE reasoning_run_id = ?",
                    (run_json["reasoning_run_id"],),
                ).fetchone()[0]
                if table_exists(conn, "reasoning_run_decisions")
                else len(run_json["decision_ids"]),
            }
        snapshot_row = conn.execute(
            """
            SELECT snapshot_json FROM live_portfolio_snapshots
            WHERE execution_profile_id = ?
              AND (? = '' OR portfolio_snapshot_id = ?)
            ORDER BY captured_at DESC LIMIT 1
            """,
            (
                profile_id,
                run["portfolio_snapshot_id"] if run else "",
                run["portfolio_snapshot_id"] if run else "",
            ),
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
            SELECT status, detail != '' FROM broker_execution_events
            WHERE execution_profile_id = ? ORDER BY julianday(occurred_at) DESC, rowid DESC LIMIT 1
            """,
            (profile_id,),
        ).fetchone()
        supported = profile["agent_provider"] == "CODEX"
        matching_intake = bool(
            shared
            and run
            and run["shared_bundle_path"] == shared["shared_bundle_path"]
            and run["shared_bundle_sha256"] == shared["shared_bundle_sha256"]
        )
        matching_snapshot = bool(
            run and snapshot and run["portfolio_snapshot_id"] == snapshot["portfolio_snapshot_id"]
        )
        reasoning_ready = bool(
            supported
            and profile["enabled"]
            and profile["account_bound"]
            and run
            and run["result"] == "PREPARED"
            and matching_intake
            and matching_snapshot
        )
        if not supported:
            reasoning_unavailable = "Claude is disabled future support."
        elif not profile["enabled"]:
            reasoning_unavailable = "Enable this profile after binding and snapshot setup."
        elif not profile["account_bound"]:
            reasoning_unavailable = "Bind the profile to its broker account first."
        elif shared is None:
            reasoning_unavailable = "Prepare the shared intake first."
        elif run is None:
            reasoning_unavailable = "Prepare a matching reasoning run for this profile."
        elif not matching_intake:
            reasoning_unavailable = "The reasoning run doesn't match the latest shared intake."
        elif run["result"] != "PREPARED":
            reasoning_unavailable = "The latest reasoning run is already complete."
        elif not matching_snapshot:
            reasoning_unavailable = "Save the snapshot assigned to this reasoning run."
        else:
            reasoning_unavailable = ""

        execution_ready = bool(
            supported and profile["enabled"] and profile["account_bound"] and pending_packets
        )
        if not supported:
            execution_unavailable = "Claude is disabled future support."
        elif not profile["enabled"]:
            execution_unavailable = "Enable this profile before execution handoff."
        elif not profile["account_bound"]:
            execution_unavailable = "Bind the profile to its broker account first."
        elif not pending_packets:
            execution_unavailable = "No unexpired, unexecuted packet is available."
        else:
            execution_unavailable = ""
        attempts = (
            selected_rows(
                conn,
                "SELECT a.attempt_id, a.status, a.stage, a.started_at, a.heartbeat_at, "
                "a.finished_at, a.reason, r.reasoning_run_id FROM runtime_attempts a "
                "JOIN runtime_runs r USING(run_id) "
                "WHERE r.execution_profile_id=? ORDER BY julianday(a.started_at) DESC LIMIT 20",
                (profile_id,),
            )
            if table_exists(conn, "runtime_attempts")
            else []
        )
        if attempts and run:
            wrapped = conn.execute(
                "SELECT 1 FROM runtime_runs WHERE reasoning_run_id=?", (run["reasoning_run_id"],)
            ).fetchone()
            if wrapped:
                reasoning_ready = False
                reasoning_unavailable = (
                    "This run belongs to the persisted runtime; inspect its named attempt."
                )
        profile_rows.append(
            {
                "execution_profile_id": profile_id,
                "agent_provider": profile["agent_provider"],
                "supported": supported,
                "enabled": profile["enabled"],
                "account_bound": profile["account_bound"],
                "snapshot": snapshot,
                "run": run,
                "runtime_attempts": attempts,
                # attempts is newest-first per profile; a profile can have several runs
                # in one session, so report the displayed run's own latest attempt.
                "runtime_status": next(
                    (
                        attempt["status"]
                        for attempt in attempts
                        if attempt["reasoning_run_id"] == run["reasoning_run_id"]
                    ),
                    None,
                )
                if run
                else (attempts[0]["status"] if attempts else None),
                "reasoning_ready": reasoning_ready,
                "reasoning_unavailable": reasoning_unavailable,
                "pending_packet_count": len(pending_packets),
                "execution_packet_id": pending_packets[0][0] if pending_packets else None,
                "execution_ready": execution_ready,
                "execution_unavailable": execution_unavailable,
                "execution_status": event_row[0] if event_row else None,
                "execution_error": (
                    "Broker lifecycle detail is withheld from the dashboard."
                    if event_row and event_row[1]
                    else ""
                ),
            }
        )
    return {"shared": shared, "profiles": profile_rows}


def execution_handoffs(
    packets: list[dict[str, Any]] | None,
    profiles: list[dict[str, object]] | None,
    *,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    current_time = now or datetime.now(UTC)
    profile_by_id = {str(profile["execution_profile_id"]): profile for profile in profiles or []}
    handoffs = []
    for packet in packets or []:
        profile = profile_by_id.get(str(packet["execution_profile_id"]))
        enabled = bool(profile and profile["enabled"])
        account_bound = bool(profile and profile["account_bound"])
        supported = bool(profile and profile["agent_provider"] == "CODEX")
        unexpired = datetime.fromisoformat(packet["expires_at"]) > current_time
        ready = enabled and account_bound and supported and unexpired and not packet["executed"]
        if profile is None:
            unavailable = "The packet's execution profile isn't configured."
        elif not supported:
            unavailable = "Claude is disabled future support."
        elif not enabled:
            unavailable = "The packet's execution profile is disabled."
        elif not account_bound:
            unavailable = "The packet's execution profile isn't bound to a broker account."
        elif packet["executed"]:
            unavailable = "This packet already has a persisted execution record."
        elif not unexpired:
            unavailable = "This packet has expired. Build a new packet from fresh preflight."
        else:
            unavailable = ""
        handoffs.append({**packet, "ready": ready, "unavailable": unavailable})
    return handoffs


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
