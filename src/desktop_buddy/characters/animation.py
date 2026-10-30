import json
import math
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QColor, QPainter, QPixmap


@dataclass
class Clip:
    frames: list[QPixmap]
    fps: float
    loop: bool


def fallback_pixmap() -> QPixmap:
    pixmap = QPixmap(256, 256)
    pixmap.fill(QColor("transparent"))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QColor("#38564d"))
    painter.setBrush(QColor("#bfe3cd"))
    painter.drawEllipse(36, 36, 184, 192)
    painter.setBrush(QColor("#38564d"))
    painter.drawEllipse(88, 112, 10, 14)
    painter.drawEllipse(158, 112, 10, 14)
    painter.drawArc(110, 136, 36, 24, 180 * 16, 180 * 16)
    painter.end()
    return pixmap


def load_clips(root: Path) -> dict[str, Clip]:
    clips = {}
    try:
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        states = manifest.get("states", {}) if isinstance(manifest, dict) else {}
    except (OSError, ValueError):
        states = {}
    if isinstance(states, dict):
        for name, spec in states.items():
            if not isinstance(spec, dict) or not isinstance(spec.get("frames"), list):
                continue
            fps = spec.get("fps", 3)
            if type(fps) not in (int, float) or not math.isfinite(fps):
                fps = 3
            frames = []
            for relative in spec["frames"]:
                if not isinstance(relative, str):
                    continue
                try:
                    path = (root / relative).resolve()
                    if not path.is_relative_to(root.resolve()):
                        continue
                    pixmap = QPixmap(str(path))
                    if not pixmap.isNull():
                        frames.append(pixmap)
                except (OSError, ValueError):
                    continue
            if frames:
                loop = spec.get("loop", True)
                clips[name] = Clip(
                    frames, max(1, min(30, fps)), loop if type(loop) is bool else True
                )
    if "idle" not in clips:
        clips["idle"] = Clip([fallback_pixmap()], 2, True)
    return clips


class AnimationState(QObject):
    """Single authority for state transitions. Future services send events here."""

    state_changed = Signal(str)

    def __init__(self, clips: dict[str, Clip]):
        super().__init__()
        self.clips = clips
        self.base_state = "idle"
        self.state = "idle"
        self.index = 0

    @property
    def clip(self) -> Clip:
        return self.clips[self.state]

    @property
    def frame(self) -> QPixmap:
        return self.clip.frames[self.index]

    def play(self, state: str) -> None:
        self.state = state if state in self.clips else "idle"
        self.index = 0
        self.state_changed.emit(self.state)

    def set_base(self, state: str) -> None:
        old_base = self.base_state
        self.base_state = state if state in self.clips else "idle"
        if self.state == old_base or self.clip.loop:
            if self.state != self.base_state:
                self.play(self.base_state)

    def advance(self) -> None:
        if self.index + 1 < len(self.clip.frames):
            self.index += 1
        elif self.clip.loop:
            self.index = 0
        else:
            self.play(self.base_state)
