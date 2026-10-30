import sqlite3
from dataclasses import replace
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from desktop_buddy.database.migrations import SCHEMA_VERSION
from desktop_buddy.database.store import Store
from desktop_buddy.models.planning import CalendarEvent, Task
from desktop_buddy.services.planning_service import PlanningService

ZONE = ZoneInfo("Asia/Seoul")
DAY = date(2026, 10, 26)


def at(day=DAY, hour=14, minute=0):
    return datetime.combine(day, time(hour, minute), ZONE)


@pytest.fixture
def planner(qapp, tmp_path):
    store = Store(tmp_path / "buddy.db")
    service = PlanningService(store)
    yield service
    store.close()


def event(**changes):
    return replace(CalendarEvent("공부 모임", at(), at(hour=15)), **changes)


def test_migrate_v1_preserves_settings_and_backup(tmp_path):
    path = tmp_path / "buddy.db"
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE app_settings (setting_key TEXT PRIMARY KEY, setting_value TEXT NOT NULL)"
    )
    connection.execute("INSERT INTO app_settings VALUES (?,?)", ("character_name", '"예전 친구"'))
    connection.execute("PRAGMA user_version=1")
    connection.commit()
    connection.close()
    store = Store(path)
    assert store.load_settings().character_name == "예전 친구"
    assert store.connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    assert store.connection.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 0
    backup = list(tmp_path.glob("*.backup.db"))
    assert len(backup) == 1
    old = sqlite3.connect(backup[0])
    assert old.execute("PRAGMA user_version").fetchone()[0] == 1
    old.close()
    store.close()


def test_migration_failure_rolls_back_ddl(tmp_path, monkeypatch):
    import desktop_buddy.database.store as module

    path = tmp_path / "buddy.db"
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE app_settings(setting_key TEXT PRIMARY KEY, setting_value TEXT NOT NULL)"
    )
    connection.execute("PRAGMA user_version=1")
    connection.close()

    def fail(connection, old_version):
        connection.execute("CREATE TABLE incomplete_migration(id INTEGER)")
        raise RuntimeError("failure")

    monkeypatch.setattr(module, "migrate", fail)
    with pytest.raises(RuntimeError):
        Store(path)
    restored = sqlite3.connect(path)
    assert restored.execute("PRAGMA user_version").fetchone()[0] == 1
    assert not restored.execute(
        "SELECT name FROM sqlite_master WHERE name='incomplete_migration'"
    ).fetchall()
    restored.close()


def test_task_crud_move_completion_and_restart(planner):
    item_id = planner.save(Task("  자료구조 공부  ", DAY))
    occurrence = planner.occurrences(DAY, DAY + timedelta(days=1), "task")[0]
    assert occurrence.title == "자료구조 공부"
    planner.set_completed(occurrence, True)
    assert planner.occurrences(DAY, DAY + timedelta(days=1))[0].completed
    root = planner.repository.get("task", item_id)
    planner.edit(
        occurrence, replace(root, scheduled_date=DAY + timedelta(days=1), description="복습")
    )
    assert not planner.occurrences(DAY, DAY + timedelta(days=1))
    moved = planner.occurrences(DAY + timedelta(days=1), DAY + timedelta(days=2))[0]
    assert moved.completed
    planner.set_completed(moved, False)
    assert len(planner.overdue_tasks(DAY + timedelta(days=2))) == 1
    planner.delete(moved)
    assert not planner.repository.records("task")


def test_categories_update_delete_without_deleting_items(planner):
    category_id = planner.save_category("개인", "#37658a")
    planner.save(Task("할 일", DAY, category_id=category_id))
    planner.save(event(category_id=category_id))
    planner.save_category("개인 공부", "#567f43", category_id)
    assert all(
        value.category.name == "개인 공부"
        for value in planner.occurrences(DAY, DAY + timedelta(days=1))
    )
    planner.delete_category(category_id)
    items = planner.occurrences(DAY, DAY + timedelta(days=1))
    assert len(items) == 2
    assert all(value.category is None for value in items)


def test_weekly_tasks_have_independent_completion(planner):
    planner.save(Task("복습", DAY, recurrence="FREQ=WEEKLY;BYDAY=MO,WE;COUNT=4"))
    items = planner.occurrences(DAY, DAY + timedelta(days=14), "task")
    assert [item.start.date() for item in items] == [
        DAY,
        DAY + timedelta(days=2),
        DAY + timedelta(days=7),
        DAY + timedelta(days=9),
    ]
    planner.set_completed(items[1], True)
    assert [
        item.completed for item in planner.occurrences(DAY, DAY + timedelta(days=14), "task")
    ] == [False, True, False, False]
    planner.set_completed(items[1], False)
    assert not any(
        item.completed for item in planner.occurrences(DAY, DAY + timedelta(days=14), "task")
    )


def test_month_end_and_leap_year(planner):
    jan = date(2026, 1, 31)
    planner.save(event(start_at=at(jan), end_at=at(jan, 15), recurrence="FREQ=MONTHLY;COUNT=3"))
    assert [item.start.month for item in planner.occurrences(jan, date(2026, 6, 1))] == [1, 3, 5]
    leap = date(2024, 2, 29)
    planner.save(
        event(
            title="윤년", start_at=at(leap), end_at=at(leap, 15), recurrence="FREQ=YEARLY;COUNT=2"
        )
    )
    items = planner.occurrences(date(2028, 1, 1), date(2029, 1, 1))
    assert len(items) == 1 and items[0].start.date() == date(2028, 2, 29)


def test_move_one_instance_to_another_month_without_duplicate(planner):
    planner.save(event(recurrence="FREQ=WEEKLY;COUNT=3"))
    selected = planner.occurrences(DAY, DAY + timedelta(days=1))[0]
    target = date(2026, 11, 12)
    planner.edit(
        selected,
        replace(
            planner.draft(selected, "one"),
            title="이날만 변경",
            start_at=at(target, 16),
            end_at=at(target, 17),
        ),
    )
    assert not planner.occurrences(DAY, DAY + timedelta(days=1))
    moved = planner.occurrences(target, target + timedelta(days=1))
    assert len(moved) == 1 and moved[0].key == DAY.isoformat()
    assert moved[0].title == "이날만 변경"
    assert len(planner.occurrences(DAY, DAY + timedelta(days=30))) == 3
    planner.delete(moved[0], "one")
    assert not planner.occurrences(target, target + timedelta(days=1))


def test_following_edit_preserves_count_exceptions_and_completed_days(planner):
    planner.save(Task("원래", DAY, recurrence="FREQ=DAILY;COUNT=5"))
    items = planner.occurrences(DAY, DAY + timedelta(days=5), "task")
    planner.delete(items[3], "one")
    planner.set_completed(items[4], True)
    draft = planner.draft(items[2], "following")
    assert "COUNT=3" in draft.recurrence
    planner.edit(items[2], replace(draft, title="이후 변경"), "following")
    after = planner.occurrences(DAY, DAY + timedelta(days=10), "task")
    assert [value.title for value in after] == ["원래", "원래", "이후 변경", "이후 변경"]
    assert after[-1].completed
    assert len(planner.repository.records("task")) == 2


def test_following_delete_preserves_past(planner):
    planner.save(event(recurrence="FREQ=DAILY;COUNT=5"))
    items = planner.occurrences(DAY, DAY + timedelta(days=5))
    planner.delete(items[2], "following")
    assert len(planner.occurrences(DAY, DAY + timedelta(days=10))) == 2


def test_all_edit_and_delete(planner):
    planner.save(event(recurrence="FREQ=DAILY;COUNT=3"))
    selected = planner.occurrences(DAY, DAY + timedelta(days=3))[1]
    planner.edit(selected, replace(planner.draft(selected, "all"), title="전체 변경"), "all")
    assert {item.title for item in planner.occurrences(DAY, DAY + timedelta(days=3))} == {
        "전체 변경"
    }
    planner.delete(selected, "all")
    assert not planner.repository.records("event")


def test_cross_midnight_and_exclusive_all_day_end(planner):
    planner.save(event(start_at=at(hour=23), end_at=at(DAY + timedelta(days=1), 1)))
    assert len(planner.occurrences(DAY, DAY + timedelta(days=1))) == 1
    assert len(planner.occurrences(DAY + timedelta(days=1), DAY + timedelta(days=2))) == 1
    planner.save(
        event(
            title="종일", start_at=at(hour=0), end_at=at(DAY + timedelta(days=2), 0), all_day=True
        )
    )
    assert len(planner.occurrences(DAY + timedelta(days=1), DAY + timedelta(days=2))) == 2
    assert not planner.occurrences(DAY + timedelta(days=2), DAY + timedelta(days=3))


def test_dst_preserves_local_wall_clock_and_skips_nonexistent_time(qapp, tmp_path):
    store = Store(tmp_path / "ny.db")
    service = PlanningService(store, "America/New_York")
    zone = ZoneInfo("America/New_York")
    start = datetime(2026, 3, 7, 2, 30, tzinfo=zone)
    service.save(
        CalendarEvent(
            "새벽",
            start,
            start + timedelta(hours=1),
            recurrence="FREQ=DAILY;COUNT=3",
            timezone="America/New_York",
        )
    )
    items = service.occurrences(date(2026, 3, 7), date(2026, 3, 11))
    assert [item.start.day for item in items] == [7, 9, 10]
    assert all(item.start.hour == 2 for item in items)
    store.close()


@pytest.mark.parametrize(
    "record",
    [
        Task("", DAY),
        Task("a", DAY, priority=8),
        Task("a", DAY, reminder_minutes=5),
        event(end_at=at(hour=13)),
        event(recurrence="FREQ=SECONDLY"),
        event(recurrence="FREQ=DAILY;COUNT=3;UNTIL=20270101T000000Z"),
    ],
)
def test_invalid_input_does_not_write(planner, record):
    with pytest.raises(ValueError):
        planner.save(record)
    assert not planner.repository.records("task")
    assert not planner.repository.records("event")


def test_reminders_use_due_time_and_edited_deadline(planner):
    planner.save(
        Task("마감", DAY, due_at=at(hour=18), reminder_minutes=10, recurrence="FREQ=DAILY;COUNT=2")
    )
    items = planner.occurrences(DAY, DAY + timedelta(days=2), "task")
    future = DAY + timedelta(days=10)
    planner.edit(
        items[1],
        replace(planner.draft(items[1], "one"), due_at=at(future, 18), reminder_minutes=30),
    )
    first = planner.reminders_between(at(hour=17, minute=49), at(hour=17, minute=51))
    assert len(first) == 1 and first[0].occurrence.key == DAY.isoformat()
    moved = planner.reminders_between(at(future, 17, 29), at(future, 17, 31))
    assert len(moved) == 1 and moved[0].occurrence.key == (DAY + timedelta(days=1)).isoformat()
    planner.set_completed(items[1], True)
    assert not planner.reminders_between(at(future, 17, 29), at(future, 17, 31))


def test_stopping_repetition_preserves_modified_instances_and_completed_history(planner):
    planner.save(Task("반복", DAY, recurrence="FREQ=DAILY;COUNT=5"))
    items = planner.occurrences(DAY, DAY + timedelta(days=5), "task")
    planner.set_completed(items[1], True)
    planner.edit(items[3], replace(planner.draft(items[3], "one"), title="개별 수정"))
    planner.edit(items[0], replace(planner.draft(items[0], "all"), recurrence=None), "all")
    after = planner.occurrences(DAY, DAY + timedelta(days=6), "task")
    assert len(after) == 3
    assert any(item.title == "개별 수정" for item in after)
    assert sum(item.completed for item in after) == 1
    assert all(not item.repeated for item in after)


def test_stopping_following_repetition_preserves_future_overrides(planner):
    planner.save(event(recurrence="FREQ=DAILY;COUNT=5"))
    items = planner.occurrences(DAY, DAY + timedelta(days=5))
    planner.edit(items[4], replace(planner.draft(items[4], "one"), title="남길 개별 일정"))
    planner.edit(
        items[2], replace(planner.draft(items[2], "following"), recurrence=None), "following"
    )
    after = planner.occurrences(DAY, DAY + timedelta(days=7))
    assert len(after) == 4
    assert after[-1].title == "남길 개별 일정"


def test_overdue_includes_instance_moved_before_series_start(planner):
    planner.save(Task("반복", DAY, recurrence="FREQ=WEEKLY;COUNT=3"))
    first = planner.occurrences(DAY, DAY + timedelta(days=1), "task")[0]
    earlier = DAY - timedelta(days=10)
    planner.edit(first, replace(planner.draft(first, "one"), scheduled_date=earlier))
    assert len(planner.overdue_tasks(DAY - timedelta(days=1))) == 1


def test_ids_are_not_reused_for_new_tasks_or_events(planner):
    first = planner.save(Task("기존", DAY))
    occurrence = planner.occurrences(DAY, DAY + timedelta(days=1))[0]
    planner.delete(occurrence, "all")
    second = planner.save(Task("새 항목", DAY))
    assert second > first


def test_split_keeps_prior_notification_claim(planner):
    planner.save(event(recurrence="FREQ=DAILY;COUNT=4", reminder_minutes=0))
    items = planner.occurrences(DAY, DAY + timedelta(days=4))
    target = at(DAY + timedelta(days=2))
    reminder = planner.reminders_between(target - timedelta(seconds=1), target)[0]
    with planner.store.connection:
        assert planner.repository.claim_notification(reminder.key, target.isoformat(), "shown")
    planner.edit(
        items[2], replace(planner.draft(items[2], "following"), title="이후 수정"), "following"
    )
    after = planner.reminders_between(target - timedelta(seconds=1), target)[0]
    with planner.store.connection:
        assert not planner.repository.claim_notification(after.key, target.isoformat(), "shown")


def test_far_future_query_keeps_interval_phase_and_missing_month_days(planner):
    from desktop_buddy.calendar.recurrence import starts_between

    start = datetime(2000, 1, 31, 14, tzinfo=ZONE)
    lower = datetime(2099, 1, 1, tzinfo=ZONE)
    upper = datetime(2100, 1, 1, tzinfo=ZONE)
    monthly = starts_between("FREQ=MONTHLY;INTERVAL=2", start, lower, upper)
    assert all(value.month in (1, 3, 5, 7, 9, 11) and value.day == 31 for value in monthly)
    daily = starts_between("FREQ=DAILY;INTERVAL=3", start, lower, upper)
    assert all((value.date() - start.date()).days % 3 == 0 for value in daily)


def test_dst_gap_does_not_consume_count_and_split_count():
    from desktop_buddy.calendar.recurrence import remaining_rule, starts_between

    zone = ZoneInfo("America/New_York")
    start = datetime(2026, 3, 7, 2, 30, tzinfo=zone)
    rule = "FREQ=DAILY;COUNT=3"
    values = starts_between(rule, start, start, start + timedelta(days=5))
    assert [value.day for value in values] == [7, 9, 10]
    assert "COUNT=1" in remaining_rule(rule, start, date(2026, 3, 10))


def test_failed_following_edit_rolls_back_both_series(planner, monkeypatch):
    planner.save(event(recurrence="FREQ=DAILY;COUNT=4"))
    selected = planner.occurrences(DAY, DAY + timedelta(days=4))[2]
    original_save = planner.repository.save

    def fail_new(record):
        if record.id is None:
            raise OSError("disk full")
        return original_save(record)

    monkeypatch.setattr(planner.repository, "save", fail_new)
    with pytest.raises(OSError):
        planner.edit(
            selected, replace(planner.draft(selected, "following"), title="변경"), "following"
        )
    assert len(planner.occurrences(DAY, DAY + timedelta(days=5))) == 4
    assert len(planner.repository.records("event")) == 1


def test_tasks_events_exceptions_and_completion_survive_database_reopen(qapp, tmp_path):
    path = tmp_path / "reopen.db"
    first = Store(path)
    service = PlanningService(first)
    category = service.save_category("저장 확인", "#637d51")
    service.save(Task("반복 할 일", DAY, recurrence="FREQ=DAILY;COUNT=3", category_id=category))
    service.save(event(category_id=category))
    tasks = service.occurrences(DAY, DAY + timedelta(days=3), "task")
    service.set_completed(tasks[0], True)
    service.edit(tasks[1], replace(service.draft(tasks[1], "one"), title="이날만 바꿈"))
    service.delete(tasks[2], "one")
    first.close()
    reopened = Store(path)
    restored = PlanningService(reopened)
    tasks = restored.occurrences(DAY, DAY + timedelta(days=3), "task")
    assert [task.title for task in tasks] == ["반복 할 일", "이날만 바꿈"]
    assert [task.completed for task in tasks] == [True, False]
    assert all(task.category.name == "저장 확인" for task in tasks)
    assert len(restored.occurrences(DAY, DAY + timedelta(days=1), "event")) == 1
    reopened.close()
