import sqlite3
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from desktop_buddy.calendar.file_io import file_token, read_calendar, write_calendar
from desktop_buddy.calendar.ics_codec import MAX_BYTES, parse_calendar, serialize_calendar
from desktop_buddy.database.store import Store
from desktop_buddy.models.calendar_transfer import CalendarEntry, CalendarFileError
from desktop_buddy.models.planning import CalendarEvent, Task
from desktop_buddy.services.calendar_transfer import CalendarTransferService, content_hash
from desktop_buddy.services.planning_service import PlanningService

DAY = date(2026, 11, 11)
END = DAY + timedelta(days=31)
ZONE = ZoneInfo("Asia/Seoul")


def ics(*components, header=""):
    return (
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//QA//KO\r\n"
        + header
        + "\r\n".join(components)
        + "\r\nEND:VCALENDAR\r\n"
    ).encode("utf-8")


def event(uid="qa-event", title="회의", start="20261111T090000Z", end="20261111T100000Z", extra=""):
    return (
        f"BEGIN:VEVENT\r\nUID:{uid}\r\nSUMMARY:{title}\r\nDTSTART:{start}\r\n"
        f"DTEND:{end}\r\n{extra}\r\nEND:VEVENT"
    )


def parsed(data):
    return parse_calendar(data, DAY, END)


def test_utf8_folding_escaping_and_utc_roundtrip():
    title = ("긴 한글 제목, 쉼표; 세미콜론\\ " * 6).strip()
    record = CalendarEvent(
        title,
        datetime(2026, 11, 11, 23, tzinfo=ZONE),
        datetime(2026, 11, 12, 2, tzinfo=ZONE),
        description="첫 줄\n다음 줄; 쉼표, 역슬래시\\",
    )
    raw = serialize_calendar((CalendarEntry("qa", "", record),))
    assert b"\r\n " in raw and all(len(line) <= 75 for line in raw.split(b"\r\n"))
    result = parsed(raw)
    assert len(result.entries) == 1 and content_hash(result.entries[0].record) == content_hash(
        record
    )


def test_all_day_end_is_exclusive_and_dates_never_shift_with_file_zone():
    data = ics(
        "BEGIN:VEVENT\r\nUID:day\r\nSUMMARY:휴가\r\nDTSTART;VALUE=DATE:20261111\r\n"
        "DTEND;VALUE=DATE:20261113\r\nEND:VEVENT",
        header="X-WR-TIMEZONE:Pacific/Auckland\r\n",
    )
    record = parsed(data).entries[0].record
    assert record.all_day and record.start.date() == DAY and record.end.date() == date(2026, 11, 13)
    assert record.timezone == "Asia/Seoul"


@pytest.mark.parametrize("zone", ["Asia/Seoul", "Korea Standard Time"])
def test_known_tzid_and_floating_seoul(zone):
    text = (
        event(start="20261111T090000", end="20261111T100000")
        .replace("DTSTART:", f'DTSTART;TZID="{zone}":')
        .replace("DTEND:", f'DTEND;TZID="{zone}":')
    )
    result = parsed(ics(text))
    assert result.entries[0].record.start.astimezone(ZONE).hour == 9
    floating = parsed(ics(event(start="20261111T090000", end="20261111T100000")))
    assert floating.entries[0].record.start.astimezone(ZONE).hour == 9


@pytest.mark.parametrize(
    "extra",
    [
        "RRULE:FREQ=HOURLY;COUNT=2",
        "RRULE:FREQ=DAILY;INTERVAL=0",
        "RRULE:FREQ=DAILY;COUNT=10001",
        "RRULE:FREQ=DAILY;COUNT=3;UNTIL=20261114T000000Z",
        "RRULE:FREQ=DAILY;BYSECOND=1",
        "RRULE:FREQ=MONTHLY;BYDAY=2MO",
        "RRULE:FREQ=DAILY;BYMONTH=13",
        "RDATE:20261112T090000Z",
        "EXRULE:FREQ=DAILY",
        "DTSTART:20261111T120000Z",
        "DURATION:PT1H",
        "SUMMARY:중복 제목",
    ],
)
def test_unsupported_or_ambiguous_properties_are_reported_not_partially_imported(extra):
    result = parsed(ics(event(extra=extra)))
    assert not result.entries and any("#1:" in note for note in result.notes)


@pytest.mark.parametrize(
    "changes",
    [
        dict(title=""),
        dict(start="20261311T090000Z"),
        dict(end="20261111T080000Z"),
        dict(title="x" * 201),
        dict(title="sk-test-" + "x" * 30),
        dict(uid=""),
    ],
)
def test_bad_item_does_not_discard_valid_neighbors(changes):
    result = parsed(ics(event(**changes), event(uid="valid", title="정상")))
    assert [e.record.title for e in result.entries] == ["정상"]


@pytest.mark.parametrize(
    "body",
    [
        b"",
        b"x" * (MAX_BYTES + 1),
        b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\n",
        b"BEGIN:VCALENDAR\r\nEND:VEVENT\r\n",
        b"\xff\xfe",
        b"x\x00x",
        ics(event(), header="METHOD:CANCEL\r\n"),
        ics(event(), header="METHOD:REQUEST\r\n"),
        ics(event()) + ics(event(uid="second")),
        ics(event(extra="DESCRIPTION:" + "x" * 8193)),
        ics("BEGIN:VEVENT\r\n" * 7 + "END:VEVENT\r\n" * 7),
        ics(*(event(uid=str(i)) for i in range(1001))),
    ],
)
def test_container_resource_and_method_limits(body):
    with pytest.raises(CalendarFileError):
        parsed(body)


def test_valarm_and_uri_fields_never_execute_or_survive_snapshot():
    data = ics(
        event(
            extra="ATTACH:https://invalid.example/remote\r\nURL:file:///secret\r\n"
            "BEGIN:VALARM\r\nACTION:PROCEDURE\r\nTRIGGER:-PT1M\r\n"
            "ATTACH:file:///run.exe\r\nEND:VALARM"
        )
    )
    result = parsed(data)
    assert len(result.entries) == 1 and result.entries[0].record.reminder_minutes is None
    output = serialize_calendar(result.entries)
    assert not any(value in output for value in (b"ATTACH", b"URL:", b"VALARM", b"run.exe"))


def test_unknown_tzid_cannot_silently_become_floating():
    raw = event(start="20261111T090000", end="20261111T100000").replace(
        "DTSTART:", "DTSTART;TZID=Untrusted/Zone:"
    )
    assert not parsed(ics(raw)).entries


def test_custom_vtimezone_is_not_evaluated():
    zone = (
        "BEGIN:VTIMEZONE\r\nTZID:Untrusted/Zone\r\nBEGIN:STANDARD\r\n"
        "DTSTART:19000101T000000\r\nTZOFFSETFROM:+0000\r\nTZOFFSETTO:+0100\r\n"
        "RRULE:FREQ=SECONDLY\r\nEND:STANDARD\r\nEND:VTIMEZONE"
    )
    result = parsed(ics(zone, event()))
    assert len(result.entries) == 1


def test_daily_exdate_override_and_cancelled_instance_keep_original_keys():
    root = event(extra="RRULE:FREQ=DAILY;COUNT=5\r\nEXDATE:20261112T090000Z")
    moved = event(
        start="20261116T120000Z", end="20261116T130000Z", extra="RECURRENCE-ID:20261113T090000Z"
    )
    cancelled = (
        "BEGIN:VEVENT\r\nUID:qa-event\r\nRECURRENCE-ID:20261114T090000Z\r\n"
        "STATUS:CANCELLED\r\nEND:VEVENT"
    )
    result = parsed(ics(root, moved, cancelled))
    assert [e.occurrence_key for e in result.entries] == ["2026-11-11", "2026-11-13", "2026-11-15"]
    assert result.entries[1].record.start.date() == date(2026, 11, 16)
    assert all(e.record.recurrence is None for e in result.entries)


def test_monthly_31st_and_all_day_exception_roundtrip():
    root = (
        "BEGIN:VEVENT\r\nUID:month\r\nSUMMARY:월말\r\nDTSTART;VALUE=DATE:20261031\r\n"
        "DTEND;VALUE=DATE:20261101\r\nRRULE:FREQ=MONTHLY;COUNT=3\r\n"
        "EXDATE;VALUE=DATE:20261231\r\nEND:VEVENT"
    )
    result = parse_calendar(ics(root), date(2026, 10, 1), date(2027, 3, 1))
    assert [e.record.start.date() for e in result.entries] == [
        date(2026, 10, 31),
        date(2027, 1, 31),
    ]


def test_expanded_entry_limit_rejects_whole_file_instead_of_silently_dropping_series():
    data = ics(*(event(uid=str(i), extra="RRULE:FREQ=DAILY;COUNT=366") for i in range(3)))
    with pytest.raises(CalendarFileError):
        parse_calendar(data, DAY, DAY + timedelta(days=366))


def test_last_modified_of_override_and_missing_end_semantics():
    root = event(extra="RRULE:FREQ=DAILY;COUNT=2\r\nLAST-MODIFIED:20261109T000000Z")
    override = event(extra="RECURRENCE-ID:20261112T090000Z\r\nLAST-MODIFIED:20261110T000000Z")
    result = parsed(ics(root, override))
    assert result.entries[1].modified.startswith("2026-11-10")
    no_end = event().replace("DTEND:20261111T100000Z\r\n", "")
    assert not parsed(ics(no_end)).entries
    day = "BEGIN:VEVENT\r\nUID:day\r\nSUMMARY:기념일\r\nDTSTART;VALUE=DATE:20261111\r\nEND:VEVENT"
    assert parsed(ics(day)).entries[0].record.end.date() == DAY + timedelta(days=1)


@pytest.mark.parametrize(
    "start,end", [(DAY, DAY), (DAY, DAY - timedelta(days=1)), (DAY, DAY + timedelta(days=367))]
)
def test_invalid_window_rejected(start, end):
    with pytest.raises(CalendarFileError):
        parse_calendar(ics(event()), start, end)


def test_duplicate_uid_and_out_of_rule_override_are_rejected():
    assert not parsed(ics(event(), event())).entries
    root = event(extra="RRULE:FREQ=DAILY;COUNT=2")
    override = event(extra="RECURRENCE-ID:20261120T090000Z")
    assert not parsed(ics(root, override)).entries


def test_dst_recurring_local_hour_is_preserved_and_ambiguous_time_rejected():
    raw = event(start="20261031T090000", end="20261031T100000", extra="RRULE:FREQ=DAILY;COUNT=3")
    raw = raw.replace("DTSTART:", "DTSTART;TZID=America/New_York:").replace(
        "DTEND:", "DTEND;TZID=America/New_York:"
    )
    result = parse_calendar(ics(raw), date(2026, 10, 30), date(2026, 11, 4))
    assert [
        r.record.start.astimezone(ZoneInfo("America/New_York")).hour for r in result.entries
    ] == [9, 9, 9]
    assert all(r.record.timezone == "Asia/Seoul" for r in result.entries)
    assert [r.record.start.astimezone(UTC).hour for r in result.entries] == [13, 14, 14]
    ambiguous = raw.replace("20261031T090000", "20261101T013000").replace(
        "20261031T100000", "20261101T023000"
    )
    assert not parse_calendar(ics(ambiguous), date(2026, 10, 30), date(2026, 11, 4)).entries


def test_vtodo_dates_deadline_priority_completion_roundtrip():
    task = Task(
        "공부", DAY, due_at=datetime(2026, 11, 11, 23, tzinfo=ZONE), completed=True, priority=2
    )
    raw = serialize_calendar((CalendarEntry("todo", "", task),))
    from icalendar import Calendar

    component = Calendar.from_ical(raw).subcomponents[0]
    assert isinstance(component["DTSTART"].dt, datetime)
    assert isinstance(component["DUE"].dt, datetime)
    assert component["DUE"].dt > component["DTSTART"].dt
    result = parsed(raw)
    assert isinstance(result.entries[0].record, Task)
    assert content_hash(result.entries[0].record) == content_hash(task)


def test_historic_seoul_ambiguous_task_time_is_reported_without_changing_event_instant():
    todo = (
        "BEGIN:VTODO\r\nUID:old-task\r\nSUMMARY:지난 할 일\r\nDTSTART:19881008T173000Z\r\nEND:VTODO"
    )
    meeting = event(start="19881008T173000Z", end="19881008T183000Z")
    result = parse_calendar(ics(todo, meeting), date(1988, 10, 9), date(1988, 10, 10))
    assert len(result.entries) == 1 and isinstance(result.entries[0].record, CalendarEvent)
    assert result.entries[0].record.start.astimezone(UTC).hour == 17


@pytest.mark.parametrize(
    "start,due",
    [(";VALUE=DATE:20261111", ":20261111T130000Z"), (":20261111T130000Z", ":20261111T120000Z")],
)
def test_invalid_vtodo_due_type_or_order_is_reported(start, due):
    data = ics(
        "BEGIN:VTODO\r\nUID:bad\r\nSUMMARY:할 일\r\nDTSTART"
        + start
        + "\r\nDUE"
        + due
        + "\r\nEND:VTODO"
    )
    assert not parsed(data).entries


def test_until_matches_start_type_and_remains_inclusive():
    good = parsed(ics(event(extra="RRULE:FREQ=DAILY;UNTIL=20261113T090000Z")))
    assert len(good.entries) == 3
    bad = parsed(ics(event(extra="RRULE:FREQ=DAILY;UNTIL=20261113")))
    assert not bad.entries


@pytest.fixture
def transfer(qapp, tmp_path):
    store = Store(tmp_path / "buddy.db")
    planning = PlanningService(store)
    clock = [0.0]
    service = CalendarTransferService(planning, clock=lambda: clock[0])
    yield service, planning, clock
    store.close()


def preview(service, data, source="원본"):
    return service.preview_import(parsed(data), source, DAY, END)


def selected(plan):
    return {r.id for r in plan.rows if r.action}


def test_preview_is_readonly_import_once_and_same_uid_never_duplicates(transfer):
    service, planning, _ = transfer
    before = service.fingerprint()
    plan = preview(service, ics(event()))
    assert service.fingerprint() == before and not planning.repository.records("event")
    assert service.apply_import(plan.id, selected(plan)) == (1, 0)
    with pytest.raises(CalendarFileError):
        service.apply_import(plan.id, selected(plan))
    repeat = preview(service, ics(event()))
    assert repeat.rows[0].action == "" and len(planning.repository.records("event")) == 1
    assert (
        planning.store.connection.execute("SELECT label FROM calendar_sources").fetchone()[0]
        == "원본"
    )


def test_remote_update_local_conflict_and_explicit_overwrite_preserve_category(transfer):
    service, planning, _ = transfer
    plan = preview(service, ics(event()))
    service.apply_import(plan.id, selected(plan))
    changed = preview(service, ics(event(title="원본 수정")))
    assert changed.rows[0].action == "update" and "원본 변경" in changed.rows[0].status
    with pytest.raises(CalendarFileError):
        service.apply_import(changed.id, selected(changed))
    root = planning.repository.records("event")[0]
    category = planning.categories()[0].id
    planning.save(replace(root, title="앱에서 수정", category_id=category))
    conflict = preview(service, ics(event(title="원본 수정")))
    assert "충돌" in conflict.rows[0].status
    service.apply_import(conflict.id, selected(conflict), allow_updates=True)
    saved = planning.repository.records("event")[0]
    assert saved.title == "원본 수정" and saved.category_id == category
    assert not preview(service, ics(event(title="원본 수정"))).rows[0].action


def test_local_delete_tombstone_and_repeat_conversion_are_not_silently_replaced(transfer):
    service, planning, _ = transfer
    plan = preview(service, ics(event()))
    service.apply_import(plan.id, selected(plan))
    occurrence = planning.occurrences(DAY, END, "event")[0]
    planning.delete(occurrence)
    deleted = preview(service, ics(event()))
    assert "삭제됨" in deleted.rows[0].status
    service.apply_import(deleted.id, selected(deleted))
    root = planning.repository.records("event")[0]
    planning.save(replace(root, recurrence="FREQ=DAILY;COUNT=2"))
    repeat = preview(service, ics(event(title="새 제목")))
    assert not repeat.rows[0].action and "반복" in repeat.rows[0].status


@pytest.mark.parametrize("change", ["expired", "backward", "planning", "source"])
def test_preview_expiry_and_database_changes_require_new_review(transfer, change):
    service, planning, clock = transfer
    plan = preview(service, ics(event()))
    if change == "expired":
        clock[0] = 300
    elif change == "backward":
        clock[0] = -1
    elif change == "planning":
        planning.save(Task("별도 변경", DAY))
    else:
        with planning.store.transaction():
            planning.store.connection.execute(
                "INSERT INTO calendar_sources VALUES ('x','다른 출처','now')"
            )
    with pytest.raises(CalendarFileError):
        service.apply_import(plan.id, selected(plan))
    assert not planning.repository.records("event")


def test_batch_failure_rolls_back_records_links_and_notifications(transfer, monkeypatch):
    from PySide6.QtTest import QSignalSpy

    service, planning, _ = transfer
    plan = preview(service, ics(event(uid="a"), event(uid="b", title="다른 항목")))
    before = service.fingerprint()
    signals = QSignalSpy(planning.changed)
    original = planning.repository.save
    calls = []

    def fail_second(record):
        calls.append(record)
        if len(calls) == 2:
            raise sqlite3.OperationalError("QA storage failure")
        return original(record)

    monkeypatch.setattr(planning.repository, "save", fail_second)
    with pytest.raises(sqlite3.OperationalError):
        service.apply_import(plan.id, selected(plan))
    assert service.fingerprint() == before
    assert not planning.repository.records("event")
    assert signals.count() == 0


def test_exact_duplicates_and_time_overlap_have_different_actions(transfer):
    service, planning, _ = transfer
    first = preview(service, ics(event()))
    service.apply_import(first.id, selected(first))
    duplicate = preview(service, ics(event(uid="other")))
    assert not duplicate.rows[0].action
    overlap = preview(service, ics(event(uid="other", title="겹치는 회의")))
    assert overlap.rows[0].action == "add" and "겹침" in overlap.rows[0].status


def test_import_batch_emits_one_refresh_after_success(transfer):
    from PySide6.QtTest import QSignalSpy

    service, planning, _ = transfer
    plan = preview(service, ics(event(uid="a"), event(uid="b", title="별도 일정")))
    signals = QSignalSpy(planning.changed)
    assert service.apply_import(plan.id, selected(plan)) == (2, 0)
    assert signals.count() == 1


def test_export_uid_stability_self_reimport_and_stale_own_file_conflict(transfer):
    service, planning, _ = transfer
    start = datetime(2026, 11, 11, 14, tzinfo=ZONE)
    item_id = planning.save(CalendarEvent("앱 일정", start, start + timedelta(hours=1)))
    plan = service.preview_export(DAY, END, "event")
    raw = serialize_calendar(service.export_entries(plan.id))
    assert service.preview_export(DAY, END, "event").entries[0].uid == plan.entries[0].uid
    assert not preview(service, raw).rows[0].action
    root = planning.repository.get("event", item_id)
    planning.save(replace(root, title="로컬 수정"))
    conflict = preview(service, raw)
    assert conflict.rows[0].action == "update" and "충돌" in conflict.rows[0].status
    occurrence = planning.occurrences(DAY, END, "event")[0]
    planning.delete(occurrence)
    assert "삭제됨" in preview(service, raw).rows[0].status


def test_export_expands_actual_exceptions_and_completed_tasks_without_writing(transfer):
    service, planning, _ = transfer
    planning.save(Task("반복", DAY, recurrence="FREQ=DAILY;COUNT=3"))
    first = planning.occurrences(DAY, END, "task")[0]
    planning.set_completed(first, True)
    second = planning.occurrences(DAY, END, "task")[1]
    planning.delete(second)
    before = service.fingerprint()
    plan = service.preview_export(DAY, END, "task")
    assert len(plan.entries) == 2 and plan.entries[0].record.completed
    assert all(e.record.recurrence is None for e in plan.entries)
    assert service.fingerprint() == before and b"RRULE" not in serialize_calendar(plan.entries)


def test_unrepresentable_old_deadline_is_reported_while_other_export_rows_remain(transfer):
    service, planning, _ = transfer
    planning.save(
        Task("마감이 이미 지난 할 일", DAY, due_at=datetime(2026, 11, 10, 23, tzinfo=ZONE))
    )
    planning.save(Task("정상", DAY))
    before = service.fingerprint()
    plan = service.preview_export(DAY, END, "task")
    assert [entry.record.title for entry in plan.entries] == ["정상"]
    assert plan.notes and "마감" in plan.notes[0]
    assert service.fingerprint() == before


def test_atomic_file_write_cancel_changed_target_and_failed_replace(tmp_path, monkeypatch):
    import desktop_buddy.calendar.file_io as module

    path = tmp_path / "output.ics"
    path.write_bytes(b"old")
    token = file_token(path)
    with pytest.raises(CalendarFileError):
        write_calendar(path, b"new", token, lambda: True)
    assert path.read_bytes() == b"old" and not list(tmp_path.glob("*.tmp"))
    path.write_bytes(b"changed")
    with pytest.raises(CalendarFileError):
        write_calendar(path, b"new", token)
    token = file_token(path)

    def fail(*args):
        raise OSError("QA replace failure")

    monkeypatch.setattr(module.os, "replace", fail)
    with pytest.raises(OSError):
        write_calendar(path, b"new", token)
    assert path.read_bytes() == b"changed" and not list(tmp_path.glob("*.tmp"))


def test_empty_existing_target_can_be_replaced_but_not_imported(tmp_path):
    path = tmp_path / "empty.ics"
    path.touch()
    with pytest.raises(CalendarFileError):
        read_calendar(path)
    write_calendar(path, ics(event()), file_token(path))
    assert len(parsed(read_calendar(path)).entries) == 1


@pytest.mark.parametrize("name", ["data.db", "data.json", "data.ics:stream", "NUL.ics", "CON.ics"])
def test_non_ics_or_stream_target_rejected_without_changes(tmp_path, name):
    with pytest.raises(CalendarFileError):
        file_token(tmp_path / name)
    assert not list(tmp_path.iterdir())


def test_link_path_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "is_symlink", lambda self: True)
    with pytest.raises(CalendarFileError):
        file_token(tmp_path / "linked.ics")


def test_migration_v6_uses_backup_and_preserves_user_data(tmp_path):
    from desktop_buddy.database.migrations import migrate

    path = tmp_path / "legacy.db"
    connection = sqlite3.connect(path)
    migrate(connection, 0)
    connection.execute("DROP TABLE calendar_links")
    connection.execute("DROP TABLE calendar_sources")
    connection.execute("DROP TABLE calendar_identity")
    connection.execute("PRAGMA user_version=6")
    connection.execute("INSERT INTO app_settings VALUES ('character_id','\"usagi\"')")
    connection.commit()
    connection.close()
    store = Store(path)
    try:
        assert store.load_settings().character_id == "usagi"
        assert store.connection.execute("PRAGMA user_version").fetchone()[0] == 7
        backups = list(tmp_path.glob("*.backup.db"))
        assert len(backups) == 1
        with sqlite3.connect(backups[0]) as backup:
            assert backup.execute("PRAGMA user_version").fetchone()[0] == 6
    finally:
        store.close()
