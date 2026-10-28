from dataclasses import dataclass


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    width: int
    height: int


def keep_visible(x: int, y: int, size: int, screens: list[Rect]) -> tuple[int, int]:
    """Clamp to one actual work area, never to the gap between monitors."""
    if not screens:
        return x, y

    def distance(screen: Rect) -> int:
        cx, cy = x + size // 2, y + size // 2
        dx = max(screen.x - cx, 0, cx - (screen.x + screen.width))
        dy = max(screen.y - cy, 0, cy - (screen.y + screen.height))
        return dx * dx + dy * dy

    screen = min(screens, key=distance)
    return (
        max(screen.x, min(x, screen.x + max(0, screen.width - size))),
        max(screen.y, min(y, screen.y + max(0, screen.height - size))),
    )
