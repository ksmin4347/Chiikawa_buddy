from datetime import UTC, date, datetime, time, timedelta

import pytest
from test_focus import Clock, advance

from desktop_buddy.database.focus_repository import FocusRepository
from desktop_buddy.database.store import Store
from desktop_buddy.models.companion import in_time_window, study_gap
from desktop_buddy.models.planning import CalendarEvent, Task
from desktop_buddy.services.briefing_service import BriefingService
from desktop_buddy.services.companion_service import CompanionService
from desktop_buddy.services.focus_timer import FocusTimerService
from desktop_buddy.services.planning_service import PlanningService
from desktop_buddy.services.settings_service import SettingsService
from desktop_buddy.services.windows_attention import WindowsAttention

DAY = date(2026, 10, 30)


class Attention:
    available = True
    active = False

    def fullscreen(self):
        return self.active


@pytest.fixture
def companion(qapp, tmp_path):
    store = Store(tmp_path / "buddy.db")
    settings = SettingsService(store)
    planning = PlanningService(store)
    clock = Clock(datetime(2026, 10, 30, 0, tzinfo=UTC))
    focus = FocusTimerService(store, settings, planning, clock)
    service = CompanionService(store, settings, focus, clock, Attention())
    yield service, focus, clock
    service.stop()
    focus.timer.stop()
    store.close()


def seed(service, day, seconds=900, completed=True, recorded=True):
    repo = FocusRepository(service.repository.connection)
    start = datetime.combine(day, time(9), service.focus.planning.zone)
    with repo.connection:
        item_id = repo.create(
            "focus", seconds, start, (None, "분류 없음", "#607d8b"), None, None, "", recorded
        )
        repo.progress(item_id, seconds, 0)
        repo.segment(None, item_id, start, start + timedelta(seconds=seconds), seconds)
        repo.finish(item_id, start + timedelta(seconds=seconds), completed, "completed")
    service.poll()
    return item_id


def test_first_user_and_partial_study_are_not_sad(companion):
    service, focus, clock = companion
    assert service.snapshot.state == "idle"
    seed(service, DAY - timedelta(days=10), completed=False)
    seed(service, DAY - timedelta(days=9), seconds=899)
    assert service.snapshot.last_valid_date is None and service.snapshot.state == "idle"


def test_gap_threshold_rest_weekends_and_focus_override(companion):
    service, focus, clock = companion
    seed(service, date(2026, 10, 27))
    assert service.snapshot.gap_days == 3 and service.snapshot.state == "sad"
    focus.start()
    assert service.snapshot.state == "focus"
    focus.stop()
    assert service.snapshot.state == "sad"
    clock.advance(86400)
    service.poll()
    assert service.snapshot.resting and service.snapshot.state == "idle"
    clock.advance(2 * 86400)
    service.poll()
    assert service.snapshot.gap_days == 4


def test_warning_one_day_before_threshold(companion):
    service, focus, clock = companion
    seed(service, DAY - timedelta(days=2))
    assert service.snapshot.state == "worried"
    service.settings.update(emotion_gap_days=5)
    assert service.snapshot.state == "idle"


def test_rest_period_excludes_gap_and_delete_recomputes(companion):
    service, focus, clock = companion
    seed(service, DAY - timedelta(days=4))
    service.add_rest_period(DAY - timedelta(days=3), DAY)
    assert service.snapshot.resting and service.snapshot.gap_days == 0
    period = service.repository.periods()[0]
    service.delete_rest_period(period["id"])
    assert service.snapshot.gap_days == 4 and service.snapshot.state == "sad"
    with pytest.raises(ValueError):
        service.add_rest_period(DAY, DAY - timedelta(days=1))


def test_overlapping_periods_and_weekends_count_once():
    periods = [
        {"start_date": date(2026, 10, 21), "end_date": date(2026, 10, 26)},
        {"start_date": date(2026, 10, 24), "end_date": date(2026, 10, 28)},
    ]
    assert study_gap(date(2026, 10, 20), DAY, (5, 6), periods) == 2
    assert study_gap(date(2026, 10, 20), DAY, tuple(range(7)), []) == 0
    assert study_gap(date(2026, 10, 20), date(2026, 10, 19), (), []) == 0


def test_disabling_emotion_or_recording_removes_gap_expression(companion):
    service, focus, clock = companion
    seed(service, DAY - timedelta(days=4))
    service.settings.update(emotion_enabled=False)
    assert service.snapshot.state == "idle"
    service.settings.update(emotion_enabled=True, record_focus=False)
    assert service.snapshot.state == "idle"


def test_recording_off_uses_temporary_checkpoint_without_statistics(companion):
    service, focus, clock = companion
    service.settings.update(record_focus=False)
    focus.start(minutes=1)
    item_id = focus.session_id
    advance(focus, clock, 30)
    assert focus.repository.session(item_id)["recorded"] == 0
    assert focus.repository.all_total() == 0
    restored = FocusTimerService(focus.store, focus.settings, focus.planning, clock)
    assert restored.elapsed == 30 and not restored.recorded
    restored.resume()
    advance(restored, clock, 30)
    assert not restored.repository.recent(
        clock.now() - timedelta(days=1), clock.now() + timedelta(days=1)
    )
    with pytest.raises(LookupError):
        restored.repository.session(item_id)


@pytest.mark.parametrize("wall", [3600, -3600])
def test_clock_jump_freezes_prompts_until_acknowledged(companion, wall):
    service, focus, clock = companion
    seed(service, DAY - timedelta(days=3))
    clock.advance(1, wall=wall)
    service.poll()
    assert service.snapshot.clock_warning and service.snapshot.state == "idle"
    assert service.quiet()
    service.acknowledge_clock()
    assert not service.snapshot.clock_warning
    assert service.snapshot.state == "sad"


def test_natural_midnight_and_closed_app_clock_rollback(companion):
    service, focus, clock = companion
    clock.advance(86400)
    service.poll()
    assert not service.guard.warning
    clock.advance(1, wall=-3600)
    restored = CompanionService(focus.store, focus.settings, focus, clock, Attention())
    assert restored.guard.warning


def test_future_valid_record_requires_date_confirmation(companion):
    service, focus, clock = companion
    seed(service, DAY + timedelta(days=3))
    assert service.guard.warning and service.snapshot.state == "idle"


def test_emotion_messages_are_infrequent_and_persisted(companion):
    service, focus, clock = companion
    service.can_notify = lambda: True
    messages = []
    service.nudge.connect(messages.append)
    seed(service, DAY - timedelta(days=3))
    service.poll()
    assert len(messages) == 1
    restored = CompanionService(focus.store, focus.settings, focus, clock, Attention())
    restored.can_notify = lambda: True
    restored.nudge.connect(messages.append)
    restored.poll()
    assert len(messages) == 1
    assert service.repository.last_message("emotion") == DAY


def test_sleep_quiet_focus_and_essential_timer_override(companion):
    service, focus, clock = companion
    service.settings.update(sleep_enabled=True, sleep_start="08:00", sleep_end="10:00")
    assert service.snapshot.state == "sleep" and service.quiet()
    focus.start()
    assert service.snapshot.state == "focus"
    service.settings.update(timer_alert_during_quiet=True)
    assert not service.quiet(essential=True)
    focus.stop()
    assert service.snapshot.state == "sleep"
    assert in_time_window(clock.now(), "22:00", "08:00")
    assert not in_time_window(clock.now(), "09:00", "09:00")


def test_fullscreen_heuristic_is_optional_and_reversible(companion):
    service, focus, clock = companion
    service.attention.active = True
    service.poll()
    assert not service.snapshot.fullscreen
    service.settings.update(fullscreen_hide=True)
    assert service.snapshot.fullscreen and service.quiet(essential=True)
    service.attention.active = False
    service.poll()
    assert not service.snapshot.fullscreen


def test_windows_attention_query_errors_and_official_states():
    reader = WindowsAttention()
    for state in (2, 3, 4, 5, 7):

        def query(pointer, value=state):
            pointer._obj.value = value
            return 0

        reader.query = query
        assert reader.fullscreen() == (state in (2, 3, 4))
    reader.query = lambda pointer: -1
    assert not reader.fullscreen() and not reader.available


def briefing_service(service, focus):
    briefing = BriefingService(focus.planning, service.settings, service)
    briefing.can_notify = lambda: True
    return briefing


def test_briefing_exactly_once_after_restart_and_no_old_day_queue(companion):
    service, focus, clock = companion
    briefing = briefing_service(service, focus)
    messages = []
    briefing.ready.connect(messages.append)
    service.settings.update(briefing_enabled=True)
    briefing.poll()
    assert len(messages) == 1
    restored = briefing_service(service, focus)
    restored.ready.connect(messages.append)
    restored.poll()
    assert len(messages) == 1
    clock.advance(3 * 86400)
    service.poll()
    restored.poll()
    assert len(messages) == 2 and messages[-1].day == DAY + timedelta(days=3)


def test_briefing_schedule_defers_during_focus_only_for_current_day(companion):
    service, focus, clock = companion
    briefing = briefing_service(service, focus)
    messages = []
    briefing.ready.connect(messages.append)
    service.settings.update(briefing_on_start=False, briefing_time="10:00", briefing_enabled=True)
    assert messages == []
    focus.start()
    clock.advance(3600)
    service.poll()
    briefing.poll()
    assert messages == []
    focus.stop()
    briefing.poll()
    assert len(messages) == 1


def test_briefing_uses_actual_today_incomplete_due_study_and_future_events(companion):
    service, focus, clock = companion
    planning = focus.planning
    start = datetime.combine(DAY, time(14), planning.zone)
    study_id = planning.categories()[0].id
    planning.save(Task("자료구조", DAY, category_id=study_id, due_at=start))
    planning.save(Task("완료한 일", DAY, completed=True))
    planning.save(Task("어제의 일", DAY - timedelta(days=1)))
    planning.save(CalendarEvent("회의", start, start + timedelta(hours=1)))
    report = briefing_service(service, focus).build()
    assert "일정 1개" in report.summary and "남은 할 일 1개" in report.summary
    assert "14:00 회의" in report.summary
    assert "자료구조" in report.details and "오늘 마감" in report.details
    assert "완료한 일" not in report.details and "이전 미완료 · 1개" in report.details


def test_deferred_startup_brief_does_not_run_early_on_next_day(companion):
    service, focus, clock = companion
    briefing = briefing_service(service, focus)
    messages = []
    briefing.ready.connect(messages.append)
    focus.start()
    service.settings.update(briefing_enabled=True)
    assert messages == []
    clock.advance(23 * 3600)
    service.poll()
    focus.stop()
    briefing.poll()
    assert messages == []
    clock.advance(3600)
    service.poll()
    briefing.poll()
    assert len(messages) == 1 and messages[0].day == DAY + timedelta(days=1)


def test_manual_brief_counts_as_today_seen_without_restricting_explicit_review(companion):
    service, focus, clock = companion
    briefing = briefing_service(service, focus)
    assert briefing.manual().day == DAY
    assert briefing.manual().day == DAY
    messages = []
    briefing.ready.connect(messages.append)
    service.settings.update(briefing_enabled=True)
    assert messages == []


def test_schema3_migration_backs_up_focus_records(qapp, tmp_path):
    import sqlite3

    from desktop_buddy.database.migrations import SCHEMA_VERSION

    path = tmp_path / "buddy.db"
    store = Store(path)
    repository = FocusRepository(store.connection)
    now = datetime(2026, 10, 29, tzinfo=UTC)
    with store.connection:
        item_id = repository.create(
            "focus", 900, now, (None, "공부", "#607d8b"), None, None, "보존할 기록"
        )
        repository.progress(item_id, 900, 0)
        repository.finish(item_id, now + timedelta(minutes=15), True, "completed")
        for table in ("rest_periods", "companion_state", "companion_messages"):
            store.connection.execute(f"DROP TABLE {table}")
        store.connection.execute("ALTER TABLE focus_sessions DROP COLUMN recorded")
        store.connection.execute("PRAGMA user_version=3")
    store.close()
    restored = Store(path)
    assert restored.connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    assert FocusRepository(restored.connection).session(item_id)["recorded"] == 1
    assert FocusRepository(restored.connection).session(item_id)["task_title"] == "보존할 기록"
    backup = list(tmp_path.glob("*.backup.db"))
    assert len(backup) == 1
    old = sqlite3.connect(backup[0])
    assert old.execute("PRAGMA user_version").fetchone()[0] == 3
    old.close()
    restored.close()


def test_valid_completion_clears_gap_and_deleting_history_restores_first_user(companion):
    service, focus, clock = companion
    old_id = seed(service, DAY - timedelta(days=4))
    assert service.snapshot.state == "sad"
    clock.advance(3600)
    latest_id = seed(service, DAY, seconds=900)
    assert service.snapshot.state == "idle" and service.snapshot.gap_days == 0
    with service.repository.connection:
        focus.repository.delete(old_id)
        focus.repository.delete(latest_id)
    service.poll()
    assert service.snapshot.last_valid_date is None and service.snapshot.state == "idle"
