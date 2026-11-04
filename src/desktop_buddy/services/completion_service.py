import time
from collections.abc import Callable

from PySide6.QtCore import QObject, QTimer, Signal

from desktop_buddy.models.focus import PhaseFinished
from desktop_buddy.services.completion_audio import SONG_SECONDS, WavePlayer


class CompletionService(QObject):
    changed = Signal()
    failed = Signal(str)

    def __init__(
        self,
        pet,
        settings,
        focus,
        companion,
        *,
        character: Callable[[], str],
        audio: WavePlayer | None = None,
        clock: Callable[[], float] = time.monotonic,
    ):
        super().__init__(pet)
        self.pet, self.settings, self.focus, self.companion = pet, settings, focus, companion
        self.character, self.audio, self.clock = character, audio or WavePlayer(), clock
        self.active = self.previewing = False
        self._closed = False
        self._owned: str | None = None
        self._seen: list[tuple[str, int]] = []
        self._preferences = None
        self._token = None
        self._started = self._last_tick = self._duration = 0.0
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self.tick)
        settings.changed.connect(self.refresh)
        focus.updated.connect(self._timer_updated)
        companion.changed.connect(self.refresh)
        pet.visibility_changed.connect(self.refresh)
        pet.interaction_changed.connect(self.refresh)
        pet.single_clicked.connect(self.stop)
        pet.pack_changed.connect(self.stop)
        pet.animation.state_changed.connect(self._animation_changed)

    def _preference_key(self) -> tuple:
        current = self.settings.current
        return current.completion_style, current.completion_sound_enabled, self.character()

    def _timer_updated(self, *_args) -> None:
        if self.active:
            self.stop()

    def _timer_key(self) -> tuple:
        snapshot = self.focus.snapshot
        return (
            snapshot.status,
            snapshot.phase,
            snapshot.session_id,
            snapshot.completed_rounds,
            snapshot.next_phase,
        )

    def _allowed(self, preview: bool) -> bool:
        return (
            not self._closed
            and self.pet.isVisible()
            and not self.pet.interacting
            and not self.companion.quiet()
            and (preview or self.settings.current.timer_notifications)
        )

    def handle(self, result: PhaseFinished) -> None:
        if self._closed:
            return
        key = result.phase, result.session_id
        if key in self._seen:
            return
        self._seen = [*self._seen[-63:], key]
        self.stop()
        if not self._allowed(False):
            return
        # Automatic next phases keep running; use only the existing short reaction.
        if self.focus.status in ("running", "paused"):
            if (
                self.settings.current.completion_style != "off"
                and not self.settings.current.reduce_motion
            ):
                self.pet.animation.play("complete", priority=80)
            return
        self._start(preview=False, focus_completed=result.phase == "focus")

    def preview(self) -> None:
        if self.focus.status in ("running", "paused"):
            raise ValueError("타이머를 멈춘 뒤 축하를 미리 볼 수 있어요.")
        if not self._allowed(True):
            raise ValueError("캐릭터를 표시하고 수면·방해 금지를 해제한 뒤 미리 볼 수 있어요.")
        if not self._start(preview=True, focus_completed=True):
            raise ValueError(
                "축하를 재생하지 못했어요. 캐릭터 표시·움직임·소리 설정을 확인해 주세요."
            )

    def _start(self, *, preview: bool, focus_completed: bool) -> bool:
        self.stop()
        current = self.settings.current
        style = current.completion_style
        motion = (
            style != "off" and not current.reduce_motion and "complete" in self.pet.animation.clips
        )
        sound = (
            focus_completed
            and current.completion_sound_enabled
            and self.character() in SONG_SECONDS
        )
        if not motion and not sound:
            return False
        animation = self.pet.animation
        if not animation.clip.loop and animation.priority > 80:
            return False
        self.active, self.previewing = True, preview
        self._preferences, self._token = self._preference_key(), self._timer_key()
        self._owned = (
            "celebrate"
            if motion and focus_completed and style == "party" and "celebrate" in animation.clips
            else "complete"
            if motion
            else None
        )
        if self._owned is not None:
            animation.play(self._owned, priority=80, hold=self._owned == "celebrate")
        if sound:
            try:
                self.audio.play(self.character())
            except Exception:
                sound = False
                self.failed.emit("완료 음악을 재생하지 못했어요. 소리 없이 계속할게요.")
        if not self._owned and not sound:
            self.active, self.previewing = False, False
            self.changed.emit()
            return False
        clip = animation.clips.get("complete", animation.clips["idle"])
        simple_seconds = sum(clip.durations_ms or [1000 / clip.fps] * len(clip.frames))
        simple_seconds /= 10 * self.pet.settings.animation_speed
        self._duration = (
            SONG_SECONDS[self.character()]
            if sound
            else 6.0
            if self._owned == "celebrate"
            else max(0.2, simple_seconds)
        )
        self._started = self._last_tick = self.clock()
        self.timer.start()
        self.changed.emit()
        return True

    def _animation_changed(self, state: str) -> None:
        if not self.active or not self._owned or state == self._owned:
            return
        if self._owned == "complete" and state == self.pet.animation.base_state:
            self._owned = None
            if self.audio.playing:
                return
        self.stop()

    def refresh(self, *_args) -> None:
        if not self.active:
            return
        if (
            not self._allowed(self.previewing)
            or self._preferences != self._preference_key()
            or self._token != self._timer_key()
            or (self.settings.current.reduce_motion and self._owned is not None)
        ):
            self.stop()

    def tick(self) -> None:
        if not self.active:
            return
        now = self.clock()
        gap, self._last_tick = now - self._last_tick, now
        if gap < 0 or gap > 2 or now - self._started >= self._duration:
            self.stop()
            return
        self.refresh()

    def stop(self) -> None:
        active, owned = self.active, self._owned
        self.active, self.previewing, self._owned = False, False, None
        self.timer.stop()
        self.audio.stop()
        animation = self.pet.animation
        if owned is not None and animation.state == owned and animation.priority <= 80:
            animation.play(animation.base_state, priority=animation.base_priority, force=True)
        if active:
            self.changed.emit()

    def close(self) -> None:
        self._closed = True
        self.stop()
