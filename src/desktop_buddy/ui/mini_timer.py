import math

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QLabel

PHASE_NAMES = {"focus": "집중", "short_break": "짧은 휴식", "long_break": "긴 휴식"}


def countdown(seconds: float) -> str:
    value = max(0, math.ceil(seconds))
    return f"{value // 60:02}:{value % 60:02}"


def duration(seconds: float) -> str:
    minutes = int(seconds // 60)
    if minutes >= 60:
        return f"{minutes // 60}시간 {minutes % 60}분"
    return f"{minutes}분 {int(seconds % 60)}초" if minutes < 1 else f"{minutes}분"


class MiniTimer(QLabel):
    def __init__(self, pet, timer, settings):
        super().__init__(
            None,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowTransparentForInput,
        )
        self.pet, self.timer, self.settings = pet, timer, settings
        self.hovered = False
        self.force_visible = False
        self.suppressed = False
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setWindowTitle("Desktop Buddy · 작은 타이머")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet(
            "background:#264c3b;color:#ffffff;border-radius:12px;padding:8px 14px;"
            "font-size:14px;font-weight:600;"
        )
        timer.updated.connect(self.refresh)
        settings.changed.connect(self.refresh)
        pet.geometry_changed.connect(self.refresh)
        pet.visibility_changed.connect(self.refresh)
        pet.hover_changed.connect(self.set_hover)
        self.refresh()

    def set_policy(self, force_visible: bool, suppressed: bool) -> None:
        self.force_visible, self.suppressed = force_visible, suppressed
        self.refresh()

    def set_hover(self, hovered: bool) -> None:
        self.hovered = hovered
        self.refresh()

    def refresh(self, *_args) -> None:
        snapshot = self.timer.snapshot
        current = self.settings.current
        mode = current.mini_timer_mode
        visible = self.pet.isVisible() and (
            mode == "always"
            or (
                mode == "focus"
                and snapshot.phase == "focus"
                and snapshot.status in ("running", "paused")
            )
            or (mode == "hover" and self.hovered)
        )
        visible = (visible or self.force_visible) and not self.suppressed
        if not visible:
            self.hide()
            return
        suffix = " · 멈춤" if snapshot.status == "paused" else ""
        if snapshot.status == "ready":
            text = "완료 · 다음 단계 대기"
        elif snapshot.status == "idle":
            text = "집중할 준비가 됐어요"
        else:
            text = f"{PHASE_NAMES[snapshot.phase]}  {countdown(snapshot.remaining_seconds)}{suffix}"
        self.setText(text)
        self.adjustSize()
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, current.always_on_top)
        geometry = self.pet.geometry()
        screen = QGuiApplication.screenAt(geometry.center()) or QGuiApplication.primaryScreen()
        area = screen.availableGeometry()
        x = min(
            max(area.left(), geometry.center().x() - self.width() // 2),
            max(area.left(), area.right() - self.width() + 1),
        )
        y = geometry.top() - self.height() + 8
        if y < area.top():
            y = geometry.bottom() - 8
        y = min(max(area.top(), y), max(area.top(), area.bottom() - self.height() + 1))
        self.move(x, y)
        self.show()
