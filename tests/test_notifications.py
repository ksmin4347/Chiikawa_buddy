from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from PySide6.QtTest import QSignalSpy

from desktop_buddy.database.store import Store
from desktop_buddy.models.planning import CalendarEvent
from desktop_buddy.services.notification_service import NotificationService
from desktop_buddy.services.planning_service import PlanningService
from desktop_buddy.services.settings_service import SettingsService

ZONE = ZoneInfo("Asia/Seoul")


def services(tmp_path):
    store = Store(tmp_path / "buddy.db")
    planning = PlanningService(store)
    settings = SettingsService(store)
    return store, planning, settings


def test_reminder_deduplication_survives_new_notifier(qapp, tmp_path):
    store, planning, settings = services(tmp_path)
    now = datetime(2026, 10, 28, 13, 55, 10, tzinfo=ZONE)
    start = now.replace(hour=14, minute=0, second=0)
    planning.save(CalendarEvent("회의", start, start + timedelta(hours=1), reminder_minutes=5))
    notifier = NotificationService(planning, settings, lambda: now)
    received = QSignalSpy(notifier.due)
    notifier.poll()
    notifier.poll()
    assert received.count() == 1
    replacement = NotificationService(planning, settings, lambda: now + timedelta(seconds=20))
    duplicates = QSignalSpy(replacement.due)
    replacement.poll()
    assert duplicates.count() == 0
    assert store.connection.execute("SELECT COUNT(*) FROM notification_log").fetchone()[0] == 1
    store.close()


def test_paused_notifications_are_not_queued_after_resume(qapp, tmp_path):
    store, planning, settings = services(tmp_path)
    now = datetime(2026, 10, 28, 14, tzinfo=ZONE)
    planning.save(CalendarEvent("회의", now, now + timedelta(hours=1), reminder_minutes=0))
    settings.update(notifications_paused=True)
    notifier = NotificationService(planning, settings, lambda: now)
    received = QSignalSpy(notifier.due)
    notifier.poll()
    assert received.count() == 0
    assert (
        store.connection.execute("SELECT status FROM notification_log").fetchone()[0]
        == "suppressed"
    )
    settings.update(notifications_paused=False)
    notifier.poll()
    assert received.count() == 0
    store.close()


def test_quiet_hours_cross_midnight_and_global_disable(qapp, tmp_path):
    store, planning, settings = services(tmp_path)
    settings.update(quiet_enabled=True, quiet_start="22:00", quiet_end="08:00")
    notifier = NotificationService(planning, settings)
    assert notifier.muted(datetime(2026, 10, 28, 23, tzinfo=ZONE))
    assert notifier.muted(datetime(2026, 10, 29, 7, tzinfo=ZONE))
    assert not notifier.muted(datetime(2026, 10, 29, 8, tzinfo=ZONE))
    assert not notifier.muted(datetime(2026, 10, 28, 14, tzinfo=ZONE))
    settings.update(notifications_enabled=False)
    assert notifier.muted(datetime(2026, 10, 28, 14, tzinfo=ZONE))
    store.close()


def test_sleep_resume_ignores_old_alerts_and_clock_reversal_does_not_duplicate(qapp, tmp_path):
    store, planning, settings = services(tmp_path)
    now = datetime(2026, 10, 28, 14, tzinfo=ZONE)
    planning.save(
        CalendarEvent(
            "오래된 일정", now - timedelta(hours=3), now - timedelta(hours=2), reminder_minutes=0
        )
    )
    planning.save(
        CalendarEvent(
            "최근 일정", now - timedelta(minutes=1), now + timedelta(hours=1), reminder_minutes=0
        )
    )
    clock = [now]
    notifier = NotificationService(planning, settings, lambda: clock[0])
    received = QSignalSpy(notifier.due)
    notifier.poll()
    assert received.count() == 1
    assert received.at(0)[0][0].occurrence.title == "최근 일정"
    clock[0] -= timedelta(seconds=20)
    notifier.poll()
    assert received.count() == 1
    store.close()


def test_cancellation_and_notifier_error_do_not_crash(qapp, tmp_path):
    store, planning, settings = services(tmp_path)
    now = datetime(2026, 10, 28, 14, tzinfo=ZONE)
    planning.save(CalendarEvent("취소", now, now + timedelta(hours=1), reminder_minutes=0))
    occurrence = planning.occurrences(now.date(), now.date() + timedelta(days=1))[0]
    planning.delete(occurrence, "all")
    notifier = NotificationService(planning, settings, lambda: now)
    received = QSignalSpy(notifier.due)
    failed = QSignalSpy(notifier.failed)
    notifier.poll()
    assert received.count() == 0
    store.close()
    notifier.poll()
    assert failed.count() == 1


def test_calendar_setting_validation_keeps_defaults():
    from desktop_buddy.core.settings import Settings

    settings = Settings.from_mapping(
        {
            "week_start": True,
            "quiet_start": "25:00",
            "quiet_end": None,
            "notifications_enabled": "false",
        }
    )
    assert settings.week_start == 6
    assert settings.quiet_start == "22:00"
    assert settings.quiet_end == "08:00"
    assert settings.notifications_enabled
