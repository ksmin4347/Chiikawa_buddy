import math

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPainter, QPen
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
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._style = None
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
        if self._style != current.mini_timer_style:
            self._style = current.mini_timer_style
            self.setMinimumSize(0, 0)
            self.setMaximumSize(16777215, 16777215)
            if self._style == "ring":
                self.setStyleSheet("background:transparent;padding:0;border:0;")
                self.setFixedSize(124, 124)
            else:
                self.setStyleSheet(
                    "background:#264c3b;color:white;border-radius:12px;padding:8px 14px;"
                    "font-size:14px;font-weight:600;"
                )
        if self._style != "ring":
            self.adjustSize()
        self.update()
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

    def paintEvent(self, event):
        if self._style != "ring":
            super().paintEvent(event)
            return
        snapshot = self.timer.snapshot
        fraction = max(0.0, min(1.0, snapshot.elapsed_seconds / max(1, snapshot.planned_seconds)))
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#faf9f6"))
        painter.drawEllipse(QRectF(4, 4, 116, 116))
        painter.setPen(QPen(QColor("#dce3d9"), 6))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QRectF(8, 8, 108, 108))
        color = "#4e8061" if fraction < 0.65 else "#c7893a" if fraction < 0.85 else "#bf625b"
        painter.setPen(QPen(QColor(color if snapshot.status != "paused" else "#76847b"), 6))
        painter.drawArc(QRectF(8, 8, 108, 108), 90 * 16, -round(fraction * 360 * 16))
        painter.setPen(QColor("#293e34"))
        painter.setFont(QFont("Malgun Gothic", 9))
        phase = (
            "완료"
            if snapshot.status == "ready"
            else "준비"
            if snapshot.status == "idle"
            else PHASE_NAMES[snapshot.phase]
        )
        painter.drawText(QRectF(16, 26, 92, 22), Qt.AlignmentFlag.AlignCenter, phase)
        painter.setFont(QFont("Malgun Gothic", 15, QFont.Weight.Bold))
        painter.drawText(
            QRectF(12, 47, 100, 30),
            Qt.AlignmentFlag.AlignCenter,
            countdown(snapshot.remaining_seconds),
        )
        if snapshot.status == "paused":
            painter.setFont(QFont("Malgun Gothic", 9))
            painter.drawText(QRectF(16, 78, 92, 20), Qt.AlignmentFlag.AlignCenter, "일시정지")
        painter.end()
