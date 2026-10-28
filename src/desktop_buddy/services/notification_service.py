import logging
from datetime import UTC, datetime, timedelta

from PySide6.QtCore import QObject, QTimer, Signal


class NotificationService(QObject):
    due = Signal(object)
    failed = Signal(str)

    def __init__(self, planning, settings, clock=None):
        super().__init__()
        self.planning, self.settings = planning, settings
        self.clock = clock or (lambda: datetime.now(UTC))
        self.timer = QTimer(self)
        self.timer.setInterval(30000)
        self.timer.timeout.connect(self.poll)
        self.last_check = None

    def start(self) -> None:
        self.poll()
        self.timer.start()

    def stop(self) -> None:
        self.timer.stop()

    def muted(self, now: datetime) -> bool:
        settings = self.settings.current
        if not settings.notifications_enabled or settings.notifications_paused:
            return True
        if not settings.quiet_enabled:
            return False
        local = now.astimezone(self.planning.zone).strftime("%H:%M")
        start, end = settings.quiet_start, settings.quiet_end
        return start <= local < end if start <= end else local >= start or local < end

    def poll(self) -> None:
        now = self.clock()
        lower = now - timedelta(minutes=5)
        if self.last_check is not None and self.last_check <= now:
            lower = max(lower, self.last_check)
        try:
            reminders = self.planning.reminders_between(lower, now)
            quiet = self.muted(now)
            claimed = []
            with self.planning.store.connection:
                for reminder in reminders:
                    if self.planning.repository.claim_notification(
                        reminder.key, now.isoformat(), "suppressed" if quiet else "shown"
                    ):
                        claimed.append(reminder)
            self.last_check = now
            if claimed and not quiet:
                # One batch prevents notification storms after wake or several simultaneous events.
                self.due.emit(claimed)
        except Exception as error:
            logging.getLogger(__name__).warning("Reminder check failed (%s)", type(error).__name__)
            self.failed.emit("알림을 확인하지 못했어요. 저장 공간과 날짜 설정을 확인해 주세요.")
