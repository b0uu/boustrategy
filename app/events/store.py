import json
import re
import sqlite3
from collections import Counter
from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path

from app.events.fetch import fetch_earnings_dates, fomc_dates

_TICKER_PATTERN = re.compile(r"^[A-Z.]{1,12}$")


def parse_watchlist(path: str | Path) -> list[str]:
    tickers: list[str] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.startswith("-"):
            continue
        match = re.fullmatch(r"-\s+([^\s]+)\s+\N{EM DASH}\s+.+", line)
        if match is None or _TICKER_PATTERN.fullmatch(match.group(1)) is None:
            raise ValueError(f"malformed approved watchlist line: {line}")
        tickers.append(match.group(1))
    return tickers


def write_watchlist_suggestions(conn: sqlite3.Connection, path: str | Path) -> None:
    counts: Counter[str] = Counter()
    for (signal_json,) in conn.execute("SELECT signal_json FROM x_signals"):
        counts.update(json.loads(signal_json).get("tickers", []))
    lines = [
        "# Event watchlist",
        "",
        "Approved entries use `- TICKER \N{EM DASH} reason`; suggestions use `*` and are ignored.",
        "Only the maintainer may approve a suggestion by changing `*` to `-`.",
        "",
    ]
    for ticker, count in sorted(counts.items(), key=lambda item: (-item[1], item[0])):
        lines.append(f"* {ticker} \N{EM DASH} appeared in {count} captured signals")
    Path(path).write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def sync_fomc(conn: sqlite3.Connection, through: date) -> int:
    dates = fomc_dates(through)
    fetched_at = datetime.now(UTC).isoformat()
    conn.execute("DELETE FROM calendar_events WHERE event_type = 'fomc'")
    for index, meeting_date in enumerate(dates):
        day = index % 2 + 1
        conn.execute(
            """
            INSERT INTO calendar_events
                (event_type, ticker, event_date, label, source, fetched_at)
            VALUES ('fomc', '', ?, ?, 'federalreserve.gov', ?)
            """,
            (meeting_date.isoformat(), f"FOMC meeting day {day}", fetched_at),
        )
    conn.commit()
    return len(dates)


def refresh_earnings(
    conn: sqlite3.Connection,
    ticker: str,
    fetcher: Callable[[str], list[date]] = fetch_earnings_dates,
    today: date | None = None,
) -> int:
    today = today or date.today()
    dates = fetcher(ticker)
    fetched_at = datetime.now(UTC).isoformat()
    conn.execute(
        """
        DELETE FROM calendar_events
        WHERE event_type = 'earnings' AND ticker = ? AND event_date >= ?
        """,
        (ticker, today.isoformat()),
    )
    for event_date in dates:
        if event_date >= today:
            conn.execute(
                """
                INSERT INTO calendar_events
                    (event_type, ticker, event_date, label, source, fetched_at)
                VALUES ('earnings', ?, ?, 'estimated', 'yfinance', ?)
                """,
                (ticker, event_date.isoformat(), fetched_at),
            )
    conn.commit()
    return sum(event_date >= today for event_date in dates)


def upcoming_events(
    conn: sqlite3.Connection, start: date, days: int
) -> list[tuple[str, str, str, str]]:
    end = date.fromordinal(start.toordinal() + days)
    return conn.execute(
        """
        SELECT event_date, event_type, ticker, label FROM calendar_events
        WHERE event_date >= ? AND event_date < ? ORDER BY event_date, event_type, ticker
        """,
        (start.isoformat(), end.isoformat()),
    ).fetchall()
