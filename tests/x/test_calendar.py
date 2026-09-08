from datetime import date, time

import pytest

from app.x.calendar import CalendarCoverageError, run_slots, slot_should_run


def test_full_close_holiday_has_no_slots() -> None:
    assert run_slots(date(2026, 11, 26)) == []


def test_half_day_shifts_close_and_omits_midday() -> None:
    slots = run_slots(date(2026, 11, 27))

    assert [(slot, value.replace(tzinfo=None)) for slot, value in slots] == [
        ("morning", time(8, 45)),
        ("close", time(14, 45)),
    ]


def test_sunday_runs_weekly_even_before_holiday() -> None:
    slots = run_slots(date(2026, 9, 6))

    assert [(slot, value.replace(tzinfo=None)) for slot, value in slots] == [
        ("weekly", time(18, 0))
    ]


def test_saturday_has_no_slots() -> None:
    assert run_slots(date(2026, 7, 18)) == []
    assert slot_should_run(date(2026, 7, 18), "morning") is None


def test_date_past_coverage_raises() -> None:
    with pytest.raises(CalendarCoverageError, match="2028-12-31"):
        run_slots(date(2029, 1, 1))


@pytest.mark.parametrize(
    "day", ["2026-01-01", "2026-04-03", "2027-06-18", "2027-12-24", "2028-04-14"]
)
def test_full_calendar_holidays(day: str) -> None:
    from app.x.calendar import is_session

    assert not is_session(date.fromisoformat(day))


def test_completed_sessions_respect_early_close_dst_and_coverage() -> None:
    from datetime import UTC, datetime

    from app.x.calendar import completed_session, is_session, previous_session, session_close

    assert completed_session(datetime(2026, 11, 27, 17, 59, tzinfo=UTC)) == date(2026, 11, 25)
    assert completed_session(datetime(2026, 11, 27, 18, 0, tzinfo=UTC)) == date(2026, 11, 27)
    before_dst, after_dst = session_close(date(2026, 3, 6)), session_close(date(2026, 3, 9))
    assert before_dst and after_dst
    assert before_dst.astimezone(UTC).hour == 21
    assert after_dst.astimezone(UTC).hour == 20
    assert is_session(date(2028, 1, 3))
    early = session_close(date(2028, 7, 3))
    assert early and early.hour == 13
    assert previous_session(date(2028, 7, 5)) == date(2028, 7, 3)
    with pytest.raises(CalendarCoverageError):
        previous_session(date(2026, 1, 2))
