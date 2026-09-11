import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from app.broker import valuation
from app.broker.valuation import exclusive, failure_reason, run, run_collector, session_window

NEW_YORK = ZoneInfo("America/New_York")
FINGERPRINT = "f00dfeedcafe4321"


def at(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=NEW_YORK)


@pytest.mark.parametrize(
    ("moment", "is_open", "reason"),
    [
        (at("2026-09-12T11:00"), False, "weekend"),
        (at("2026-09-13T11:00"), False, "weekend"),
        (at("2026-11-26T11:00"), False, "holiday"),
        (at("2026-09-14T09:29:59"), False, "pre_open"),
        (at("2026-09-14T09:30:00"), True, "regular_session"),
        (at("2026-09-14T12:15"), True, "regular_session"),
        (at("2026-09-14T15:59:59"), True, "regular_session"),
        (at("2026-09-14T16:00"), False, "after_close"),
        (at("2026-09-14T18:30"), False, "after_close"),
        (at("2026-11-27T12:59:59"), True, "regular_session"),
        (at("2026-11-27T13:00"), False, "after_close"),
        (at("2029-01-02T11:00"), False, "calendar_out_of_coverage"),
    ],
)
def test_session_window_follows_the_nyse_calendar(
    moment: datetime, is_open: bool, reason: str
) -> None:
    window = session_window(moment)

    assert (window.open, window.reason) == (is_open, reason)
    assert window.session_date == (moment.date().isoformat() if is_open else None)


def test_session_window_holds_across_daylight_saving_changes() -> None:
    # Standard time from 2026-11-01: 09:30 New York is 14:30 UTC, not 13:30.
    assert not session_window(datetime(2026, 11, 2, 14, 29, tzinfo=UTC)).open
    assert session_window(datetime(2026, 11, 2, 14, 30, tzinfo=UTC)).open
    assert not session_window(datetime(2026, 11, 2, 21, 0, tzinfo=UTC)).open
    # Daylight time from 2026-03-08: 09:30 New York is 13:30 UTC.
    assert session_window(datetime(2026, 3, 9, 13, 30, tzinfo=UTC)).open
    assert not session_window(datetime(2026, 3, 9, 20, 0, tzinfo=UTC)).open
    with pytest.raises(ValueError):
        session_window(datetime(2026, 9, 14, 12, 0))


class Collector:
    def __init__(self, *outcomes: tuple[int | None, str, str]) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[tuple[list[str], float]] = []

    def __call__(self, argv: list[str], timeout: float) -> tuple[int | None, str, str]:
        self.calls.append((argv, timeout))
        return self.outcomes.pop(0)


SUCCESS = (
    0,
    json.dumps(
        {
            "portfolio_snapshot_id": "snap_codex_20260914T161500Z",
            "captured_at": "2026-09-14T16:15:00+00:00",
            "account_equity": 100.12,
            "buying_power": 50.0,
            "positions": 2,
        }
    )
    + "\n",
    "",
)


def tick(tmp_path: Path, collector: Collector, **options: object) -> tuple[int, dict[str, object]]:
    arguments: dict[str, object] = {
        "db": str(tmp_path / "source.db"),
        "profile": "codex",
        "model": "gpt-5.6-luna",
        "codex_home": str(tmp_path / "codex-home"),
        "state_dir": tmp_path / "state",
        "now": at("2026-09-14T12:07"),
        "collect": collector,
    }
    arguments.update(options)
    return run(**arguments)  # type: ignore[arg-type]


def test_outside_a_session_nothing_starts_and_nothing_is_written(tmp_path: Path) -> None:
    collector = Collector()

    code, result = tick(tmp_path, collector, now=at("2026-09-12T11:00"))

    assert (code, result["outcome"], result["reason"]) == (0, "skipped", "weekend")
    assert collector.calls == []
    assert not (tmp_path / "state").exists()
    assert not (tmp_path / "source.db").exists()


def test_a_session_tick_runs_only_the_snapshot_command(tmp_path: Path) -> None:
    collector = Collector(SUCCESS)

    code, result = tick(tmp_path, collector)

    assert code == 0
    assert result["outcome"] == "success"
    assert result["summary"] == {
        "captured_at": "2026-09-14T16:15:00+00:00",
        "account_equity": 100.12,
        "positions": 2,
    }
    assert result["alert"] is None
    (argv, timeout), *_ = collector.calls
    assert argv[:3] == [sys.executable, "-m", "app.broker.collector"]
    assert argv[-1] == "snapshot"
    assert not {"preflight", "prepare-live", "review", "order"} & set(argv)
    assert timeout == valuation.DEFAULT_TIMEOUT_SECONDS < 15 * 60


def test_an_overlapping_tick_skips_without_starting_a_session(tmp_path: Path) -> None:
    collector = Collector()

    with exclusive(tmp_path / "state" / "live-valuation.lock") as held:
        assert held
        code, result = tick(tmp_path, collector)

    assert (code, result["outcome"], result["reason"]) == (0, "skipped", "overlap")
    assert collector.calls == []
    with exclusive(tmp_path / "state" / "live-valuation.lock") as again:
        assert again


def test_failures_alert_first_then_at_the_threshold_then_on_recovery(tmp_path: Path) -> None:
    failed = (1, "", "app.broker.session.BrokerSessionFailure: session_exit_2\n")
    collector = Collector(failed, (None, "", ""), failed, failed, SUCCESS, SUCCESS)

    results = [tick(tmp_path, collector, alert_after=3) for _ in range(6)]

    assert [code for code, _ in results] == [1, 1, 1, 1, 0, 0]
    assert [result["consecutive_failures"] for _, result in results] == [1, 2, 3, 4, 0, 0]
    alerts = [result["alert"] for _, result in results]
    assert alerts[0] == "BouStrategy valuation FAILED: BrokerSessionFailure: session_exit_2 (0.0s)"
    assert alerts[1] is None
    assert results[1][1]["reason"] == "timeout"
    assert "3 ticks in a row" in str(alerts[2])
    assert alerts[3] is None
    assert alerts[4] == "BouStrategy valuation recovered after 4 failed ticks (0.0s)"
    assert alerts[5] is None
    state = json.loads((tmp_path / "state" / "live-valuation.json").read_text(encoding="utf-8"))
    assert state["consecutive_failures"] == 0


@pytest.mark.parametrize(
    "stderr",
    [
        f"ValueError: account {FINGERPRINT} mismatch",
        'Traceback (most recent call last):\n  File "C:\\Users\\Administrator\\x.py"',
        "RuntimeError: https://discord.com/api/webhooks/123/secret-token",
        "sqlite3.OperationalError: unable to open C:\\Users\\Administrator\\data\\x.db",
        "Error: account number 5550001234 rejected",
    ],
)
def test_alerts_never_carry_collector_output(
    tmp_path: Path, stderr: str, capsys: pytest.CaptureFixture[str]
) -> None:
    code, result = tick(tmp_path, Collector((1, f"{FINGERPRINT}\n", stderr)))

    alert = str(result["alert"])
    assert code == 1
    assert result["reason"] == "exit_1"
    for secret in (FINGERPRINT, "Administrator", "discord", "secret-token", "5550001234"):
        assert secret not in alert
        assert secret not in json.dumps(result)
    # The private operator log still receives the tail for diagnosis.
    assert stderr.splitlines()[-1] in capsys.readouterr().err


def test_failure_reason_keeps_only_known_safe_codes() -> None:
    assert failure_reason(None, "anything") == "timeout"
    assert failure_reason(3, "") == "exit_3"
    assert (
        failure_reason(1, "x\nValueError: collector_account_mismatch\n")
        == "ValueError: collector_account_mismatch"
    )
    assert failure_reason(1, "ValueError: Collector Account 1234") == "exit_1"


def test_what_if_reports_the_decision_without_starting_or_writing(tmp_path: Path) -> None:
    collector = Collector()

    for moment, would_run in ((at("2026-09-14T12:07"), True), (at("2026-09-12T12:07"), False)):
        code, result = tick(tmp_path, collector, now=moment, what_if=True)
        assert (code, result["outcome"], result["would_run"]) == (0, "what_if", would_run)
        assert "<codex-home>" in str(result["command"])
        assert str(tmp_path) not in json.dumps(result)

    assert collector.calls == []
    assert not (tmp_path / "state").exists()


def test_run_collector_kills_a_hung_collector_at_the_timeout() -> None:
    started = time.monotonic()

    returncode, _, _ = run_collector([sys.executable, "-c", "import time; time.sleep(60)"], 1.0)

    assert returncode is None
    assert time.monotonic() - started < 30
