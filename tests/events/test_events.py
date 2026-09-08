import json
from datetime import date
from pathlib import Path

import pytest

from app.events.fetch import FomcCoverageError
from app.events.store import (
    parse_watchlist,
    refresh_earnings,
    sync_fomc,
    upcoming_events,
    write_watchlist_suggestions,
)
from app.storage.database import connect


def test_watchlist_ignores_suggestions_and_reads_approved(tmp_path: Path) -> None:
    path = tmp_path / "watchlist.md"
    path.write_text("* AMD \N{EM DASH} suggested\n- NVDA \N{EM DASH} approved\n", encoding="utf-8")

    assert parse_watchlist(path) == ["NVDA"]


def test_watchlist_rejects_malformed_approved_line(tmp_path: Path) -> None:
    path = tmp_path / "watchlist.md"
    path.write_text("- nvda \N{EM DASH} lowercase is invalid\n", encoding="utf-8")

    with pytest.raises(ValueError, match="malformed approved"):
        parse_watchlist(path)


def test_watchlist_suggestions_count_synthetic_signals(tmp_path: Path) -> None:
    conn = connect(tmp_path / "synthetic.db")
    for entry_id, tickers in (("1", ["NVDA", "AMD"]), ("2", ["NVDA"])):
        conn.execute(
            """
            INSERT INTO x_signals (entry_id, post_id, handle, signal_json, captured_at)
            VALUES (?, ?, 'source', ?, '2026-07-01T00:00:00+00:00')
            """,
            (entry_id, entry_id, json.dumps({"tickers": tickers})),
        )
    path = tmp_path / "watchlist.md"

    write_watchlist_suggestions(conn, path)

    lines = path.read_text(encoding="utf-8").splitlines()
    assert "* NVDA \N{EM DASH} appeared in 2 captured signals" in lines
    assert lines.index("* NVDA \N{EM DASH} appeared in 2 captured signals") < lines.index(
        "* AMD \N{EM DASH} appeared in 1 captured signals"
    )


def test_fomc_sync_replaces_wholesale_and_checks_coverage(tmp_path: Path) -> None:
    conn = connect(tmp_path / "synthetic.db")
    conn.execute(
        """
        INSERT INTO calendar_events
            (event_type, ticker, event_date, label, source, fetched_at)
        VALUES ('fomc', '', '2026-01-01', 'stale', 'old', '2026-01-01')
        """
    )

    count = sync_fomc(conn, date(2026, 12, 31))

    assert count == 16
    assert (
        conn.execute("SELECT COUNT(*) FROM calendar_events WHERE event_type = 'fomc'").fetchone()[0]
        == 16
    )
    assert (
        conn.execute(
            "SELECT label FROM calendar_events WHERE event_date = '2026-07-29'"
        ).fetchone()[0]
        == "FOMC meeting day 2"
    )
    with pytest.raises(FomcCoverageError):
        sync_fomc(conn, date(2028, 1, 1))


def test_earnings_refresh_replaces_future_only(tmp_path: Path) -> None:
    conn = connect(tmp_path / "synthetic.db")
    conn.executemany(
        """
        INSERT INTO calendar_events
            (event_type, ticker, event_date, label, source, fetched_at)
        VALUES ('earnings', 'NVDA', ?, 'old', 'old', '2026-01-01')
        """,
        [("2026-07-01",), ("2026-08-01",)],
    )

    count = refresh_earnings(
        conn,
        "NVDA",
        fetcher=lambda _: [date(2026, 8, 20)],
        today=date(2026, 7, 18),
    )

    assert count == 1
    assert conn.execute(
        "SELECT event_date FROM calendar_events WHERE ticker = 'NVDA' ORDER BY event_date"
    ).fetchall() == [("2026-07-01",), ("2026-08-20",)]


def test_upcoming_uses_half_open_day_window(tmp_path: Path) -> None:
    conn = connect(tmp_path / "synthetic.db")
    conn.executemany(
        """
        INSERT INTO calendar_events
            (event_type, ticker, event_date, label, source, fetched_at)
        VALUES ('earnings', 'NVDA', ?, 'estimated', 'test', '2026-01-01')
        """,
        [("2026-07-20",), ("2026-07-26",), ("2026-07-27",)],
    )

    rows = upcoming_events(conn, date(2026, 7, 20), 7)

    assert [row[0] for row in rows] == ["2026-07-20", "2026-07-26"]


def test_fomc_2027_is_explicit_tentative_and_does_not_imply_2028(tmp_path: Path) -> None:
    conn = connect(tmp_path / "source.db")
    assert sync_fomc(conn, date(2027, 12, 31)) == 32
    assert (
        "tentative"
        in conn.execute(
            "SELECT label FROM calendar_events WHERE event_date='2027-12-08'"
        ).fetchone()[0]
    )
    assert not conn.execute(
        "SELECT 1 FROM calendar_events WHERE event_date>='2028-01-01'"
    ).fetchone()
    conn.close()


def test_suggestion_refresh_preserves_approved_entries_and_notes(tmp_path: Path) -> None:
    conn = connect(":memory:")
    path = tmp_path / "watchlist.md"
    original = "# Watchlist\n- NVDA \N{EM DASH} approved reason\n\nMaintainer note\n"
    path.write_text(original, encoding="utf-8")
    write_watchlist_suggestions(conn, path)
    assert path.read_text(encoding="utf-8") == original
    assert parse_watchlist(path) == ["NVDA"]
    conn.close()
