import math
from dataclasses import dataclass

from desktop_buddy.core.geometry import Rect


def look_direction(dx: float, dy: float, previous: int | None = None) -> int:
    """Clockwise from north; retain the previous pose near a sector boundary."""
    angle = math.atan2(dx, -dy) % math.tau
    sector = math.tau / 16
    if previous is not None:
        delta = (angle - previous * sector + math.pi) % math.tau - math.pi
        if abs(delta) <= sector * 0.65:
            return previous
    return math.floor(angle / sector + 0.5) % 16


@dataclass(frozen=True)
class Walk:
    start_x: int
    end_x: int
    y: int
    started: float
    duration: float

    def position(self, now: float) -> tuple[int, int, bool]:
        progress = min(1.0, max(0.0, (now - self.started) / self.duration))
        return round(self.start_x + (self.end_x - self.start_x) * progress), self.y, progress == 1


def plan_walk(
    x: int, y: int, size: int, area: Rect, direction: int, distance: int, now: float
) -> Walk | None:
    right = area.x + area.width - size
    bottom = area.y + area.height - size
    if not area.x <= x <= right or not area.y <= y <= bottom:
        return None
    for sign in (direction, -direction):
        target = max(area.x, min(right, x + sign * distance))
        if abs(target - x) >= 24:
            return Walk(x, target, y, now, abs(target - x) / max(24, size * 0.35))
    return None
