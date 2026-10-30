import math
from datetime import UTC, timedelta, tzinfo

from desktop_buddy.database.companion_repository import CompanionRepository
from desktop_buddy.models.focus import Clock


class LocalDayGuard:
    """Freeze automatic emotional/time-based prompts on an observed clock discontinuity."""

    def __init__(self, repository: CompanionRepository, clock: Clock, zone: tzinfo = UTC) -> None:
        self.repository, self.clock, self.zone = repository, clock, zone
        self.last_wall, self.warning = repository.clock_state()
        now = clock.now()
        self.warning = self.warning or (
            self.last_wall is not None
            and (
                now < self.last_wall - timedelta(seconds=120)
                or now.astimezone(self.zone).date() < self.last_wall.astimezone(self.zone).date()
            )
        )
        self.last_wall = max(self.last_wall, now) if self.last_wall else now
        self.last_mono = clock.monotonic()
        self.checkpoint = self.last_mono
        self._save()

    def _save(self) -> None:
        with self.repository.connection:
            self.repository.save_clock(self.last_wall, self.warning)
        self.checkpoint = self.clock.monotonic()

    def observe(self) -> None:
        now, mono = self.clock.now(), self.clock.monotonic()
        previous_day = self.last_wall.astimezone(self.zone).date()
        day = now.astimezone(self.zone).date()
        delta = mono - self.last_mono
        wall_delta = (now - self.last_wall).total_seconds()
        if not self.warning:
            if (
                not math.isfinite(delta)
                or delta < 0
                or abs(wall_delta - delta) > 120
                or day < previous_day
            ):
                self.flag()
            else:
                self.last_wall = now
        self.last_mono = mono
        if mono - self.checkpoint >= 60 or (not self.warning and day != previous_day):
            self._save()

    def flag(self) -> None:
        if not self.warning:
            self.warning = True
            self._save()

    def acknowledge(self) -> None:
        self.last_wall, self.last_mono = self.clock.now(), self.clock.monotonic()
        self.warning = False
        self._save()
