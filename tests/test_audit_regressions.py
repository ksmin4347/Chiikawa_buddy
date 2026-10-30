# ruff: noqa: F811 -- Imported pytest fixtures are named by test arguments.
from dataclasses import replace
from datetime import timedelta

from test_companion import companion  # noqa: F401 -- pytest fixture
from test_companion_ui import buddy as audit_buddy  # noqa: F401 -- pytest fixture
from test_focus import advance

from desktop_buddy.models.planning import Task


def test_custom_duration_survives_unrelated_setting_changes(audit_buddy):
    buddy, clock = audit_buddy
    page = buddy.manager.focus_page
    page.minutes.setValue(47)
    buddy.settings.update(x=53, y=61)
    assert page.minutes.value() == 47
    buddy.settings.update(theme="dark")
    assert page.minutes.value() == 47


def test_explicit_no_category_is_honored_when_linking_task(audit_buddy):
    buddy, clock = audit_buddy
    day = buddy.planning.today()
    category_id = buddy.planning.categories()[0].id
    buddy.planning.save(Task("분류를 직접 정하는 공부", day, category_id=category_id))
    page = buddy.manager.focus_page
    page.task.setCurrentIndex(1)
    page.category.setCurrentIndex(0)
    page.start()
    row = buddy.focus_timer.repository.session(buddy.focus_timer.session_id)
    assert row["task_title"] == "분류를 직접 정하는 공부"
    assert row["category_id"] is None


def test_linked_repeat_uses_instance_category(companion):
    service, focus, clock = companion
    planning = focus.planning
    day = clock.now().astimezone(planning.zone).date()
    first, second = planning.categories()[:2]
    planning.save(Task("반복 복습", day, category_id=first.id, recurrence="FREQ=DAILY;COUNT=2"))
    occurrence = planning.occurrences(day, day + timedelta(days=2), "task")[1]
    planning.edit(occurrence, replace(occurrence.record, category_id=second.id), "one")
    updated = planning.occurrences(day, day + timedelta(days=2), "task")[1]
    focus.start(task=updated)
    assert focus.repository.session(focus.session_id)["category_id"] == second.id


def test_renamed_category_matches_summary_and_record_list(audit_buddy):
    buddy, clock = audit_buddy
    category = buddy.planning.categories()[0]
    buddy.focus_timer.start(category_id=category.id)
    advance(buddy.focus_timer, clock, 5)
    buddy.focus_timer.stop()
    buddy.planning.save_category("새 분류 이름", category.color, category.id)
    day = clock.now().astimezone(buddy.planning.zone).date()
    values = buddy.statistics.totals(day, day + timedelta(days=1))
    assert values["categories"] == {"새 분류 이름": 5}
    assert values["records"][0]["category_name"] == "새 분류 이름"


def test_clock_rollback_across_local_midnight_is_guarded(companion):
    service, focus, clock = companion
    clock.advance(15 * 3600 + 30)
    service.poll()
    assert not service.guard.warning
    clock.advance(1, wall=-61)
    service.poll()
    assert service.guard.warning
    changes = service.repository.connection.total_changes
    service.poll()
    assert service.repository.connection.total_changes == changes


def test_home_and_today_follow_midnight_without_reopening(audit_buddy, monkeypatch):
    from datetime import datetime

    import desktop_buddy.ui.management as management

    buddy, clock = audit_buddy

    class ClockDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            value = clock.now()
            return value.astimezone(tz) if tz is not None else value

    monkeypatch.setattr(management, "datetime", ClockDateTime)
    monkeypatch.setattr(
        buddy.planning, "today", lambda: clock.now().astimezone(buddy.planning.zone).date()
    )
    buddy.manager.open_page()
    buddy.focus_timer.tick()
    clock.advance(86400)
    buddy.focus_timer.tick()
    day = buddy.planning.today()
    assert buddy.manager.home_date.text().startswith(f"{day.month}월 {day.day}일")
    assert buddy.manager.today_page.day == day


def test_custom_duration_is_preserved_when_defaults_change(audit_buddy):
    buddy, clock = audit_buddy
    page = buddy.manager.focus_page
    page.minutes.setValue(47)
    buddy.settings.update(focus_minutes=30)
    assert page.minutes.value() == 47
    page.minutes.setValue(30)
    buddy.settings.update(focus_minutes=20)
    assert page.minutes.value() == 20


def test_user_selected_past_day_is_not_changed_at_midnight(audit_buddy, monkeypatch):
    from PySide6.QtCore import QDate

    buddy, clock = audit_buddy
    monkeypatch.setattr(
        buddy.planning, "today", lambda: clock.now().astimezone(buddy.planning.zone).date()
    )
    buddy.focus_timer.tick()
    past = buddy.planning.today() - timedelta(days=7)
    buddy.manager.today_page.date_edit.setDate(QDate(past))
    clock.advance(86400)
    buddy.focus_timer.tick()
    assert buddy.manager.today_page.day == past
    buddy.shutdown()
    assert not buddy.manager.clock_timer.isActive()


def test_midnight_checkpoint_guards_rollback_after_restart(companion):
    from desktop_buddy.services.local_day_guard import LocalDayGuard

    service, focus, clock = companion
    clock.advance(15 * 3600 + 30)
    service.poll()
    clock.advance(1, wall=-61)
    restored = LocalDayGuard(service.repository, clock, focus.planning.zone)
    assert restored.warning


def test_abrupt_process_exit_preserves_checkpoint_and_releases_lock(qapp, tmp_path):
    import sys
    from pathlib import Path

    from PySide6.QtCore import QProcess
    from test_focus import Clock

    from desktop_buddy.database.store import Store
    from desktop_buddy.services.focus_timer import FocusTimerService
    from desktop_buddy.services.planning_service import PlanningService
    from desktop_buddy.services.settings_service import SettingsService
    from desktop_buddy.services.single_instance import SingleInstance

    source = Path(__file__).resolve().parents[1] / "src"
    code = f"""
import os, sys
from pathlib import Path
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
sys.path.insert(0,{str(source)!r})
from PySide6.QtCore import QCoreApplication
from desktop_buddy.database.store import Store
from desktop_buddy.services.single_instance import SingleInstance
from desktop_buddy.services.settings_service import SettingsService
from desktop_buddy.services.planning_service import PlanningService
from desktop_buddy.services.focus_timer import FocusTimerService
app=QCoreApplication([])
root=Path(sys.argv[1])
guard=SingleInstance(root)
assert guard.acquire()
store=Store(root/'buddy.db')
clock=SimpleNamespace(seconds=0)
clock.monotonic=lambda:clock.seconds
clock.now=lambda:datetime(2026,10,30,tzinfo=UTC)+timedelta(seconds=clock.seconds)
focus=FocusTimerService(store,SettingsService(store),PlanningService(store),clock)
focus.start()
clock.seconds=5
focus.tick()
clock.seconds=7
focus.tick()
os._exit(27)
"""
    child = QProcess()
    child.start(sys.executable, ["-c", code, str(tmp_path)])
    assert child.waitForStarted(3000)
    assert child.waitForFinished(10000)
    assert child.exitCode() == 27
    guard = SingleInstance(tmp_path)
    assert guard.acquire()
    store = Store(tmp_path / "buddy.db")
    clock = Clock()
    restored = FocusTimerService(store, SettingsService(store), PlanningService(store), clock)
    assert restored.status == "paused"
    assert restored.elapsed == 5
    assert restored.repository.all_total() == 5
    guard.close()
    store.close()
