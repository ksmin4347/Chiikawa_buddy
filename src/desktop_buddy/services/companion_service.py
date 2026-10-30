import logging
from datetime import date, timedelta

from PySide6.QtCore import QObject, QTimer, Signal

from desktop_buddy.database.companion_repository import CompanionRepository
from desktop_buddy.database.store import Store
from desktop_buddy.models.companion import CompanionSnapshot, in_time_window, study_gap
from desktop_buddy.models.focus import Clock, SystemClock
from desktop_buddy.services.focus_timer import FocusTimerService
from desktop_buddy.services.local_day_guard import LocalDayGuard
from desktop_buddy.services.settings_service import SettingsService
from desktop_buddy.services.windows_attention import WindowsAttention


class CompanionService(QObject):
    changed = Signal(object)
    nudge = Signal(str)
    reaction = Signal(str)
    failed = Signal(str)

    def __init__(
        self,
        store: Store,
        settings: SettingsService,
        focus: FocusTimerService,
        clock: Clock | None = None,
        attention=None,
    ) -> None:
        super().__init__()
        self.settings, self.focus = settings, focus
        self.clock = clock or SystemClock()
        self.repository = CompanionRepository(store.connection)
        self.guard = LocalDayGuard(self.repository, self.clock, focus.planning.zone)
        self.attention = attention or WindowsAttention()
        self.snapshot = CompanionSnapshot()
        self.can_notify = lambda: False
        self._last_valid = None
        self._initialized = False
        self._error = False
        self._attention_warned = False
        self.timer = QTimer(self)
        self.timer.setInterval(2000)
        self.timer.timeout.connect(self.poll)
        settings.changed.connect(self.poll)
        focus.updated.connect(self.poll)
        focus.records_changed.connect(self.poll)
        self.poll()

    def start(self) -> None:
        self.timer.start()

    def stop(self) -> None:
        self.timer.stop()

    def quiet(self, essential: bool = False) -> bool:
        current = self.settings.current
        if self._error or self.snapshot.fullscreen or self.guard.warning:
            return True
        if essential and current.timer_alert_during_quiet:
            return False
        now = self.clock.now().astimezone(self.focus.planning.zone)
        sleeping = current.sleep_enabled and in_time_window(
            now, current.sleep_start, current.sleep_end
        )
        return (
            current.notifications_paused
            or sleeping
            or (
                current.quiet_enabled
                and in_time_window(now, current.quiet_start, current.quiet_end)
            )
            or (not essential and self.focus.snapshot.focusing and current.focus_quiet)
        )

    def poll(self, *_args) -> None:
        try:
            self._poll()
            self._error = False
        except Exception as error:
            logging.getLogger(__name__).warning("Companion check failed (%s)", type(error).__name__)
            if not self._error:
                self.failed.emit("생활 상태를 확인하지 못했어요. 저장 공간과 날짜를 확인해 주세요.")
            self._error = True

    def _poll(self) -> None:
        self.guard.observe()
        now = self.clock.now().astimezone(self.focus.planning.zone)
        current, timer = self.settings.current, self.focus.snapshot
        periods = self.repository.periods()
        resting = now.weekday() in current.rest_weekdays or any(
            row["start_date"] <= now.date() <= row["end_date"] for row in periods
        )
        valid = self.repository.last_valid(current.valid_focus_minutes * 60)
        if valid and valid > self.clock.now() + timedelta(seconds=120):
            self.guard.flag()
        last_date = valid.astimezone(self.focus.planning.zone).date() if valid else None
        gap = (
            study_gap(last_date, now.date(), current.rest_weekdays, periods)
            if last_date and last_date <= now.date()
            else 0
        )
        sleeping = current.sleep_enabled and in_time_window(
            now, current.sleep_start, current.sleep_end
        )
        fullscreen = current.fullscreen_hide and self.attention.fullscreen()
        if current.fullscreen_hide and not self.attention.available and not self._attention_warned:
            self._attention_warned = True
            self.failed.emit(
                "Windows 전체 화면 감지를 사용할 수 없어요. 트레이에서 직접 숨길 수 있어요."
            )
        state, description = "idle", "편안하게 함께하고 있어요."
        if timer.status == "running":
            state = "focus" if timer.phase == "focus" else "break"
            description = "조용히 집중을 응원해요." if state == "focus" else "잠깐 쉬고 있어요."
        elif sleeping:
            state, description = "sleep", "설정한 수면 시간이에요."
        elif self.guard.warning:
            description = "날짜 변경을 확인할 때까지 공부 공백 판단과 자동 안내를 쉬어요."
        elif resting:
            description = "오늘은 쉬는 날이에요. 편안하게 보내요."
        elif current.emotion_enabled and current.record_focus and last_date:
            if gap >= current.emotion_gap_days:
                state, description = "sad", "오늘은 조금만 함께해도 괜찮아요."
            elif gap >= max(1, current.emotion_gap_days - 1):
                state, description = "worried", "내 속도로 천천히 시작해도 좋아요."
        elif not last_date:
            description = "첫 유효한 집중 전에는 공부 공백을 판단하지 않아요."
        previous = self.snapshot
        self.snapshot = CompanionSnapshot(
            state,
            description,
            gap,
            last_date,
            resting,
            sleeping,
            False,
            self.guard.warning,
            fullscreen,
        )
        self.snapshot = CompanionSnapshot(
            state,
            description,
            gap,
            last_date,
            resting,
            sleeping,
            self.quiet(),
            self.guard.warning,
            fullscreen,
        )
        if self.snapshot != previous:
            self.changed.emit(self.snapshot)
        if (
            self._initialized
            and valid
            and self._last_valid
            and valid > self._last_valid
            and previous.state in ("sad", "worried")
            and not self.quiet()
        ):
            self.reaction.emit("happy")
        self._last_valid, self._initialized = valid, True
        interval = current.emotion_message_days
        if (
            state in ("sad", "worried")
            and interval > 0
            and not self.quiet()
            and current.bubbles_enabled
            and self.can_notify()
        ):
            last_message = self.repository.last_message("emotion")
            if last_message is None or (now.date() - last_message).days >= interval:
                with self.repository.connection:
                    claimed = self.repository.claim_message("emotion", now.date())
                if claimed:
                    self.nudge.emit(description)

    def acknowledge_clock(self) -> None:
        self.guard.acknowledge()
        self.poll()

    def add_rest_period(self, start: date, end: date) -> None:
        if end < start:
            raise ValueError("휴식 종료일은 시작일보다 빠를 수 없어요.")
        with self.repository.connection:
            self.repository.add_period(start, end)
        self.poll()

    def delete_rest_period(self, item_id: int) -> None:
        with self.repository.connection:
            self.repository.delete_period(item_id)
        self.poll()
