"""Build public accounting snapshots during trusted publication."""

import calendar
import hashlib
import sqlite3
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from app.dashboard.queries import table_exists
from app.performance.calculate import (
    METHODOLOGY,
    covered,
    daily_pnl,
    linked_return,
    session_timestamp_reason,
)
from app.schemas.reporting import (
    CorporateActionObservation,
    CoverageObservation,
    FillObservation,
    FlowObservation,
    ReportingObservation,
    ValuationObservation,
)


def holding_episodes(
    values: list[ValuationObservation],
    observations: list[ReportingObservation],
    coverage: list[CoverageObservation],
    *,
    limit: int | None = 100,
) -> dict[str, Any]:
    baseline, latest = values[0], values[-1]
    if baseline.positions is None or any(p.quantity is None for p in baseline.positions):
        return {"status": "unavailable", "reason": "opening_quantities_missing", "items": []}
    if not covered(baseline.occurred_at, latest.occurred_at, coverage, activity=True):
        return {"status": "unavailable", "reason": "activity_coverage_missing", "items": []}
    items: list[dict[str, Any]] = []
    current: dict[str, dict[str, Any]] = {}
    quantities: dict[str, Decimal] = {}
    for position in baseline.positions:
        if not position.quantity:
            continue
        episode = {
            "episode_id": "holding_"
            + hashlib.sha256(
                f"{baseline.account_id}/{baseline.external_event_id}/{position.ticker}".encode()
            ).hexdigest()[:24],
            "ticker": position.ticker,
            "opened_at": None,
            "first_observed_at": baseline.occurred_at.isoformat(),
            "closed_at": None,
            "status": "open",
            "quantity": str(position.quantity),
        }
        current[position.ticker] = episode
        quantities[position.ticker] = position.quantity
        items.append(episode)
    events = [
        o
        for o in observations
        if isinstance(o, FillObservation | CorporateActionObservation)
        and baseline.occurred_at < o.occurred_at <= latest.occurred_at
    ]
    event_keys = [
        (o.occurred_at, o.ticker, o.sequence)
        for o in events
        if isinstance(o, FillObservation) or o.action in {"split", "transfer_in", "transfer_out"}
    ]
    if len(event_keys) != len(set(event_keys)):
        return {"status": "unavailable", "reason": "activity_order_unknown", "items": []}
    for event in sorted(events, key=lambda o: (o.occurred_at, o.sequence, o.observation_id)):
        if isinstance(event, CorporateActionObservation) and event.action in {"fee", "dividend"}:
            continue
        ticker = event.ticker
        assert ticker is not None
        previous = quantities.get(ticker, Decimal(0))
        if isinstance(event, FillObservation):
            quantity = previous + event.quantity * (1 if event.side == "BUY" else -1)
        elif event.action == "split":
            assert event.split_ratio is not None
            quantity = previous * event.split_ratio
        else:
            assert event.quantity is not None
            quantity = previous + event.quantity * (1 if event.action == "transfer_in" else -1)
        if quantity < 0:
            return {
                "status": "unavailable",
                "reason": "position_activity_does_not_reconcile",
                "items": [],
            }
        if previous == 0 and quantity > 0:
            episode = {
                "episode_id": "holding_"
                + hashlib.sha256(
                    f"{event.account_id}/{event.external_event_id}/{ticker}".encode()
                ).hexdigest()[:24],
                "ticker": ticker,
                "opened_at": event.occurred_at.isoformat(),
                "first_observed_at": event.occurred_at.isoformat(),
                "closed_at": None,
                "status": "open",
                "quantity": str(quantity),
            }
            current[ticker] = episode
            items.append(episode)
        if ticker in current:
            current[ticker]["quantity"] = str(quantity)
            if quantity == 0:
                current[ticker]["closed_at"] = event.occurred_at.isoformat()
                current[ticker]["status"] = "closed"
                del current[ticker]
        quantities[ticker] = quantity
    if latest.positions is not None and all(p.quantity is not None for p in latest.positions):
        actual = {p.ticker: p.quantity for p in latest.positions if p.quantity}
        if actual != {ticker: quantity for ticker, quantity in quantities.items() if quantity}:
            return {
                "status": "unavailable",
                "reason": "position_activity_does_not_reconcile",
                "items": [],
            }
    return {
        "status": "available",
        "reason": None,
        "history_starts_at": baseline.occurred_at.isoformat(),
        "items": items[-limit:] if limit is not None else items,
        "total": len(items),
        "truncated": limit is not None and len(items) > limit,
    }


def materialize(
    conn: sqlite3.Connection, observations: list[ReportingObservation]
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    values = sorted(
        (
            o
            for o in observations
            if isinstance(o, ValuationObservation) and o.phase not in {"before_flow", "after_flow"}
        ),
        key=lambda value: (value.occurred_at, value.observation_id),
    )
    if not values:
        return {}, {}
    if len({value.occurred_at for value in values}) != len(values):
        raise ValueError("ambiguous ordinary valuation instants")
    latest = values[-1]
    if any(
        (item.mode, item.account_id) != (latest.mode, latest.account_id) for item in observations
    ):
        raise ValueError("reporting observations must share one account")
    names: dict[str, str] = {}
    for value in values:
        for position in value.positions or []:
            if position.name is not None:
                names[position.ticker] = position.name
    all_values = {
        o.observation_id: o
        for o in observations
        if isinstance(o, ValuationObservation) and o.phase in {"before_flow", "after_flow"}
    }
    flows = [o for o in observations if isinstance(o, FlowObservation)]
    coverage = [o for o in observations if isinstance(o, CoverageObservation)]
    positions: list[dict[str, Any]] = []
    for position in latest.positions or []:
        positions.append(
            {
                "ticker": position.ticker,
                "name": names.get(position.ticker),
                "shares": str(position.quantity) if position.quantity is not None else None,
                "market_value": str(position.market_value)
                if position.market_value is not None
                else None,
                "average_cost": str(position.average_cost)
                if position.average_cost is not None
                else None,
                "latest_price": str(position.price) if position.price is not None else None,
                "weight": float(position.market_value / latest.equity)
                if position.market_value is not None and latest.equity
                else None,
                "unrealized_return_percent": float(
                    (position.price / position.average_cost - 1) * 100
                )
                if position.price is not None and position.average_cost
                else None,
                "theme": position.theme,
                "asset_class": position.asset_class,
                "price_quality": position.price_quality,
                "quote_at": position.quote_at.isoformat() if position.quote_at else None,
                "latest_public_summary": None,
                "latest_decision_id": None,
            }
        )
    complete = [value for value in values if value.complete]
    episodes = holding_episodes(values, observations, coverage)
    state = (
        "unavailable_holdings"
        if latest.positions is None
        else "zero_balance"
        if latest.complete and latest.equity == 0 and any(value.equity for value in values[:-1])
        else "unfunded"
        if latest.complete and latest.equity == 0
        else "sold_out"
        if latest.complete
        and not latest.positions
        and any(item["status"] == "closed" for item in episodes["items"])
        else "all_cash"
        if latest.complete and not latest.positions and latest.cash == latest.equity
        else "partial"
        if not latest.complete
        else "invested"
    )
    allocation: dict[str, Decimal] = {}
    if latest.complete:
        assert latest.cash is not None
        allocation["cash"] = latest.cash
        allocation["receivables"] = latest.receivables
        allocation["liabilities"] = -latest.liabilities
        for position in latest.positions or []:
            assert position.market_value is not None
            allocation[position.asset_class] = (
                allocation.get(position.asset_class, Decimal(0)) + position.market_value
            )
    result: dict[str, Any] = {
        "status": "available" if latest.complete else "partial",
        "reason": None if latest.complete else "incomplete_reporting_balance",
        "data_as_of": latest.occurred_at.isoformat(),
        "currency": "USD",
        "equity": str(latest.equity) if latest.equity is not None else None,
        "cash": str(latest.cash) if latest.cash is not None else None,
        "positions": positions,
        "holdings_status": "available" if latest.positions is not None else "unavailable",
        "portfolio_state": state,
        "last_complete_valuation": {
            "at": complete[-1].occurred_at.isoformat(),
            "equity": str(complete[-1].equity),
        }
        if complete
        else None,
        "allocation": [
            {
                "asset_class": name,
                "market_value": str(amount),
                "weight": float(amount / latest.equity) if latest.equity else None,
            }
            for name, amount in allocation.items()
            if amount
        ],
        "observed_since": values[0].occurred_at.isoformat(),
        "daily_pnl": daily_pnl(latest, values, flows, coverage),
        "holding_episodes": episodes,
        "methodology": METHODOLOGY,
        "capabilities": {
            "returns": False,
            "cash": latest.cash is not None,
            "quantities": latest.positions is not None
            and all(p.quantity is not None for p in latest.positions),
        },
    }
    fills = [o for o in observations if isinstance(o, FillObservation)]
    result["recent_fills"] = [
        {
            "fill_id": "fill_"
            + hashlib.sha256(f"{fill.account_id}/{fill.external_event_id}".encode()).hexdigest()[
                :24
            ],
            "ticker": fill.ticker,
            "side": fill.side,
            "quantity": str(fill.quantity),
            "price": str(fill.price),
            "gross_notional": str(fill.gross_notional),
            "fee": str(fill.fee) if fill.fee is not None else None,
            "origin": fill.origin,
            "occurred_at": fill.occurred_at.isoformat(),
            "order_state": fill.order_state,
            "canceled_quantity": str(fill.canceled_quantity),
            "settled_at": fill.settled_at.isoformat() if fill.settled_at else None,
        }
        for fill in sorted(
            fills, key=lambda fill: (fill.occurred_at, fill.observation_id), reverse=True
        )[:100]
    ]
    ranges: dict[str, dict[str, Any]] = {}
    local_end = latest.occurred_at.astimezone(ZoneInfo("America/New_York"))
    for name in ("1M", "3M", "YTD", "All"):
        if name == "All":
            cutoff = values[0].occurred_at
        elif name == "YTD":
            cutoff = local_end.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        else:
            months = 1 if name == "1M" else 3
            month_number = local_end.year * 12 + local_end.month - 1 - months
            year, month = divmod(month_number, 12)
            cutoff = local_end.replace(
                year=year,
                month=month + 1,
                day=min(local_end.day, calendar.monthrange(year, month + 1)[1]),
                hour=0,
                minute=0,
                second=0,
                microsecond=0,
            )
        eligible = [value for value in values if value.occurred_at >= cutoff]
        start = eligible[0] if eligible else latest
        computed = linked_return(start, latest, all_values, flows, coverage)
        history: list[dict[str, Any]] = []
        peak = Decimal(1)
        drawdown = Decimal(0)
        for value in eligible:
            if value.phase != "session_close" and value not in (start, latest):
                continue
            metric = (
                linked_return(start, value, all_values, flows, coverage)
                if value != start
                else {
                    "status": "available" if start.complete and start.equity else "unavailable",
                    "return_percent": "0",
                    "growth_factor": "1",
                }
            )
            factor = Decimal(metric["growth_factor"]) if metric["status"] == "available" else None
            if factor is not None:
                peak = max(peak, factor)
                drawdown = min(drawdown, factor / peak - 1)
            history.append(
                {
                    "at": value.occurred_at.isoformat(),
                    "session_date": value.session_date.isoformat() if value.session_date else None,
                    "equity": str(value.equity) if value.equity is not None else None,
                    "return_percent": metric.get("return_percent")
                    if metric["status"] == "available"
                    else None,
                    "quality": "complete" if value.complete else "partial",
                    "gap_reason": metric.get("reason"),
                    "phase": value.phase,
                }
            )
        total_points = len(history)
        chart_reason = None
        if total_points > 400:
            selected = {0, total_points - 1}
            previous_gap = (
                history[0]["return_percent"] is None or history[0]["quality"] != "complete"
            )
            for index, point in enumerate(history[1:], 1):
                gap = point["return_percent"] is None or point["quality"] != "complete"
                if gap != previous_gap:
                    selected.update((index - 1, index))
                previous_gap = gap
            if len(selected) > 400:
                history = []
                chart_reason = "too_many_quality_gaps"
            else:
                for index in range(400):
                    if len(selected) >= 400:
                        break
                    selected.add(round(index * (total_points - 1) / 399))
                history = [history[index] for index in sorted(selected)]
        benchmarks: list[dict[str, Any]] = []
        for ticker in ("QQQ", "SPY", "SMH"):
            benchmark: dict[str, Any] = {
                "ticker": ticker,
                "primary": ticker == "QQQ",
                "status": "unavailable",
                "reason": "matching_session_closes_required",
                "return_percent": None,
                "convention": "adjusted_close",
            }
            if (
                start.phase == latest.phase == "session_close"
                and start.session_date
                and latest.session_date
                and start.session_date != latest.session_date
                and session_timestamp_reason(start) is None
                and session_timestamp_reason(latest) is None
                and table_exists(conn, "daily_prices")
            ):
                prices = dict(
                    conn.execute(
                        "SELECT bar_date, adj_close FROM daily_prices WHERE ticker=? AND "
                        "bar_date IN (?, ?)",
                        (ticker, start.session_date.isoformat(), latest.session_date.isoformat()),
                    )
                )
                first, last = (
                    prices.get(start.session_date.isoformat()),
                    prices.get(latest.session_date.isoformat()),
                )
                if first is not None and last is not None and first > 0 and last > 0:
                    benchmark.update(
                        status="available",
                        reason=None,
                        return_percent=str(
                            ((Decimal(str(last)) / Decimal(str(first)) - 1) * 100).quantize(
                                Decimal("0.000001")
                            )
                        ),
                    )
                else:
                    benchmark["reason"] = "matching_adjusted_prices_missing"
            if latest.mode == "paper":
                benchmark.update(
                    status="unavailable",
                    reason="paper_corporate_action_convention_mismatch",
                    return_percent=None,
                )
            benchmarks.append(benchmark)
        ranges[name] = {
            "range": name,
            "requested_start_at": cutoff.isoformat(),
            "range_is_partial": start.occurred_at > cutoff,
            "period_label": f"Since {start.occurred_at.date().isoformat()}",
            **computed,
            "start_at": start.occurred_at.isoformat(),
            "end_at": latest.occurred_at.isoformat(),
            "history": history,
            "observed_drawdown_percent": str((drawdown * 100).quantize(Decimal("0.000001")))
            if computed["status"] == "available"
            else None,
            "chart_sampling": {
                "status": "unavailable" if chart_reason else "available",
                "reason": chart_reason,
                "method": "gap_preserving_observation_indices"
                if total_points > 400
                else "all_observed_session_closes",
                "source_points": total_points,
                "limit": 400,
            },
            "benchmarks": benchmarks,
            "methodology": METHODOLOGY,
        }
        ranges[name].pop("growth_factor", None)
    result["return_percent"] = ranges["All"]["return_percent"]
    result["capabilities"]["returns"] = ranges["All"]["status"] == "available"
    result["history"] = []
    return result, ranges
