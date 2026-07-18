from datetime import date, time
from zoneinfo import ZoneInfo

NEW_YORK = ZoneInfo("America/New_York")
COVERAGE_END = date(2026, 12, 31)

_FULL_CLOSES = {date(2026, 9, 7), date(2026, 11, 26), date(2026, 12, 25)}
_HALF_DAYS = {date(2026, 11, 27), date(2026, 12, 24)}


class CalendarCoverageError(ValueError):
    pass


def _at(hour: int, minute: int) -> time:
    return time(hour, minute, tzinfo=NEW_YORK)


def run_slots(d: date) -> list[tuple[str, time]]:
    if d > COVERAGE_END:
        raise CalendarCoverageError(f"NYSE calendar coverage ends at {COVERAGE_END.isoformat()}")
    if d.weekday() == 6:
        return [("weekly", _at(18, 0))]
    if d.weekday() == 5 or d in _FULL_CLOSES:
        return []
    if d in _HALF_DAYS:
        return [("morning", _at(8, 45)), ("close", _at(14, 45))]
    return [("morning", _at(8, 45)), ("midday", _at(12, 30)), ("close", _at(17, 45))]


def slot_should_run(d: date, slot: str) -> time | None:
    return dict(run_slots(d)).get(slot)
