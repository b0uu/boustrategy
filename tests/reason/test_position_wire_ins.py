import sys
from pathlib import Path

import pytest

from app.events import run as events_run
from app.storage.database import connect
from app.triggers import run as triggers_run


def test_events_refresh_unions_watchlist_and_position_tickers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn = connect(tmp_path / "events.db")
    refreshed: list[str] = []

    def refresh_earnings(conn: object, ticker: str) -> int:
        refreshed.append(ticker)
        return 0

    monkeypatch.setattr(events_run, "connect", lambda path: conn)
    monkeypatch.setattr(events_run, "parse_watchlist", lambda path: ["WATCH"])
    monkeypatch.setattr(events_run, "position_tickers", lambda conn: ["HELD", "WATCH"])
    monkeypatch.setattr(events_run, "refresh_earnings", refresh_earnings)
    monkeypatch.setattr(events_run, "sync_fomc", lambda conn, through: 0)
    monkeypatch.setattr(sys, "argv", ["app.events.run", "refresh"])

    events_run.main()

    assert refreshed == ["HELD", "WATCH"]


def test_trigger_evaluation_unions_watchlist_and_position_tickers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn = connect(tmp_path / "triggers.db")
    refreshed: list[str] = []
    evaluated: list[str] = []

    def evaluate_triggers(conn: object, tickers: list[str], on_date: object) -> dict[str, int]:
        evaluated.extend(tickers)
        return {"fired": 0}

    monkeypatch.setattr(triggers_run, "connect", lambda path: conn)
    monkeypatch.setattr(triggers_run, "parse_watchlist", lambda path: ["WATCH"])
    monkeypatch.setattr(triggers_run, "position_tickers", lambda conn: ["HELD", "WATCH"])
    monkeypatch.setattr(
        triggers_run,
        "refresh_ticker",
        lambda conn, ticker, start, end: refreshed.append(ticker),
    )
    monkeypatch.setattr(
        triggers_run,
        "evaluate_triggers",
        evaluate_triggers,
    )
    monkeypatch.setattr(sys, "argv", ["app.triggers.run", "evaluate", "--date", "2026-06-10"])

    triggers_run.main()

    assert refreshed == ["HELD", "WATCH"]
    assert evaluated == ["HELD", "WATCH"]
