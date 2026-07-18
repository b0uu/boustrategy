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
    with pytest.raises(CalendarCoverageError, match="2026-12-31"):
        run_slots(date(2027, 1, 1))
