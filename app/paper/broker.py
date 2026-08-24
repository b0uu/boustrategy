import sqlite3
from datetime import UTC, date, datetime

from app.schemas.order_intent import OrderIntent
from app.storage.records import get_decision_record

STARTING_CASH = 5_000.0


def cash_balance(conn: sqlite3.Connection, on_date: date | None = None) -> float:
    query = "SELECT side, shares, price FROM paper_fills"
    parameters: tuple[str, ...] = ()
    if on_date is not None:
        query += " WHERE fill_date <= ?"
        parameters = (on_date.isoformat(),)
    cash = STARTING_CASH
    for side, shares, price in conn.execute(query, parameters):
        cash += shares * price * (-1 if side == "BUY" else 1)
    return cash


def _close_on(conn: sqlite3.Connection, ticker: str, on_date: date) -> float:
    row = conn.execute(
        "SELECT close FROM daily_prices WHERE ticker = ? AND bar_date = ?",
        (ticker, on_date.isoformat()),
    ).fetchone()
    if row is None:
        raise ValueError(f"missing {ticker} close for {on_date}; refresh prices first")
    return float(row[0])


def equity_on(conn: sqlite3.Connection, on_date: date) -> float:
    equity = cash_balance(conn, on_date)
    for ticker, shares in conn.execute("SELECT ticker, shares FROM paper_positions"):
        equity += shares * _close_on(conn, ticker, on_date)
    return equity


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
        new_shares = existing_shares - shares
        if new_shares < 1e-9:
            conn.execute("DELETE FROM paper_positions WHERE ticker = ?", (intent.ticker,))
        else:
            conn.execute(
                "UPDATE paper_positions SET shares = ? WHERE ticker = ?",
                (new_shares, intent.ticker),
            )


def settle(conn: sqlite3.Connection) -> tuple[int, int]:
    rows = conn.execute(
        """
        SELECT o.intent_json FROM order_intents o
        LEFT JOIN paper_fills f ON f.order_intent_id = o.order_intent_id
        WHERE f.fill_id IS NULL
        """
    ).fetchall()
    candidates: list[tuple[date, OrderIntent, float]] = []
    awaiting = 0
    for (intent_json,) in rows:
        intent = OrderIntent.model_validate_json(intent_json)
        row = conn.execute(
            """
            SELECT bar_date, open FROM daily_prices
            WHERE ticker = ? AND bar_date > ? ORDER BY bar_date LIMIT 1
            """,
            (intent.ticker, intent.created_at.date().isoformat()),
        ).fetchone()
        if row is None:
            awaiting += 1
        else:
            candidates.append((date.fromisoformat(row[0]), intent, float(row[1])))
    candidates.sort(key=lambda item: (item[0], item[1].created_at, item[1].order_intent_id))
    for fill_date, intent, open_price in candidates:
        equity = equity_on(conn, fill_date)
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
        shares = abs(delta_value) / open_price
        if intent.side.value == "SELL":
            shares = min(shares, held_shares)
        conn.execute(
            """
            INSERT INTO paper_fills
                (fill_id, order_intent_id, ticker, side, shares, price, fill_date, filled_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
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
            ),
        )
        _apply_fill(conn, intent, shares, open_price, fill_date)
        conn.commit()
    return len(candidates), awaiting


def rebuild_positions(conn: sqlite3.Connection) -> None:
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
    conn.commit()
