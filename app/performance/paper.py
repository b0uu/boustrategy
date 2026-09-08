"""Reconstruct the existing paper convention without changing its stored fills."""

import json
import sqlite3
from datetime import UTC, date, datetime, time
from decimal import Decimal
from zoneinfo import ZoneInfo

from app.dashboard.queries import table_exists
from app.paper.broker import STARTING_CASH
from app.schemas.reporting import (
    CoverageObservation,
    FillObservation,
    ReportingObservation,
    ReportingPosition,
    ValuationObservation,
)
from app.x.calendar import CalendarCoverageError, previous_session, session_close


def paper_observations(
    conn: sqlite3.Connection, *, observed_at: datetime | None = None
) -> tuple[list[ReportingObservation], str | None]:
    observed_at = observed_at or datetime.now(UTC)
    if not table_exists(conn, "paper_fills"):
        return [], None
    if conn.execute(
        "SELECT 1 FROM paper_fills f LEFT JOIN order_intents o USING(order_intent_id) WHERE "
        "o.order_intent_id IS NULL OR o.execution_mode!='PAPER' LIMIT 1"
    ).fetchone():
        return [], "paper_ledger_contains_unscoped_or_live_fills"
    fills = conn.execute(
        "SELECT f.fill_id, f.ticker, f.side, f.shares, f.price, f.fill_date, o.created_at, "
        "d.record_json "
        "FROM paper_fills f JOIN order_intents o USING(order_intent_id) "
        "JOIN decision_records d ON d.decision_id=o.decision_id WHERE o.execution_mode='PAPER' "
        "ORDER BY f.fill_date, f.filled_at, f.fill_id"
    ).fetchall()
    if not fills:
        return [], None
    inception = min(datetime.fromisoformat(row[6]) for row in fills)
    common = {"mode": "paper", "account_id": "paper"}
    initial = ValuationObservation(
        **common,
        observation_id="paper_inception",
        external_event_id="paper_inception",
        occurred_at=inception,
        recorded_at=inception,
        equity=Decimal(str(STARTING_CASH)),
        cash=Decimal(str(STARTING_CASH)),
        positions=[],
        complete=True,
    )
    observations: list[ReportingObservation] = [initial]
    prices = (
        {
            (ticker, day): Decimal(str(close))
            for ticker, day, close in conn.execute(
                "SELECT ticker, bar_date, close FROM daily_prices"
            )
        }
        if table_exists(conn, "daily_prices")
        else {}
    )
    tickers = {row[1] for row in fills}
    days = sorted(
        {day for ticker, day in prices if ticker in tickers and day >= fills[0][5]}
        | {row[5] for row in fills}
    )
    quantities: dict[str, Decimal] = {}
    costs: dict[str, Decimal] = {}
    themes: dict[str, str | None] = {}
    cash = Decimal(str(STARTING_CASH))
    fill_index = 0
    for day in days:
        session_date = date.fromisoformat(day)
        try:
            close_at = session_close(session_date)
            previous_day = previous_session(session_date)
        except CalendarCoverageError:
            return [], "paper_calendar_out_of_coverage"
        if close_at is None:
            return [], "paper_activity_on_non_session"
        if session_date > observed_at.astimezone(ZoneInfo("America/New_York")).date():
            continue
        completed = close_at <= observed_at
        while fill_index < len(fills) and fills[fill_index][5] <= day:
            fill_id, ticker, side, shares, price, fill_day, _, raw = fills[fill_index]
            quantity, fill_price = Decimal(str(shares)), Decimal(str(price))
            fill_at = datetime.combine(
                date.fromisoformat(fill_day), time(9, 30), ZoneInfo("America/New_York")
            ).astimezone(UTC)
            if fill_at > observed_at:
                return [], "paper_fill_not_yet_observable"
            observations.append(
                FillObservation(
                    **common,
                    observation_id=fill_id,
                    external_event_id=fill_id,
                    occurred_at=fill_at,
                    recorded_at=fill_at,
                    sequence=fill_index,
                    ticker=ticker,
                    side=side,
                    quantity=quantity,
                    price=fill_price,
                    gross_notional=(quantity * fill_price).quantize(Decimal("0.01")),
                    fee=Decimal(0),
                    origin="agent",
                    decision_id=json.loads(raw)["decision_id"],
                )
            )
            previous = quantities.get(ticker, Decimal(0))
            if side == "BUY":
                costs[ticker] = (
                    previous * costs.get(ticker, Decimal(0)) + quantity * fill_price
                ) / (previous + quantity)
                quantities[ticker] = previous + quantity
                cash -= quantity * fill_price
            else:
                quantities[ticker] = previous - quantity
                cash += quantity * fill_price
            if quantities[ticker] < Decimal("-0.000000001"):
                return [], "paper_position_activity_does_not_reconcile"
            if abs(quantities[ticker]) < Decimal("0.000000001"):
                quantities[ticker] = Decimal(0)
            themes[ticker] = json.loads(raw).get("primary_theme_id")
            fill_index += 1
        instant = close_at.astimezone(UTC) if completed else observed_at
        positions: list[ReportingPosition] = []
        for ticker, quantity in sorted(quantities.items()):
            if not quantity:
                continue
            close = prices.get((ticker, day)) if completed else None
            positions.append(
                ReportingPosition(
                    ticker=ticker,
                    quantity=quantity.quantize(Decimal("0.000000000000000001")),
                    average_cost=costs[ticker].quantize(Decimal("0.00000001")),
                    price=close,
                    market_value=(quantity * close).quantize(Decimal("0.01"))
                    if close is not None
                    else None,
                    price_quality="current" if close is not None else "missing",
                    quote_at=instant if close is not None else None,
                    theme=themes.get(ticker),
                )
            )
        complete = all(position.market_value is not None for position in positions)
        rounded_cash = cash.quantize(Decimal("0.01"))
        equity = (
            rounded_cash
            + sum(
                (
                    position.market_value
                    for position in positions
                    if position.market_value is not None
                ),
                Decimal(0),
            )
            if complete
            else None
        )
        observations.append(
            ValuationObservation(
                **common,
                observation_id=f"paper_close_{day}",
                external_event_id=f"paper_close_{day}",
                occurred_at=instant,
                recorded_at=instant,
                equity=equity,
                cash=rounded_cash,
                positions=positions,
                complete=complete,
                phase="session_close" if completed else "intraday",
                session_date=date.fromisoformat(day),
                previous_session_date=previous_day,
            )
        )
    expected = {ticker: float(quantity) for ticker, quantity in quantities.items() if quantity}
    persisted = dict(conn.execute("SELECT ticker, shares FROM paper_positions"))
    issue = (
        "paper_positions_do_not_reconcile"
        if expected.keys() != persisted.keys()
        or any(abs(expected[ticker] - persisted[ticker]) > 1e-9 for ticker in expected)
        else None
    )
    end = observations[-1].occurred_at
    if end > inception:
        observations.append(
            CoverageObservation(
                **common,
                observation_id="paper_coverage",
                external_event_id="paper_coverage",
                occurred_at=end,
                recorded_at=end,
                start_at=inception,
                end_at=end,
                external_flows_complete=True,
                activity_complete=True,
            )
        )
    return observations, issue
