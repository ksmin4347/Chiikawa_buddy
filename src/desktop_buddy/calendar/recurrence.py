from datetime import UTC, date, datetime, time, timedelta

from dateutil.rrule import rrulestr
from dateutil.tz import datetime_exists

ALLOWED = {"FREQ", "INTERVAL", "BYDAY", "BYMONTHDAY", "BYMONTH", "COUNT", "UNTIL", "WKST"}
WEEKDAYS = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")


def parts(rule: str) -> dict[str, str]:
    try:
        values = dict(part.split("=", 1) for part in rule.upper().removeprefix("RRULE:").split(";"))
    except ValueError as error:
        raise ValueError("반복 규칙을 확인해 주세요.") from error
    return values


def encode(values: dict[str, str]) -> str:
    return ";".join(f"{key}={value}" for key, value in values.items())


def validate_rule(rule: str | None, start: datetime) -> str | None:
    if not rule:
        return None
    if len(rule) > 300 or "\n" in rule or "\r" in rule:
        raise ValueError("반복 규칙이 너무 길거나 잘못되었어요.")
    values = parts(rule)
    if set(values) - ALLOWED or values.get("FREQ") not in {"DAILY", "WEEKLY", "MONTHLY", "YEARLY"}:
        raise ValueError("매일·매주·매월·매년 반복만 사용할 수 있어요.")
    if not 1 <= int(values.get("INTERVAL", "1")) <= 365:
        raise ValueError("반복 간격은 1~365로 지정해 주세요.")
    if "COUNT" in values and ("UNTIL" in values or not 1 <= int(values["COUNT"]) <= 10000):
        raise ValueError("반복 종료 날짜 또는 1~10,000회 중 하나를 선택해 주세요.")
    try:
        parsed = rrulestr(encode(values), dtstart=start)
        first = parsed.after(start - timedelta(seconds=1))
    except (ValueError, TypeError, OverflowError) as error:
        raise ValueError("반복 요일과 종료 조건을 확인해 주세요.") from error
    if first is None:
        raise ValueError("반복 종료는 시작 날짜보다 빠를 수 없어요.")
    return encode(values)


def _nearby_anchor(start: datetime, values: dict[str, str], lower: datetime) -> datetime:
    """Skip complete uncounted recurrence cycles without changing their phase."""
    if lower <= start:
        return start
    interval = int(values.get("INTERVAL", "1"))
    frequency = values["FREQ"]
    if frequency in {"DAILY", "WEEKLY"}:
        days = interval * (7 if frequency == "WEEKLY" else 1)
        cycles = max(0, (lower.date() - start.date()).days // days - 1)
        return start + timedelta(days=cycles * days)
    if frequency == "MONTHLY":
        difference = (lower.year - start.year) * 12 + lower.month - start.month
    else:
        difference = lower.year - start.year
    cycles = max(0, difference // interval - 1)
    while cycles:
        try:
            if frequency == "MONTHLY":
                month_index = start.year * 12 + start.month - 1 + cycles * interval
                return start.replace(year=month_index // 12, month=month_index % 12 + 1)
            return start.replace(year=start.year + cycles * interval)
        except ValueError:  # A 31st day or leap day can be absent in that cycle.
            cycles -= 1
    return start


def starts_between(
    rule: str | None, start: datetime, lower: datetime, upper: datetime
) -> list[datetime]:
    if not rule:
        return [start] if lower <= start < upper else []
    values = parts(rule)
    if "COUNT" in values:
        count = int(values.pop("COUNT"))
        parsed = rrulestr(encode(values), dtstart=start)
        result, valid_count = [], 0
        for value in parsed:
            if value >= upper:
                break
            if not datetime_exists(value):
                continue
            valid_count += 1
            if lower <= value:
                result.append(value)
            if valid_count >= count:
                break
        return result
    anchor = _nearby_anchor(start, values, lower)
    parsed = rrulestr(rule, dtstart=anchor)
    return [
        value
        for value in parsed.between(lower, upper, inc=True)
        if lower <= value < upper and datetime_exists(value)
    ]


def end_before(rule: str, start: datetime, cutoff: date) -> str:
    values = parts(rule)
    values.pop("COUNT", None)
    until = datetime.combine(cutoff, time(), start.tzinfo) - timedelta(seconds=1)
    previous_until = values.get("UNTIL")
    formatted = until.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    values["UNTIL"] = min(previous_until, formatted) if previous_until else formatted
    return encode(values)


def remaining_rule(rule: str, start: datetime, cutoff: date) -> str:
    values = parts(rule)
    if "COUNT" in values:
        end = datetime.combine(cutoff, time(), start.tzinfo)
        before = len(starts_between(rule, start, start, end))
        values["COUNT"] = str(max(1, int(values["COUNT"]) - before))
    return encode(values)
