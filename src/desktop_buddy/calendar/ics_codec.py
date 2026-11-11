"""Bounded, offline ICS snapshots. Never retrieve URIs or evaluate alarms."""

from collections import defaultdict
from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from dateutil.rrule import rrulestr
from dateutil.tz import datetime_ambiguous, datetime_exists

from desktop_buddy.calendar.recurrence import ALLOWED, WEEKDAYS, encode, parts
from desktop_buddy.chat.parser import looks_secret
from desktop_buddy.models.calendar_transfer import CalendarEntry, CalendarFileError, ParsedCalendar
from desktop_buddy.models.planning import CalendarEvent, Record, Task

MAX_BYTES = 8 * 1024 * 1024
MAX_ITEMS = 1000
MAX_SCANS = 100000
PROPERTIES = {
    "UID",
    "SUMMARY",
    "DESCRIPTION",
    "DTSTART",
    "DTEND",
    "DUE",
    "DURATION",
    "RRULE",
    "RDATE",
    "EXRULE",
    "EXDATE",
    "RECURRENCE-ID",
    "STATUS",
    "PERCENT-COMPLETE",
    "PRIORITY",
    "LAST-MODIFIED",
    "DTSTAMP",
    "SEQUENCE",
    "X-DESKTOPBUDDY-DATE-ONLY",
}


def window(start: date, end: date) -> None:
    if type(start) is not date or type(end) is not date or not 1 <= (end - start).days <= 366:
        raise CalendarFileError("기간은 1~366일로 선택해 주세요.")
    if not 1900 <= start.year <= (end - timedelta(days=1)).year <= 2100:
        raise CalendarFileError("날짜는 1900~2100년 사이로 선택해 주세요.")


def clean_text(value: object, limit: int, *, multiline: bool = False) -> str:
    text = str(value)
    try:
        text.encode("utf-8")
    except UnicodeError:
        raise CalendarFileError("지원하지 않는 문자가 있어요.") from None
    if len(text) > limit or any(ord(c) < 32 and (not multiline or c not in "\n\t") for c in text):
        raise CalendarFileError("제목·메모·식별자의 길이나 문자를 확인해 주세요.")
    if looks_secret(text):
        raise CalendarFileError("비밀 값으로 보이는 내용을 포함한 항목은 가져오지 않아요.")
    return text


def seoul_snapshot(record: Record) -> Record:
    """The local calendar displays Seoul time; DATE values remain calendar dates."""
    zone = ZoneInfo("Asia/Seoul")
    if isinstance(record, CalendarEvent):
        start = (
            datetime.combine(record.start.date(), time(), zone)
            if record.all_day
            else record.start.astimezone(zone)
        )
        end = (
            datetime.combine(record.end.date(), time(), zone)
            if record.all_day
            else record.end.astimezone(zone)
        )
        if not datetime_exists(start) or not datetime_exists(end):
            raise CalendarFileError("서울 시간에서 존재하지 않는 시각은 가져오지 않아요.")
        return replace(record, start_at=start, end_at=end, timezone=zone.key)
    start = record.start.astimezone(zone)
    if record.start_time is not None and datetime_ambiguous(start):
        raise CalendarFileError("서울의 중복 일광절약 시각은 할 일 시각으로 가져올 수 없어요.")
    return replace(
        record,
        scheduled_date=record.scheduled_date if record.start_time is None else start.date(),
        start_time=None if record.start_time is None else start.time().replace(tzinfo=None),
        due_at=record.due_at.astimezone(zone) if record.due_at else None,
        timezone=zone.key,
    )


def _filtered(data: bytes) -> tuple[str, set[str]]:
    if not data or len(data) > MAX_BYTES:
        raise CalendarFileError("ICS 파일은 비어 있지 않은 8 MiB 이하 파일이어야 해요.")
    try:
        text = data.decode("utf-8-sig").replace("\r\n", "\n")
    except UnicodeError:
        raise CalendarFileError("UTF-8 ICS 파일을 선택해 주세요.") from None
    if "\r" in text or "\x00" in text:
        raise CalendarFileError("ICS 줄 구분이나 문자를 확인해 주세요.")
    physical = text.split("\n")
    if len(physical) > 120000:
        raise CalendarFileError("ICS 파일의 줄 수가 너무 많아요.")
    lines = []
    for line in physical:
        if line.startswith((" ", "\t")):
            if not lines:
                raise CalendarFileError("잘못 접힌 ICS 줄이에요.")
            lines[-1] += line[1:]
        elif line:
            lines.append(line)
        if lines and len(lines[-1].encode("utf-8")) > 8192:
            raise CalendarFileError("ICS 한 항목의 줄이 너무 길어요.")
    if len(lines) > 50000:
        raise CalendarFileError("ICS 속성이 너무 많아요.")
    stack, output, notes = [], [], set()
    roots = components = 0
    for line in lines:
        name, sep, value = line.partition(":")
        name = name.upper()
        if not sep:
            raise CalendarFileError("잘못된 ICS 속성이 있어요.")
        if name == "BEGIN":
            component = value.upper()
            if not stack:
                if component != "VCALENDAR" or roots:
                    raise CalendarFileError("한 개의 VCALENDAR 파일만 가져올 수 있어요.")
                roots += 1
            elif component == "VCALENDAR":
                raise CalendarFileError("중첩된 캘린더는 지원하지 않아요.")
            stack.append(component)
            if len(stack) > 6:
                raise CalendarFileError("ICS 구성 요소가 너무 깊게 중첩되었어요.")
            if len(stack) == 2 and component in ("VEVENT", "VTODO"):
                components += 1
                if components > MAX_ITEMS:
                    raise CalendarFileError("파일당 일정·할 일 구성 요소는 1,000개까지예요.")
            if stack == ["VCALENDAR"] or (len(stack) == 2 and component in ("VEVENT", "VTODO")):
                output.append(line)
            elif len(stack) == 2:
                notes.add(
                    "사용자 정의 VTIMEZONE 대신 내장 IANA 시간대를 사용해요."
                    if component == "VTIMEZONE"
                    else "일지 등 부가 구성 요소는 가져오지 않아요."
                )
            elif stack[1] in ("VEVENT", "VTODO"):
                if component != "VALARM" or len(stack) != 3:
                    raise CalendarFileError("일정 안의 지원하지 않는 중첩 구성 요소가 있어요.")
                notes.add("첨부·초대·URL·알람은 실행하거나 가져오지 않아요.")
        elif name == "END":
            if not stack or stack[-1] != value.upper():
                raise CalendarFileError("ICS 구성 요소의 시작/끝이 맞지 않아요.")
            if len(stack) == 1 or (len(stack) == 2 and stack[1] in ("VEVENT", "VTODO")):
                output.append(line)
            stack.pop()
        elif not stack:
            raise CalendarFileError("캘린더 밖에 속성이 있어요.")
        elif len(stack) == 1:
            if name.split(";", 1)[0] in ("VERSION", "PRODID", "METHOD", "X-WR-TIMEZONE"):
                output.append(line)
        elif len(stack) == 2 and stack[1] in ("VEVENT", "VTODO"):
            if name.split(";", 1)[0] in PROPERTIES:
                output.append(line)
            else:
                notes.add("첨부·초대·URL·알람·분류 등 지원하지 않는 속성은 제외해요.")
    if stack or roots != 1:
        raise CalendarFileError("완전한 VCALENDAR 파일을 선택해 주세요.")
    return "\r\n".join(output) + "\r\n", notes


def _zone(name: str) -> ZoneInfo:
    if name == "Korea Standard Time":
        name = "Asia/Seoul"
    try:
        return ZoneInfo(name)
    except (ValueError, KeyError):
        raise CalendarFileError(
            "지원하지 않는 시간대예요. IANA 시간대나 UTC로 내보내 주세요."
        ) from None


def _value(component, key: str, default=None):
    value = component.get(key)
    if value is None:
        return default
    if isinstance(value, list):
        raise CalendarFileError("중복된 단일 속성이 있어요.")
    return value


def _temporal(prop, fallback: ZoneInfo) -> tuple[datetime, bool]:
    value = prop.dt
    if type(value) is date:
        if not 1898 <= value.year <= 2102:
            raise CalendarFileError("날짜 범위를 확인해 주세요.")
        return datetime.combine(value, time(), ZoneInfo("Asia/Seoul")), True
    if not isinstance(value, datetime):
        raise CalendarFileError("날짜/시각 형식을 지원하지 않아요.")
    tzid = prop.params.get("TZID")
    zone = _zone(str(tzid)) if tzid else None
    if zone:
        value = value.replace(tzinfo=None).replace(tzinfo=zone)
    elif value.tzinfo is None:
        value = value.replace(tzinfo=fallback)
    if not 1898 <= value.year <= 2102 or not datetime_exists(value):
        raise CalendarFileError("날짜 범위 또는 존재하지 않는 시각을 확인해 주세요.")
    if (zone or prop.dt.tzinfo is None) and datetime_ambiguous(value):
        raise CalendarFileError("중복되는 일광절약 시각은 UTC로 지정해 주세요.")
    return value, False


def _record(component, fallback: ZoneInfo) -> Record:
    if component.errors or any(k in component for k in ("RDATE", "EXRULE")):
        raise CalendarFileError("잘못되었거나 지원하지 않는 반복/속성이 있어요.")
    title = clean_text(_value(component, "SUMMARY", ""), 200).strip()
    description = clean_text(_value(component, "DESCRIPTION", ""), 4000, multiline=True)
    if not title:
        raise CalendarFileError("제목이 없는 항목은 가져오지 않아요.")
    start_prop = _value(component, "DTSTART")
    if start_prop is None:
        raise CalendarFileError("시작 날짜가 없는 항목은 가져오지 않아요.")
    start, all_day = _temporal(start_prop, fallback)
    zone_name = getattr(start.tzinfo, "key", "UTC")
    if component.name == "VEVENT":
        end_prop, duration = _value(component, "DTEND"), _value(component, "DURATION")
        if end_prop is not None and duration is not None:
            raise CalendarFileError("종료 시각과 기간이 동시에 지정되었어요.")
        if end_prop is not None:
            end, end_day = _temporal(end_prop, fallback)
            if end_day != all_day:
                raise CalendarFileError("종일/시각 형식이 서로 다르게 지정되었어요.")
        elif duration is not None:
            if not isinstance(duration.dt, timedelta) or (all_day and duration.dt.seconds):
                raise CalendarFileError("기간 형식을 확인해 주세요.")
            end = start + duration.dt
        else:
            end = start + timedelta(days=1) if all_day else start
        if not start < end or end - start > timedelta(days=366):
            raise CalendarFileError("종료는 시작 이후이며 일정 길이는 366일 이하여야 해요.")
        return CalendarEvent(
            title, start, end, description=description, all_day=all_day, timezone=zone_name
        )
    due_prop = _value(component, "DUE")
    due = None
    if due_prop is not None:
        due, due_day = _temporal(due_prop, fallback)
        if due_day != all_day or due <= start:
            raise CalendarFileError("할 일의 시작/마감 형식은 같고 마감이 시작보다 뒤여야 해요.")
        if due_day:
            raise CalendarFileError("날짜만 있는 할 일 마감은 시각으로 내보내 주세요.")
    if _value(component, "DURATION") is not None:
        raise CalendarFileError("기간으로 지정한 할 일은 지원하지 않아요.")
    priority = int(_value(component, "PRIORITY", 0))
    percent = int(_value(component, "PERCENT-COMPLETE", 0))
    if not 0 <= priority <= 9 or not 0 <= percent <= 100:
        raise CalendarFileError("우선순위/완료 비율을 확인해 주세요.")
    return Task(
        title,
        start.date(),
        description=description,
        start_time=None if all_day else start.time().replace(tzinfo=None),
        due_at=due,
        completed=str(_value(component, "STATUS", "")).upper() == "COMPLETED" or percent == 100,
        priority=2 if 1 <= priority <= 3 else 0 if priority >= 7 else 1,
        timezone=zone_name,
    )


def _rule(component, start: datetime, upper: datetime) -> tuple[str | None, int | None]:
    raw = _value(component, "RRULE")
    if raw is None:
        return None, None
    text = raw.to_ical().decode("ascii")
    if len(text) > 300:
        raise CalendarFileError("반복 규칙이 너무 길어요.")
    values = parts(text)
    if set(values) - ALLOWED or values.get("FREQ") not in {"DAILY", "WEEKLY", "MONTHLY", "YEARLY"}:
        raise CalendarFileError("매일·매주·매월·매년 반복만 지원해요.")
    if not 1 <= int(values.get("INTERVAL", "1")) <= 365:
        raise CalendarFileError("반복 간격을 확인해 주세요.")
    count = int(values.pop("COUNT")) if "COUNT" in values else None
    if count is not None and ("UNTIL" in values or not 1 <= count <= 10000):
        raise CalendarFileError("반복 횟수/종료 조건을 확인해 주세요.")
    for key in ("BYMONTHDAY", "BYMONTH"):
        if key in values:
            nums = values[key].split(",")
            bound = 31 if key == "BYMONTHDAY" else 12
            if len(nums) > 31 or any(not -bound <= int(v) <= bound or int(v) == 0 for v in nums):
                raise CalendarFileError("반복 날짜 범위를 확인해 주세요.")
            if key == "BYMONTH" and any(int(v) < 1 for v in nums):
                raise CalendarFileError("반복 월을 확인해 주세요.")
    if "BYDAY" in values:
        days = values["BYDAY"].split(",")
        if len(days) > 7 or any(v not in WEEKDAYS for v in days):
            raise CalendarFileError("서수가 없는 요일 반복만 지원해요.")
    until = upper.astimezone(UTC)
    if "UNTIL" in values:
        raw_until = raw.get("UNTIL")
        if not isinstance(raw_until, list) or len(raw_until) != 1:
            raise CalendarFileError("반복 종료 형식이 잘못되었어요.")
        value = raw_until[0]
        if (type(value) is date) != (type(component["DTSTART"].dt) is date):
            raise CalendarFileError("반복 시작과 종료의 날짜/시각 형식이 달라요.")
        if type(value) is date:
            value = datetime.combine(value + timedelta(days=1), time(), start.tzinfo) - timedelta(
                seconds=1
            )
        elif isinstance(value, datetime):
            value = value.replace(tzinfo=start.tzinfo) if value.tzinfo is None else value
        else:
            raise CalendarFileError("반복 종료 형식을 지원하지 않아요.")
        until = min(until, value.astimezone(UTC))
    values["UNTIL"] = until.strftime("%Y%m%dT%H%M%SZ")
    return encode(values), count


def parse_calendar(
    data: bytes, lower: date, upper: date, cancelled=lambda: False
) -> ParsedCalendar:
    window(lower, upper)
    text, notes = _filtered(data)
    try:
        from icalendar import Calendar

        calendar = Calendar.from_ical(text)
    except Exception:
        raise CalendarFileError(
            "ICS 파일을 해석하지 못했어요. 파일 형식을 확인해 주세요."
        ) from None
    if str(_value(calendar, "VERSION", "")) != "2.0" or calendar.errors:
        raise CalendarFileError("iCalendar 2.0 파일을 선택해 주세요.")
    if str(_value(calendar, "METHOD", "")).upper() not in ("", "PUBLISH"):
        raise CalendarFileError("초대·취소 요청 대신 일정 내보내기 파일을 선택해 주세요.")
    fallback = _zone(str(_value(calendar, "X-WR-TIMEZONE", "Asia/Seoul")))
    groups = defaultdict(list)
    for index, component in enumerate(calendar.subcomponents, 1):
        try:
            uid = clean_text(_value(component, "UID", ""), 512)
            if not uid.strip():
                raise CalendarFileError("외부 UID가 없어요.")
            groups[uid].append((index, component))
        except (ValueError, TypeError):
            notes.add(f"#{index}: 식별자를 확인하지 못해 제외했어요.")
    entries = []
    budget = 0
    over_limit = False
    for group in groups.values():
        if cancelled():
            raise CalendarFileError("작업을 취소했어요.")
        try:
            masters = [c for _, c in group if "RECURRENCE-ID" not in c]
            if len(masters) != 1 or len({c.name for _, c in group}) != 1:
                raise CalendarFileError("중복 원본 또는 원본 없는 반복 예외예요.")
            root = masters[0]
            if str(_value(root, "STATUS", "")).upper() == "CANCELLED":
                raise CalendarFileError(
                    "취소된 원본은 제외해요. 기존 앱 항목은 자동 삭제하지 않아요."
                )
            record = _record(root, fallback)
            date_only_hint = str(_value(root, "X-DESKTOPBUDDY-DATE-ONLY", "")).upper()
            if date_only_hint not in ("", "TRUE", "FALSE"):
                raise CalendarFileError("날짜 전용 할 일 표시가 잘못되었어요.")
            if date_only_hint == "TRUE" and (not isinstance(record, Task) or "RRULE" in root):
                raise CalendarFileError("날짜 전용 표시는 개별 할 일에만 사용할 수 있어요.")
            original = record.start
            overrides = {}
            override_components = {}
            excluded = set()
            raw_ex = root.get("EXDATE", [])
            for prop in raw_ex if isinstance(raw_ex, list) else [raw_ex]:
                for item in prop.dts:
                    dt, day_value = _temporal(item, original.tzinfo)
                    local = dt.astimezone(original.tzinfo)
                    if (
                        day_value != (type(root["DTSTART"].dt) is date)
                        or local.time() != original.time()
                    ):
                        raise CalendarFileError("반복 제외 날짜/시각이 원본과 맞지 않아요.")
                    excluded.add(local.date().isoformat())
            for _, component in group:
                if component is root:
                    continue
                recurrence_id = _value(component, "RECURRENCE-ID")
                if recurrence_id.params.get("RANGE"):
                    raise CalendarFileError("이후 전체 변경 예외는 지원하지 않아요.")
                dt, day_value = _temporal(recurrence_id, original.tzinfo)
                local = dt.astimezone(original.tzinfo)
                if local.time() != original.time() or day_value != (
                    type(root["DTSTART"].dt) is date
                ):
                    raise CalendarFileError("반복 예외의 원래 시각이 맞지 않아요.")
                key = local.date().isoformat()
                if key in overrides:
                    raise CalendarFileError("같은 발생일의 예외가 중복되었어요.")
                overrides[key] = (
                    None
                    if str(_value(component, "STATUS", "")).upper() == "CANCELLED"
                    else _record(component, fallback)
                )
                override_components[key] = component
            if (overrides or excluded) and "RRULE" not in root:
                raise CalendarFileError("반복 원본이 없는 예외는 지원하지 않아요.")
            horizon = max(
                [upper] + [date.fromisoformat(key) + timedelta(days=1) for key in overrides]
            )
            horizon_dt = datetime.combine(horizon, time(), ZoneInfo("Asia/Seoul"))
            rule, count = _rule(root, original, horizon_dt)
            anchors = rrulestr(rule, dtstart=original) if rule else [original]
            count_valid = 0
            generated = set()
            accepted = []
            for anchor in anchors:
                if rule and count_valid == 0 and anchor != original:
                    raise CalendarFileError("반복 시작 날짜가 규칙의 첫 발생일과 맞지 않아요.")
                budget += 1
                if budget > MAX_SCANS:
                    raise CalendarFileError(
                        "반복 계산 한도를 넘었어요. 시작이 최근인 파일로 나눠 주세요."
                    )
                if budget % 100 == 0 and cancelled():
                    raise CalendarFileError("작업을 취소했어요.")
                if not datetime_exists(anchor):
                    continue
                count_valid += 1
                if count is not None and count_valid > count:
                    break
                key = anchor.date().isoformat() if rule else ""
                generated.add(key)
                if key in excluded or (key in overrides and overrides[key] is None):
                    continue
                candidate = overrides.get(key)
                if candidate is None:
                    candidate = (
                        replace(
                            record, start_at=anchor, end_at=anchor + (record.end - record.start)
                        )
                        if isinstance(record, CalendarEvent)
                        else replace(
                            record,
                            scheduled_date=anchor.date(),
                            due_at=(
                                anchor + (record.due_at.astimezone(original.tzinfo) - original)
                                if record.due_at
                                else None
                            ),
                        )
                    )
                local = candidate.start.astimezone(ZoneInfo("Asia/Seoul"))
                end = (
                    candidate.end.astimezone(ZoneInfo("Asia/Seoul"))
                    if isinstance(candidate, CalendarEvent)
                    else local + timedelta(seconds=1)
                )
                nominal = anchor.astimezone(ZoneInfo("Asia/Seoul")).date()
                if not (local.date() < upper and end.date() >= lower) and not (
                    key in overrides and lower <= nominal < upper
                ):
                    continue
                if isinstance(candidate, CalendarEvent):
                    if (
                        not (
                            local < datetime.combine(upper, time(), ZoneInfo("Asia/Seoul"))
                            and end > datetime.combine(lower, time(), ZoneInfo("Asia/Seoul"))
                        )
                        and key not in overrides
                    ):
                        continue
                modified = _value(override_components.get(key, root), "LAST-MODIFIED")
                modified_text = None
                if modified is not None:
                    md, _ = _temporal(modified, fallback)
                    modified_text = md.astimezone(UTC).isoformat()
                if date_only_hint == "TRUE":
                    if local.time().replace(tzinfo=None) != time():
                        raise CalendarFileError(
                            "날짜 전용 할 일 표시는 서울 00:00에만 사용할 수 있어요."
                        )
                    candidate = replace(
                        candidate,
                        scheduled_date=local.date(),
                        start_time=None,
                        timezone="Asia/Seoul",
                    )
                accepted.append(
                    CalendarEntry(
                        clean_text(root["UID"], 512), key, seoul_snapshot(candidate), modified_text
                    )
                )
                if len(entries) + len(accepted) > MAX_ITEMS:
                    over_limit = True
                    raise CalendarFileError(
                        "선택 기간의 발생 항목이 1,000개를 넘어요. 기간을 줄여 주세요."
                    )
            if set(overrides) - generated:
                raise CalendarFileError("원래 반복에 없는 예외 날짜가 있어요.")
            entries.extend(accepted)
            if rule:
                notes.add(
                    "반복은 선택 기간의 개별 항목으로 가져와요. 원래 반복 규칙은 저장하지 않아요."
                )
            if excluded or any(v is None for v in overrides.values()):
                notes.add(
                    "제외/취소된 발생일은 건너뛰어요. 이미 가져온 앱 항목은 자동 삭제하지 않아요."
                )
        except (ValueError, TypeError, KeyError, OverflowError) as error:
            if over_limit:
                raise CalendarFileError(
                    "선택 기간의 발생 항목이 1,000개를 넘었어요. 기간을 줄여 주세요."
                ) from None
            if budget > MAX_SCANS or len(entries) > MAX_ITEMS or cancelled():
                raise CalendarFileError(
                    "계산 한도를 넘었거나 취소했어요. 파일/기간을 줄여 주세요."
                ) from None
            detail = (
                str(error)
                if isinstance(error, CalendarFileError)
                else "날짜·시각·반복 형식을 확인해 주세요."
            )
            notes.add(f"#{group[0][0]}: {detail}")
    notes.add("시간대 없는 시각은 파일의 시간대 또는 서울로 해석해요. 알람·첨부는 제외해요.")
    return ParsedCalendar(tuple(entries), tuple(sorted(notes)))


def serialize_calendar(entries: tuple[CalendarEntry, ...]) -> bytes:
    if not 0 < len(entries) <= MAX_ITEMS:
        raise CalendarFileError("내보낼 항목은 1~1,000개를 선택해 주세요.")
    from icalendar import Calendar, Event, Todo

    calendar = Calendar()
    calendar.add("prodid", "-//DesktopBuddy//Calendar file exchange//KO")
    calendar.add("version", "2.0")
    for entry in entries:
        record = entry.record
        component = Event() if isinstance(record, CalendarEvent) else Todo()
        component.add("uid", entry.uid)
        component.add("dtstamp", datetime.now(UTC).replace(microsecond=0))
        component.add("summary", record.title)
        if record.description:
            component.add("description", record.description)
        if isinstance(record, CalendarEvent):
            component.add(
                "dtstart", record.start.date() if record.all_day else record.start.astimezone(UTC)
            )
            component.add(
                "dtend", record.end.date() if record.all_day else record.end.astimezone(UTC)
            )
        else:
            if record.due_at is not None and record.due_at <= record.start:
                raise CalendarFileError("할 일의 마감은 시작 이후여야 ICS로 내보낼 수 있어요.")
            component.add(
                "dtstart",
                record.scheduled_date
                if record.start_time is None and record.due_at is None
                else record.start.astimezone(UTC),
            )
            if record.start_time is None and record.due_at is not None:
                component.add("x-desktopbuddy-date-only", "TRUE")
            if record.due_at:
                component.add("due", record.due_at.astimezone(UTC))
            component.add("status", "COMPLETED" if record.completed else "NEEDS-ACTION")
            component.add("percent-complete", 100 if record.completed else 0)
            component.add("priority", {0: 9, 1: 5, 2: 1}[record.priority])
        calendar.add_component(component)
    data = calendar.to_ical()
    if len(data) > MAX_BYTES:
        raise CalendarFileError("내보낼 파일이 8 MiB를 넘어요. 기간을 줄여 주세요.")
    return data
