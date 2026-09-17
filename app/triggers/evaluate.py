import sqlite3
from datetime import date, timedelta

from app.prices.cache import get_daily_prices
from app.storage.short_watchlist import short_removal_status, short_watchlist_history
from app.triggers.store import expire_triggers, insert_trigger

PRICE_MOVE_THRESHOLD = 0.05
VOLUME_SPIKE_MULT = 3.0
CALENDAR_LOOKAHEAD_DAYS = 3
TRIGGER_TTL_DAYS = 5


def evaluate_triggers(
    conn: sqlite3.Connection, tickers: list[str], evaluation_date: date
) -> dict[str, int]:
    counts = {
        "price_move": 0,
        "price_move_skipped": 0,
        "volume_spike": 0,
        "volume_spike_skipped": 0,
        "calendar_upcoming": 0,
        "calendar_upcoming_skipped": 0,
        "digest_headline": 0,
        "digest_headline_skipped": 0,
    }
    for ticker in tickers:
        bars = get_daily_prices(conn, ticker, end=evaluation_date)
        price_fired = False
        volume_fired = False
        if bars and bars[-1].bar_date == evaluation_date:
            if len(bars) >= 2:
                previous = bars[-2]
                current = bars[-1]
                daily_return = current.close / previous.close - 1
                if abs(daily_return) >= PRICE_MOVE_THRESHOLD and insert_trigger(
                    conn,
                    "price_move",
                    ticker,
                    evaluation_date,
                    evaluation_date,
                    {
                        "return": daily_return,
                        "previous_close": previous.close,
                        "close": current.close,
                    },
                ):
                    counts["price_move"] += 1
                    price_fired = True
            if len(bars) >= 21:
                average = sum(bar.volume for bar in bars[-21:-1]) / 20
                current = bars[-1]
                multiple = current.volume / average if average > 0 else 0.0
                if multiple >= VOLUME_SPIKE_MULT and insert_trigger(
                    conn,
                    "volume_spike",
                    ticker,
                    evaluation_date,
                    evaluation_date,
                    {"volume": current.volume, "average": average, "multiple": multiple},
                ):
                    counts["volume_spike"] += 1
                    volume_fired = True
        if not price_fired:
            counts["price_move_skipped"] += 1
        if not volume_fired:
            counts["volume_spike_skipped"] += 1

    calendar_end = evaluation_date + timedelta(days=CALENDAR_LOOKAHEAD_DAYS)
    events = conn.execute(
        """
        SELECT event_type, ticker, event_date, label FROM calendar_events
        WHERE event_date > ? AND event_date <= ? ORDER BY event_date
        """,
        (evaluation_date.isoformat(), calendar_end.isoformat()),
    ).fetchall()
    for event_type, ticker, event_date_text, label in events:
        event_date = date.fromisoformat(event_date_text)
        subject = ticker or "FOMC"
        if insert_trigger(
            conn,
            "calendar_upcoming",
            subject,
            event_date,
            evaluation_date,
            {"event_type": event_type, "label": label},
        ):
            counts["calendar_upcoming"] += 1
        else:
            counts["calendar_upcoming_skipped"] += 1

    headlines = conn.execute(
        """
        SELECT r.post_id, r.reason, p.handle, p.url
        FROM x_route_decisions r JOIN x_posts p ON p.post_id = r.post_id
        WHERE r.rank = 'headline' AND substr(r.decided_at, 1, 10) = ?
        """,
        (evaluation_date.isoformat(),),
    ).fetchall()
    for post_id, reason, handle, url in headlines:
        if insert_trigger(
            conn,
            "digest_headline",
            post_id,
            evaluation_date,
            evaluation_date,
            {"reason": reason, "handle": handle, "url": url},
        ):
            counts["digest_headline"] += 1
        else:
            counts["digest_headline_skipped"] += 1

    # A short call the account cannot trade still has to be answered: when a close crosses one of
    # its removal conditions, or its backstop date arrives, the next review must deal with it.
    for mode in ("PAPER", "LIVE"):
        for call in short_watchlist_history(conn, mode):
            if call.removed_at is not None:
                continue
            bars = get_daily_prices(conn, call.ticker, end=evaluation_date)
            close = bars[-1].close if bars else None
            due = short_removal_status(call, close, evaluation_date)
            if due and insert_trigger(
                conn,
                "short_removal_due",
                call.ticker,
                evaluation_date,
                evaluation_date,
                {
                    "due": due,
                    "close": close,
                    "mode": mode,
                    "declared_by": call.declarations[-1].decision_id,
                },
            ):
                counts["short_removal_due"] = counts.get("short_removal_due", 0) + 1

    counts["expired"] = expire_triggers(conn, evaluation_date - timedelta(days=TRIGGER_TTL_DAYS))
    return counts
