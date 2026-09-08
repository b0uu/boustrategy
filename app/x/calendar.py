"""Versioned NYSE regular sessions; digester slots retain their weekly cadence."""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

NEW_YORK = ZoneInfo("America/New_York")
CALENDAR_VERSION = "nyse-2026-2028-v1"
COVERAGE_START = date(2026, 1, 1)
COVERAGE_END = date(2028, 12, 31)

_FULL_CLOSES = {
    date.fromisoformat(value)
    for value in (
        "2026-01-01",
        "2026-01-19",
        "2026-02-16",
        "2026-04-03",
        "2026-05-25",
        "2026-06-19",
        "2026-07-03",
        "2026-09-07",
        "2026-11-26",
        "2026-12-25",
        "2027-01-01",
        "2027-01-18",
        "2027-02-15",
        "2027-03-26",
        "2027-05-31",
        "2027-06-18",
        "2027-07-05",
        "2027-09-06",
        "2027-11-25",
        "2027-12-24",
        "2028-01-17",
        "2028-02-21",
        "2028-04-14",
        "2028-05-29",
        "2028-06-19",
        "2028-07-04",
        "2028-09-04",
        "2028-11-23",
        "2028-12-25",
    )
}
_HALF_DAYS = {
    date.fromisoformat(value)
    for value in (
        "2026-11-27",
        "2026-12-24",
        "2027-11-26",
        "2028-07-03",
        "2028-11-24",
    )
}


class CalendarCoverageError(ValueError):
    pass


def is_session(day: date) -> bool:
    if not COVERAGE_START <= day <= COVERAGE_END:
        raise CalendarCoverageError(
            f"NYSE calendar coverage is {COVERAGE_START} through {COVERAGE_END}"
        )
    return day.weekday() < 5 and day not in _FULL_CLOSES


def session_close(day: date) -> datetime | None:
    if not is_session(day):
        return None
    return datetime.combine(day, time(13 if day in _HALF_DAYS else 16), NEW_YORK)


def previous_session(day: date) -> date:
    is_session(day)
    candidate = day - timedelta(days=1)
    while not is_session(candidate):
        candidate -= timedelta(days=1)
    return candidate


def completed_session(observed_at: datetime) -> date:
    if observed_at.tzinfo is None:
        raise ValueError("completed session requires an aware observation time")
    day = observed_at.astimezone(NEW_YORK).date()
    close = session_close(day)
    return day if close is not None and close <= observed_at else previous_session(day)


def run_slots(d: date) -> list[tuple[str, time]]:
    eligible = is_session(d)
    if d.weekday() == 6:
        return [("weekly", time(18, 0, tzinfo=NEW_YORK))]
    if not eligible:
        return []
    if d in _HALF_DAYS:
        return [("morning", time(8, 45, tzinfo=NEW_YORK)), ("close", time(14, 45, tzinfo=NEW_YORK))]
    return [
        ("morning", time(8, 45, tzinfo=NEW_YORK)),
        ("midday", time(12, 30, tzinfo=NEW_YORK)),
        ("close", time(17, 45, tzinfo=NEW_YORK)),
    ]


def slot_should_run(d: date, slot: str) -> time | None:
    return dict(run_slots(d)).get(slot)


def completed_through(day: date, observed_at: datetime) -> date:
    """Bound a requested daily-data endpoint by actual session completion."""
    is_session(day)
    end = datetime.combine(day, time.max, NEW_YORK)
    return completed_session(min(end, observed_at))
