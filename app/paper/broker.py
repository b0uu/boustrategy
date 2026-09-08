import math
import sqlite3
from datetime import UTC, date, datetime

from app.schemas.order_intent import OrderIntent
from app.storage.records import get_decision_record
from app.storage.runtime import immediate
from app.x.calendar import NEW_YORK

STARTING_CASH = 5_000.0


def validate_paper_ledger(conn: sqlite3.Connection) -> None:
    if conn.execute(
        "SELECT 1 FROM paper_fills f LEFT JOIN order_intents o USING(order_intent_id) "
        "WHERE o.order_intent_id IS NULL OR o.execution_mode != 'PAPER' "
        "OR o.execution_profile_id != '' OR f.ticker != o.ticker OR f.side != o.side LIMIT 1"
    ).fetchone():
        raise ValueError("paper_ledger_contains_unscoped_or_live_fills")


def cash_balance(conn: sqlite3.Connection, on_date: date | None = None) -> float:
    validate_paper_ledger(conn)
    query = "SELECT side, shares, price FROM paper_fills"
    parameters: tuple[str, ...] = ()
    if on_date is not None:
        query += " WHERE fill_date <= ?"
        parameters = (on_date.isoformat(),)
    cash = STARTING_CASH
    for side, shares, price in conn.execute(query, parameters):
        cash += shares * price * (-1 if side == "BUY" else 1)
    return cash


def _apply_fill(
    conn: sqlite3.Connection,
    intent: OrderIntent,
    shares: float,
    price: float,
    fill_date: date,
) -> None:
    position = conn.execute(
        """
        SELECT shares, avg_cost, opened_at, primary_theme_id
        FROM paper_positions WHERE ticker = ?
        """,
        (intent.ticker,),
    ).fetchone()
    existing_shares = float(position[0]) if position else 0.0
    if not math.isfinite(shares) or not math.isfinite(price) or shares <= 0 or price <= 0:
        raise ValueError("paper_fill_invalid_economics")
    if intent.side.value == "BUY":
        new_shares = existing_shares + shares
        avg_cost = (
            ((existing_shares * float(position[1])) + shares * price) / new_shares
            if position
            else price
        )
        decision = get_decision_record(conn, intent.decision_id)
        if decision is None:
            raise ValueError(f"missing decision {intent.decision_id}")
        theme = position[3] if position else decision.primary_theme_id or ""
        opened_at = position[2] if position else fill_date.isoformat()
        conn.execute(
            """
            INSERT OR REPLACE INTO paper_positions
                (ticker, shares, avg_cost, opened_at, primary_theme_id)
            VALUES (?, ?, ?, ?, ?)
            """,
            (intent.ticker, new_shares, avg_cost, opened_at, theme),
        )
    else:
        if shares > existing_shares + 1e-9:
            raise ValueError("paper_fill_exceeds_held_shares")
        new_shares = existing_shares - shares
        if new_shares < 1e-9:
            conn.execute("DELETE FROM paper_positions WHERE ticker = ?", (intent.ticker,))
        else:
            conn.execute(
                "UPDATE paper_positions SET shares = ? WHERE ticker = ?",
                (new_shares, intent.ticker),
            )


def _settle(conn: sqlite3.Connection, through_date: date | None = None) -> tuple[int, int]:
    validate_paper_ledger(conn)
    rows = conn.execute(
        """
        SELECT o.intent_json FROM order_intents o
        LEFT JOIN paper_fills f ON f.order_intent_id = o.order_intent_id
        WHERE f.fill_id IS NULL AND o.execution_mode = 'PAPER'
        """
    ).fetchall()
    candidates: list[tuple[date, OrderIntent, float]] = []
    awaiting = 0
    for (intent_json,) in rows:
        intent = OrderIntent.model_validate_json(intent_json)
        query = """
            SELECT bar_date, open FROM daily_prices
            WHERE ticker = ? AND bar_date > ?
        """
        # Fill on the first session after the New York day, not the UTC day already ahead at night.
        parameters = [
            intent.ticker,
            intent.created_at.astimezone(NEW_YORK).date().isoformat(),
        ]
        if through_date is not None:
            query += " AND bar_date <= ?"
            parameters.append(through_date.isoformat())
        query += " ORDER BY bar_date LIMIT 1"
        row = conn.execute(query, parameters).fetchone()
        if row is None:
            awaiting += 1
        else:
            candidates.append((date.fromisoformat(row[0]), intent, float(row[1])))
    candidates.sort(key=lambda item: (item[0], item[1].created_at, item[1].order_intent_id))
    settled = 0
    for fill_date, intent, open_price in candidates:
        latest_fill = conn.execute("SELECT MAX(fill_date) FROM paper_fills").fetchone()[0]
        if latest_fill and fill_date.isoformat() < latest_fill:
            raise ValueError("late paper intent requires explicit chronological replay")
        marks = conn.execute(
            "SELECT p.shares, d.open FROM paper_positions p LEFT JOIN daily_prices d "
            "ON d.ticker=p.ticker AND d.bar_date=?",
            (fill_date.isoformat(),),
        ).fetchall()
        if any(price is None for _, price in marks):
            awaiting += 1
            continue
        cash = cash_balance(conn, fill_date)
        if (
            not math.isfinite(open_price)
            or open_price <= 0
            or any(not math.isfinite(price) or price <= 0 for _, price in marks)
        ):
            raise ValueError("paper_open_invalid_economics")
        equity = cash + sum(shares * price for shares, price in marks)
        position = conn.execute(
            "SELECT shares FROM paper_positions WHERE ticker = ?", (intent.ticker,)
        ).fetchone()
        held_shares = float(position[0]) if position else 0.0
        current_value = held_shares * open_price
        delta_value = intent.target_weight * equity - current_value
        if intent.side.value == "BUY" and delta_value <= 0:
            raise ValueError(f"BUY intent {intent.order_intent_id} has non-positive delta")
        if intent.side.value == "SELL" and delta_value >= 0:
            raise ValueError(f"SELL intent {intent.order_intent_id} has non-negative delta")
        if intent.side.value == "BUY" and delta_value > cash:
            raise ValueError("paper_buy_insufficient_cash")
        shares = abs(delta_value) / open_price
        if intent.side.value == "SELL":
            shares = min(shares, held_shares)
        conn.execute(
            """
            INSERT INTO paper_fills
                (fill_id, order_intent_id, ticker, side, shares, price, fill_date, filled_at,
                 simulation_version)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"fill_{intent.order_intent_id}",
                intent.order_intent_id,
                intent.ticker,
                intent.side.value,
                shares,
                open_price,
                fill_date.isoformat(),
                datetime.now(UTC).isoformat(),
                "next_open_v2",
            ),
        )
        _apply_fill(conn, intent, shares, open_price, fill_date)
        settled += 1
    return settled, awaiting


def _rebuild_positions(conn: sqlite3.Connection) -> None:
    validate_paper_ledger(conn)
    fills = conn.execute(
        """
        SELECT f.order_intent_id, f.shares, f.price, f.fill_date
        FROM paper_fills f ORDER BY f.fill_date, f.filled_at, f.fill_id
        """
    ).fetchall()
    conn.execute("DELETE FROM paper_positions")
    for order_intent_id, shares, price, fill_date_text in fills:
        row = conn.execute(
            "SELECT intent_json FROM order_intents WHERE order_intent_id = ?",
            (order_intent_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"missing intent {order_intent_id}")
        _apply_fill(
            conn,
            OrderIntent.model_validate_json(row[0]),
            float(shares),
            float(price),
            date.fromisoformat(fill_date_text),
        )


def settle(conn: sqlite3.Connection, through_date: date | None = None) -> tuple[int, int]:
    with immediate(conn):
        return _settle(conn, through_date)


def rebuild_positions(conn: sqlite3.Connection) -> None:
    with immediate(conn):
        _rebuild_positions(conn)
