import sqlite3
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from desktop_buddy.database.migrations import SCHEMA_VERSION
from desktop_buddy.database.store import Store
from desktop_buddy.models.planning import Task
from desktop_buddy.services.focus_timer import FocusTimerService
from desktop_buddy.services.planning_service import PlanningService
from desktop_buddy.services.settings_service import SettingsService
from desktop_buddy.services.study_statistics import StudyStatistics, split_segment


class Clock:
    def __init__(self, now=None):
        self.wall = now or datetime(2026, 10, 28, 14, tzinfo=UTC)
        self.mono = 0.0

    def now(self):
        return self.wall

    def monotonic(self):
        return self.mono

    def advance(self, seconds, wall=None):
        self.mono += seconds
        self.wall += timedelta(seconds=seconds if wall is None else wall)


def advance(timer, clock, seconds):
    while seconds > 0:
        step = min(seconds, 5)
        clock.advance(step)
        timer.tick()
        seconds -= step


@pytest.fixture
def focus(qapp, tmp_path):
    store = Store(tmp_path / "buddy.db")
    planning = PlanningService(store)
    settings = SettingsService(store)
    clock = Clock()
    timer = FocusTimerService(store, settings, planning, clock)
    stats = StudyStatistics(store, planning, timer)
    yield timer, clock, stats
    timer.timer.stop()
    store.close()


def test_pause_stop_and_continuous_segments(focus):
    timer, clock, stats = focus
    timer.start(minutes=2)
    advance(timer, clock, 15)
    timer.pause()
    advance(timer, clock, 30)
    timer.resume()
    advance(timer, clock, 10)
    timer.stop()
    row = stats.repository.session(1)
    assert row["active_seconds"] == 25
    assert row["paused_seconds"] == 30
    assert row["interrupted"] and not row["completed"]
    assert stats.all_total() == 25
    assert len(stats.repository.segments_between(clock.now() - timedelta(days=1), clock.now())) == 2


def test_completion_once_break_excluded_and_next_opt_in(focus):
    timer, clock, stats = focus
    events = []
    timer.phase_finished.connect(events.append)
    timer.start(minutes=1)
    advance(timer, clock, 61)
    assert len(events) == 1 and timer.status == "ready"
    assert timer.next_phase == "short_break"
    assert stats.all_total() == 60
    timer.start_next()
    advance(timer, clock, 10)
    timer.stop()
    assert stats.all_total() == 60
    totals = stats.totals(date(2026, 10, 28), date(2026, 10, 30))
    assert totals["completed"] == 1 and totals["average"] == 60


def test_auto_sequence_long_break_and_stop_never_restarts(focus):
    timer, clock, stats = focus
    timer.settings.update(
        focus_minutes=1, break_minutes=1, long_break_interval=2, auto_next_phase=True
    )
    timer.start()
    advance(timer, clock, 60)
    assert timer.phase == "short_break" and timer.status == "running"
    advance(timer, clock, 60)
    assert timer.phase == "focus"
    advance(timer, clock, 60)
    assert timer.phase == "long_break" and timer.completed_rounds == 2
    timer.reset()
    assert timer.status == "idle" and timer.completed_rounds == 0
    assert stats.all_total() == 120


@pytest.mark.parametrize(
    "seconds,wall,reason",
    [(3600, None, "long_gap"), (1, 3601, "clock_changed"), (1, -1, "clock_changed")],
)
def test_sleep_and_clock_changes_do_not_credit_gap(focus, seconds, wall, reason):
    timer, clock, stats = focus
    timer.start()
    advance(timer, clock, 5)
    clock.advance(seconds, wall)
    timer.tick()
    assert timer.status == "paused" and timer.reason == reason
    assert timer.elapsed == 5 and stats.all_total() == 5
    timer.resume()
    advance(timer, clock, 5)
    timer.stop()
    assert stats.all_total() == 10


def test_crash_recovery_keeps_checkpoint_and_excludes_downtime(focus):
    timer, clock, stats = focus
    timer.start()
    advance(timer, clock, 7)
    clock.advance(3600)
    restored = FocusTimerService(timer.store, timer.settings, timer.planning, clock)
    assert restored.status == "paused" and restored.reason == "recovered"
    assert restored.elapsed == 5
    restored.resume()
    advance(restored, clock, 5)
    restored.stop()
    assert stats.all_total() == 10


def test_graceful_shutdown_retains_last_seconds(focus):
    timer, clock, stats = focus
    timer.start()
    advance(timer, clock, 3)
    timer.shutdown()
    clock.advance(3600)
    restored = FocusTimerService(timer.store, timer.settings, timer.planning, clock)
    assert restored.status == "paused" and restored.elapsed == 3
    assert stats.all_total() == 3


def test_storage_error_pauses_and_can_retry(focus, monkeypatch):
    timer, clock, stats = focus
    timer.start()
    original = timer.repository.save_state
    monkeypatch.setattr(
        timer.repository,
        "save_state",
        lambda state: (_ for _ in ()).throw(sqlite3.OperationalError("disk full")),
    )
    errors = []
    timer.error.connect(errors.append)
    advance(timer, clock, 6)
    assert timer.status == "paused" and len(errors) == 1 and stats.all_total() == 0
    monkeypatch.setattr(timer.repository, "save_state", original)
    timer.resume()
    advance(timer, clock, 5)
    timer.stop()
    assert stats.all_total() == 10


def test_local_midnight_pauses_and_stats_delete(focus):
    timer, clock, stats = focus
    clock.wall = datetime(2026, 10, 28, 14, 59, 50, tzinfo=UTC)
    timer.start()
    advance(timer, clock, 20)
    timer.pause()
    advance(timer, clock, 60)
    timer.resume()
    advance(timer, clock, 10)
    timer.stop()
    assert stats.totals(date(2026, 10, 28), date(2026, 10, 29))["seconds"] == 10
    assert stats.totals(date(2026, 10, 29), date(2026, 10, 30))["seconds"] == 20
    stats.delete_record(1)
    assert stats.all_total() == 0
    assert not timer.store.connection.execute("SELECT * FROM focus_segments").fetchall()


def test_category_edit_and_deleted_task_keep_history(focus):
    timer, clock, stats = focus
    planning = timer.planning
    day = planning.today()
    category_id = planning.save_category("알고리즘", "#567f43")
    planning.save(Task("연결한 할 일", day, category_id=category_id))
    task = planning.occurrences(day, day + timedelta(days=1), "task")[0]
    timer.start(task=task)
    with pytest.raises(ValueError):
        stats.delete_record(1)
    advance(timer, clock, 10)
    timer.stop()
    planning.delete(task)
    planning.delete_category(category_id)
    assert stats.repository.session(1)["task_title"] == "연결한 할 일"
    assert stats.repository.session(1)["category_name"] == "알고리즘"
    stats.change_category(1, None)
    assert stats.repository.session(1)["category_name"] == "분류 없음"
    assert stats.all_total() == 10


def test_dst_day_is_23_hours():
    zone = ZoneInfo("America/New_York")
    start = datetime(2026, 3, 8, tzinfo=zone)
    end = datetime(2026, 3, 9, tzinfo=zone)
    assert split_segment(start, end, 23 * 3600, zone) == {date(2026, 3, 8): 23 * 3600}


def test_v2_migration_backs_up_and_preserves_plans(qapp, tmp_path):
    path = tmp_path / "buddy.db"
    store = Store(path)
    PlanningService(store).save(Task("이전 할 일", date(2026, 10, 28)))
    for table in (
        "companion_messages",
        "companion_state",
        "rest_periods",
        "focus_segments",
        "focus_sessions",
        "timer_state",
    ):
        store.connection.execute(f"DROP TABLE {table}")
    store.connection.execute("PRAGMA user_version=2")
    store.connection.commit()
    store.close()
    reopened = Store(path)
    assert len(PlanningService(reopened).repository.records("task")) == 1
    assert reopened.connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    backups = list(tmp_path.glob("*.backup.db"))
    assert len(backups) == 1
    old = sqlite3.connect(backups[0])
    assert old.execute("PRAGMA user_version").fetchone()[0] == 2
    old.close()
    reopened.close()


def test_more_than_100_sessions_have_correct_average(focus):
    timer, clock, stats = focus
    for _ in range(101):
        timer.start(minutes=1 / 60)
        advance(timer, clock, 1)
    timer.start(minutes=2 / 60)
    advance(timer, clock, 2)
    values = stats.totals(date(2026, 10, 28), date(2026, 10, 30))
    assert values["completed"] == 102
    assert values["average"] == pytest.approx(103 / 102)
    assert len(values["records"]) == 100


def test_corrupt_checkpoint_interrupts_orphan_without_crediting_downtime(focus):
    timer, clock, stats = focus
    timer.start()
    advance(timer, clock, 5)
    with timer.store.connection:
        timer.store.connection.execute("UPDATE timer_state SET payload='invalid'")
    clock.advance(3600)
    restored = FocusTimerService(timer.store, timer.settings, timer.planning, clock)
    assert restored.status == "idle"
    assert stats.repository.session(1)["interrupted"]
    assert stats.all_total() == 5


def test_skip_break_keeps_task_link_and_reset_keeps_history(focus):
    timer, clock, stats = focus
    planning = timer.planning
    day = planning.today()
    planning.save(Task("복습", day))
    task = planning.occurrences(day, day + timedelta(days=1), "task")[0]
    timer.start(minutes=1 / 60, task=task)
    advance(timer, clock, 1)
    timer.skip_break()
    assert timer.status == "running" and timer.phase == "focus"
    assert timer.task_title == "복습" and timer.completed_rounds == 1
    timer.reset()
    assert stats.all_total() == 1


def test_ready_checkpoint_restores_completed_progress(focus):
    timer, clock, stats = focus
    timer.start(minutes=1 / 60)
    advance(timer, clock, 1)
    restored = FocusTimerService(timer.store, timer.settings, timer.planning, clock)
    assert restored.status == "ready" and restored.next_phase == "short_break"
    assert restored.snapshot.remaining_seconds == 0
