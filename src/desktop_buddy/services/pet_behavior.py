import math
import random
import time
from collections.abc import Callable

from PySide6.QtCore import QObject, QPoint, QTimer
from PySide6.QtGui import QCursor

from desktop_buddy.characters.behavior import Walk, look_direction, plan_walk
from desktop_buddy.services.settings_service import SettingsService
from desktop_buddy.ui.pet import PetWindow


class PetBehavior(QObject):
    def __init__(
        self,
        pet: PetWindow,
        settings: SettingsService,
        *,
        blocked: Callable[[], bool],
        roaming_blocked: Callable[[], bool],
        clock: Callable[[], float] = time.monotonic,
        cursor: Callable[[], QPoint] = QCursor.pos,
        rng: random.Random | None = None,
    ):
        super().__init__(pet)
        self.pet, self.settings = pet, settings
        self.blocked, self.roaming_blocked = blocked, roaming_blocked
        self.clock, self.cursor = clock, cursor
        self.rng = rng or random.Random()
        self.timer = QTimer(self)
        self.timer.setInterval(120)
        self.timer.timeout.connect(self.poll)
        self.walk: Walk | None = None
        self._closed = self._polling = False
        self._last_tick = self.clock()
        self._next_walk = self._last_tick + self.rng.uniform(18, 35)
        self._last_pose: int | None = None
        settings.changed.connect(self.refresh)
        pet.visibility_changed.connect(self.refresh)
        pet.interaction_changed.connect(self.refresh)
        pet.hover_changed.connect(self.refresh)
        pet.animation.state_changed.connect(self.refresh)
        pet.pack_changed.connect(self.reset)
        pet.geometry_changed.connect(self._geometry_changed)
        self.refresh()

    def _geometry_changed(self) -> None:
        if self.walk is not None and not self._polling:
            self.reset()

    def reset(self) -> None:
        self._finish_walk()
        self.refresh()

    def _eligible(self) -> bool:
        state = self.pet.animation
        current = self.settings.current
        return (
            not self._closed
            and self.pet.isVisible()
            and not current.reduce_motion
            and not self.pet.interacting
            and not self.blocked()
            and state.base_state == "idle"
            and (state.state == "idle" or state.ambient)
            and (
                (current.cursor_look_enabled and "look" in state.clips)
                or (current.roaming_enabled and "run_right" in state.clips)
            )
        )

    def refresh(self, *_args) -> None:
        if self._closed or self._polling:
            return
        if not self._eligible():
            self._suspend()
            return
        interval = 33 if self.walk is not None else 120
        if self.timer.interval() != interval:
            self.timer.setInterval(interval)
        if not self.timer.isActive():
            self._last_tick = self.clock()
            self.timer.start()

    def _defer_walk(self, now: float) -> None:
        self._next_walk = now + self.rng.uniform(18, 35)

    def _finish_walk(self, *, persist: bool = True) -> None:
        previous, self.walk = self.walk, None
        self.pet.animation.clear_ambient()
        self._last_pose = None
        self._defer_walk(self.clock())
        if previous is not None and persist and self.pet.x() != previous.start_x:
            self.pet.position_changed.emit(self.pet.x(), self.pet.y())

    def _suspend(self) -> None:
        self.timer.stop()
        self._finish_walk()

    def poll(self) -> None:
        if self._polling or self._closed:
            return
        self._polling = True
        try:
            self._poll()
        finally:
            self._polling = False
        self.refresh()

    def _poll(self) -> None:
        now = self.clock()
        gap, self._last_tick = now - self._last_tick, now
        if not self._eligible() or gap < 0 or gap > 0.5:
            self._suspend()
            return
        pet, current = self.pet, self.settings.current
        pointer = self.cursor()
        dx = pointer.x() - (pet.x() + pet.width() / 2)
        dy = pointer.y() - (pet.y() + pet.height() * 0.43)
        distance = math.hypot(dx, dy)
        can_walk = (
            current.roaming_enabled
            and {"run_left", "run_right"} <= pet.animation.clips.keys()
            and not self.roaming_blocked()
            and not pet.bubble.isVisible()
            and distance > max(120, pet.width())
        )
        if self.walk is not None:
            if not can_walk:
                self._finish_walk()
            else:
                x, y, finished = self.walk.position(now)
                # A monitor/size/manual-position change invalidates the old path.
                if pet.safe_position(x, y) != (x, y):
                    self._finish_walk()
                    return
                pet.move(x, y)
                if finished:
                    self._finish_walk()
                return
        if not can_walk:
            self._defer_walk(now)
        elif now >= self._next_walk:
            self.walk = plan_walk(
                pet.x(),
                pet.y(),
                pet.width(),
                pet.work_area(),
                self.rng.choice((-1, 1)),
                round(self.rng.uniform(70, 130) * pet.width() / 176),
                now,
            )
            if self.walk is not None:
                state = "run_right" if self.walk.end_x > self.walk.start_x else "run_left"
                pet.animation.show_ambient(state)
                self._last_pose = None
                return
            self._defer_walk(now)
        if current.cursor_look_enabled and "look" in pet.animation.clips and 24 < distance < 700:
            pose = look_direction(dx, dy, self._last_pose)
            pet.animation.show_ambient("look", pose)
            self._last_pose = pose
        else:
            pet.animation.clear_ambient()
            self._last_pose = None

    def close(self) -> None:
        self._closed = True
        self.timer.stop()
        self._finish_walk(persist=False)
