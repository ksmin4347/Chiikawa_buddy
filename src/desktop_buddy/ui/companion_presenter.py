from dataclasses import replace

from desktop_buddy.ui.pet import PetWindow


class CompanionPresenter:
    """Apply temporary presentation choices without saving over user preferences."""

    def __init__(self, pet: PetWindow, mini, settings, focus, companion):
        self.pet, self.mini, self.settings = pet, mini, settings
        self.focus, self.companion = focus, companion
        self.requested_visible = False
        self._override = None
        self._profile = None
        self.pet.speech_guard = self.can_speak
        companion.changed.connect(self.refresh)
        companion.nudge.connect(pet.speak)
        companion.reaction.connect(lambda state: pet.animation.play(state, priority=40))
        focus.updated.connect(self.refresh)
        settings.changed.connect(self.refresh)

    def can_speak(self, explicit: bool = False, essential: bool = False) -> bool:
        return explicit or not self.companion.quiet(essential=essential)

    def refresh(self, *_args) -> None:
        current, snapshot = self.settings.current, self.focus.snapshot
        focusing = snapshot.focusing
        mode = current.focus_appearance if focusing else "normal"
        signature = (focusing, mode, self.companion.snapshot.fullscreen)
        overridden = self._override == signature
        if self._override is not None and not overridden:
            self._override = None
        effective = current
        if mode == "calm":
            effective = replace(current, animation_speed=max(20, current.animation_speed // 2))
        elif mode == "small":
            effective = replace(current, size=min(128, current.size))
        if effective != self._profile:
            self._profile = effective
            self.pet.apply_settings(effective)
        base = (
            ("focus" if snapshot.phase == "focus" else "break")
            if snapshot.status == "running"
            else self.companion.snapshot.state
        )
        priority = 60 if base in ("focus", "break") else 30 if base == "sleep" else 20
        self.pet.animation.set_base(base, priority=priority)
        if current.reduce_motion and self.pet.animation.state != self.pet.animation.base_state:
            self.pet.animation.play(self.pet.animation.base_state, priority=priority, force=True)
        blocked = self.companion.snapshot.fullscreen and not overridden
        visible = (
            self.requested_visible
            and not blocked
            and (mode not in ("hidden", "timer_only") or overridden)
        )
        if visible != self.pet.isVisible():
            self.pet.setVisible(visible)
        self.mini.set_policy(
            force_visible=self.requested_visible and mode == "timer_only" and not blocked,
            suppressed=not self.requested_visible or blocked or mode == "hidden",
        )
        if self.pet.bubble.isVisible() and not self.can_speak(
            explicit=self.pet.bubble_explicit, essential=self.pet.bubble_essential
        ):
            self.pet.bubble.hide()

    def find(self) -> None:
        self.requested_visible = True
        self._override = (
            self.focus.snapshot.focusing,
            self.settings.current.focus_appearance if self.focus.snapshot.focusing else "normal",
            self.companion.snapshot.fullscreen,
        )
        self.pet.ensure_visible_position()
        self.refresh()
        self.pet.raise_()

    def show_initial(self, visible: bool) -> None:
        self.requested_visible = visible
        self.refresh()

    def hide(self) -> None:
        self.requested_visible = False
        self._override = None
        self.refresh()
