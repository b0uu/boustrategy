import json
import sqlite3
from collections import Counter
from datetime import datetime

from app.dashboard.queries import equity_series, table_exists
from app.paper.broker import STARTING_CASH, cash_balance
from app.public.models import (
    PublicClaim,
    PublicDashboard,
    PublicDecision,
    PublicDecisionListItem,
    PublicOutcome,
    PublicPerformance,
    PublicPolicySummary,
    PublicPosition,
    PublicRegime,
    PublicTheme,
    PublicTrigger,
    PublicXUsage,
)
from app.schemas.decision_record import InvestmentDecisionRecord

_PUBLIC_LIFECYCLE = {
    "decision_recorded",
    "schema_validated",
    "schema_failed",
    "policy_approved",
    "policy_rejected",
    "order_intent_created",
    "paper_filled",
}
_PUBLIC_SOURCE_TYPES = {"SEC", "COMPANY_IR", "NEWS", "X", "PRICE_DATA", "MACRO", "ETF_ISSUER"}


def _outcomes(conn: sqlite3.Connection, decision_id: str) -> tuple[str, str, str]:
    if not table_exists(conn, "status_events"):
        return "unavailable", "unavailable", "unavailable"
    statuses = [
        row[0]
        for row in conn.execute(
            "SELECT status FROM status_events WHERE subject_type = 'decision' "
            "AND subject_id = ? ORDER BY event_id",
            (decision_id,),
        )
    ]
    schema = (
        "failed"
        if "schema_failed" in statuses
        else "passed"
        if "schema_validated" in statuses
        else "unavailable"
    )
    policy = (
        "rejected"
        if "policy_rejected" in statuses
        else "approved"
        if "policy_approved" in statuses
        else "unavailable"
    )
    lifecycle = next(
        (status for status in reversed(statuses) if status in _PUBLIC_LIFECYCLE), "unavailable"
    )
    return schema, policy, lifecycle


def _paper_lifecycle(conn: sqlite3.Connection, decision_id: str, fallback: str) -> str:
    if not table_exists(conn, "order_intents"):
        return fallback
    intent = conn.execute(
        "SELECT order_intent_id, execution_mode FROM order_intents WHERE decision_id = ?",
        (decision_id,),
    ).fetchone()
    if intent is None or intent[1] != "PAPER":
        return fallback
    if (
        table_exists(conn, "paper_fills")
        and conn.execute(
            "SELECT 1 FROM paper_fills WHERE order_intent_id = ?", (intent[0],)
        ).fetchone()
    ):
        return "paper_filled"
    return "awaiting_paper_price"


def _decision_item(
    conn: sqlite3.Connection, decision_id: str, raw: dict[str, object]
) -> PublicDecisionListItem:
    schema, policy, lifecycle = _outcomes(conn, decision_id)
    return PublicDecisionListItem(
        ticker=str(raw["ticker"]),
        created_at=str(raw["created_at"]),
        decision=str(raw["decision"]),
        public_summary=str(raw.get("public_summary") or ""),
        policy_outcome=policy,
        schema_outcome=schema,
        lifecycle=_paper_lifecycle(conn, decision_id, lifecycle),
        regime=str(raw.get("regime_state") or "unavailable"),
        theme=str(raw["primary_theme_id"]) if raw.get("primary_theme_id") else None,
    )


def dashboard(
    conn: sqlite3.Connection, *, include_decisions: bool = True, include_history: bool = True
) -> PublicDashboard:
    raw_decisions: list[tuple[str, dict[str, object]]] = []
    if include_decisions and table_exists(conn, "decision_records"):
        for decision_id, record_json in conn.execute(
            "SELECT decision_id, record_json FROM decision_records "
            "WHERE COALESCE(json_extract(record_json, '$.public_summary'), '') != '' "
            "ORDER BY created_at DESC, decision_id DESC LIMIT 100"
        ):
            raw = json.loads(record_json)
            if raw.get("public_summary"):
                raw_decisions.append((decision_id, raw))
    decisions = [_decision_item(conn, decision_id, raw) for decision_id, raw in raw_decisions]

    latest_summary: dict[str, str] = {}
    for item in decisions:
        latest_summary.setdefault(item.ticker, item.public_summary)
    positions: list[PublicPosition] = []
    has_paper_data = bool(
        table_exists(conn, "paper_positions")
        and conn.execute("SELECT 1 FROM paper_positions LIMIT 1").fetchone()
    ) or bool(
        table_exists(conn, "paper_fills")
        and conn.execute("SELECT 1 FROM paper_fills LIMIT 1").fetchone()
    )
    if has_paper_data and table_exists(conn, "order_intents"):
        contaminated = conn.execute(
            "SELECT 1 FROM paper_fills f LEFT JOIN order_intents o USING(order_intent_id) "
            "WHERE o.order_intent_id IS NULL OR o.execution_mode!='PAPER' LIMIT 1"
        ).fetchone()
        if contaminated:
            has_paper_data = False
    if has_paper_data:
        rows = conn.execute(
            "SELECT ticker, shares, avg_cost, primary_theme_id FROM paper_positions ORDER BY ticker"
        ).fetchall()
        valued: list[tuple[str, float, float, str, float | None]] = []
        for ticker, shares, average_cost, theme in rows:
            price_row = (
                conn.execute(
                    "SELECT close FROM daily_prices WHERE ticker = ? ORDER BY bar_date DESC "
                    "LIMIT 1",
                    (ticker,),
                ).fetchone()
                if table_exists(conn, "daily_prices")
                else None
            )
            price = float(price_row[0]) if price_row else None
            valued.append((str(ticker), float(shares), float(average_cost), str(theme), price))
        equity = (
            (
                cash_balance(conn)
                + sum(shares * price for _, shares, _, _, price in valued if price is not None)
            )
            if all(price is not None for _, _, _, _, price in valued)
            else None
        )
        for ticker, shares, average_cost, theme, price in valued:
            if include_decisions and table_exists(conn, "decision_records"):
                summary = conn.execute(
                    "SELECT json_extract(record_json, '$.public_summary') FROM decision_records "
                    "WHERE ticker=? AND "
                    "COALESCE(json_extract(record_json, '$.public_summary'), '') "
                    "!= '' ORDER BY created_at DESC, decision_id DESC LIMIT 1",
                    (ticker,),
                ).fetchone()
                if summary:
                    latest_summary[ticker] = summary[0]
            value = float(shares) * price if price is not None else None
            positions.append(
                PublicPosition(
                    ticker=str(ticker),
                    shares=float(shares),
                    average_cost=float(average_cost),
                    latest_price=price,
                    market_value=value,
                    weight=value / equity if value is not None and equity else None,
                    unrealized_return_percent=((price / float(average_cost)) - 1) * 100
                    if price is not None and average_cost
                    else None,
                    theme=str(theme) or None,
                    latest_public_summary=latest_summary.get(str(ticker)),
                )
            )
    else:
        equity = None
    series = (
        equity_series(conn)
        if include_history and equity is not None and table_exists(conn, "daily_prices")
        else None
    )
    performance = PublicPerformance(
        status="available" if equity is not None else "unavailable",
        equity=equity,
        return_percent=((equity / STARTING_CASH) - 1) * 100 if equity is not None else None,
        history=series or [],
    )
    outcomes: Counter[str] = Counter()
    if include_decisions and table_exists(conn, "decision_records"):
        if table_exists(conn, "status_events"):
            for policy, count in conn.execute(
                "WITH outcomes AS (SELECT subject_id, "
                "MAX(status='policy_rejected') AS rejected, "
                "MAX(status='policy_approved') AS approved "
                "FROM status_events WHERE subject_type='decision' GROUP BY subject_id) "
                "SELECT CASE WHEN rejected THEN 'rejected' WHEN approved THEN 'approved' "
                "ELSE 'unavailable' END AS policy, COUNT(*) FROM decision_records d "
                "LEFT JOIN outcomes o ON o.subject_id=d.decision_id "
                "WHERE COALESCE(json_extract(record_json, '$.public_summary'), '') != '' "
                "GROUP BY policy"
            ):
                outcomes[policy] = count
        else:
            outcomes["unavailable"] = conn.execute(
                "SELECT COUNT(*) FROM decision_records "
                "WHERE COALESCE(json_extract(record_json, '$.public_summary'), '') != ''"
            ).fetchone()[0]
    regime_row = None
    if table_exists(conn, "regime_snapshots"):
        regime_row = conn.execute(
            "SELECT snapshot_date, regime, score FROM regime_snapshots "
            "ORDER BY snapshot_date DESC LIMIT 1"
        ).fetchone()
    regime = (
        PublicRegime(
            status="available", as_of=regime_row[0], state=regime_row[1], score=regime_row[2]
        )
        if regime_row
        else PublicRegime(status="unavailable")
    )
    themes = Counter(position.theme for position in positions if position.theme)
    return PublicDashboard(
        performance=performance,
        positions=positions,
        decisions=decisions,
        policy=PublicPolicySummary(
            approved=outcomes["approved"],
            rejected=outcomes["rejected"],
            unavailable=outcomes["unavailable"],
        ),
        regime=regime,
        themes=[
            PublicTheme(name=name, position_count=count) for name, count in sorted(themes.items())
        ],
    )


def decision(conn: sqlite3.Connection, ticker: str, created_at: str) -> PublicDecision | None:
    if not table_exists(conn, "decision_records"):
        return None
    try:
        requested_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    matches = [
        item
        for item in conn.execute(
            "SELECT decision_id, record_json FROM decision_records WHERE ticker = ?", (ticker,)
        )
        if InvestmentDecisionRecord.model_validate_json(item[1]).created_at == requested_at
        and json.loads(item[1]).get("public_summary")
    ]
    row = matches[0] if len(matches) == 1 else None
    if row is None:
        return None
    decision_id, record_json = row
    record = InvestmentDecisionRecord.model_validate_json(record_json)
    if not record.public_summary:
        return None
    schema, policy, lifecycle = _outcomes(conn, decision_id)
    trigger = None
    if record.trigger_id and table_exists(conn, "trigger_events"):
        trigger_row = conn.execute(
            "SELECT trigger_type, subject, fired_at, status FROM trigger_events "
            "WHERE trigger_id = ?",
            (record.trigger_id,),
        ).fetchone()
        if trigger_row:
            trigger = PublicTrigger(
                trigger_type=trigger_row[0],
                subject=record.ticker,
                fired_at=trigger_row[2],
                status=trigger_row[3],
            )
    evidence = None
    return PublicDecision(
        ticker=record.ticker,
        created_at=record.created_at.isoformat(),
        decision=record.decision,
        public_summary=record.public_summary,
        initial_thesis="",
        counter_thesis="",
        adversarial_refinement="",
        refined_thesis="",
        what_is_priced_in="",
        invalidation_criteria=[],
        add_conditions=[],
        trim_conditions=[],
        exit_conditions=[],
        themes=record.theme_ids,
        strategy_beliefs=record.strategy_belief_ids,
        operating_mode=record.operating_mode,
        regime=record.regime_state,
        claims=[
            PublicClaim(
                claim=claim.claim,
                source_type=claim.source_type,
                source_timestamp=claim.source_timestamp.isoformat(),
            )
            for claim in record.source_claims
            if claim.public_safe and claim.source_type in _PUBLIC_SOURCE_TYPES
        ],
        trigger=trigger,
        regime_evidence=evidence,
        x_usage=PublicXUsage(
            used=record.x_signal_usage.used,
            usage_type=record.x_signal_usage.usage_type,
            summary="",
            confirmed_outside_x=record.x_signal_usage.confirmed_outside_x,
        ),
        outcome=PublicOutcome(
            schema_outcome=schema,
            policy=policy,
            policy_reasons=[],
            lifecycle=_paper_lifecycle(conn, decision_id, lifecycle),
        ),
    )
