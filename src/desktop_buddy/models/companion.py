from dataclasses import dataclass
from datetime import date, datetime, timedelta


def in_time_window(value: datetime, start: str, end: str) -> bool:
    local = value.strftime("%H:%M")
    return start <= local < end if start <= end else local >= start or local < end


def counted_days(start: date, end: date, rest_weekdays: tuple[int, ...]) -> int:
    """Count an inclusive date range without iterating over long histories."""
    length = max(0, (end - start).days + 1)
    weeks, remainder = divmod(length, 7)
    return weeks * (7 - len(set(rest_weekdays))) + sum(
        (start.weekday() + offset) % 7 not in rest_weekdays for offset in range(remainder)
    )


def study_gap(last: date, today: date, weekdays: tuple[int, ...], periods: list[dict]) -> int:
    lower = last + timedelta(days=1)
    total = counted_days(lower, today, weekdays)
    merged = []
    for period in sorted(periods, key=lambda row: row["start_date"]):
        start, end = max(lower, period["start_date"]), min(today, period["end_date"])
        if start > end:
            continue
        if merged and (start - merged[-1][1]).days <= 1:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    return max(0, total - sum(counted_days(a, b, weekdays) for a, b in merged))


@dataclass(frozen=True)
class CompanionSnapshot:
    state: str = "idle"
    description: str = "편안하게 함께하고 있어요."
    gap_days: int = 0
    last_valid_date: date | None = None
    resting: bool = False
    sleeping: bool = False
    quiet: bool = False
    clock_warning: bool = False
    fullscreen: bool = False


@dataclass(frozen=True)
class Briefing:
    day: date
    heading: str
    summary: str
    details: str
