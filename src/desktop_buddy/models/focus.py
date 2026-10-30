import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Protocol

Phase = Literal["focus", "short_break", "long_break"]
Status = Literal["idle", "running", "paused", "ready"]


def stamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="microseconds")


class Clock(Protocol):
    def monotonic(self) -> float: ...
    def now(self) -> datetime: ...


class SystemClock:
    def monotonic(self) -> float:
        return time.monotonic()

    def now(self) -> datetime:
        return datetime.now(UTC)


@dataclass(frozen=True)
class TimerSnapshot:
    status: Status
    phase: Phase
    planned_seconds: float
    elapsed_seconds: float
    paused_seconds: float
    session_id: int | None
    completed_rounds: int
    next_phase: Phase | None
    task_title: str
    category_name: str
    reason: str = ""

    @property
    def remaining_seconds(self) -> float:
        return max(0, self.planned_seconds - self.elapsed_seconds)

    @property
    def focusing(self) -> bool:
        return self.status == "running" and self.phase == "focus"


@dataclass(frozen=True)
class PhaseFinished:
    phase: Phase
    session_id: int
    elapsed_seconds: float
    next_phase: Phase
