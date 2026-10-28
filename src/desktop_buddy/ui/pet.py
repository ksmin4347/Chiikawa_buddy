from PySide6.QtCore import QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QBitmap, QGuiApplication, QPainter, QRegion
from PySide6.QtWidgets import QApplication, QMenu, QWidget

from desktop_buddy.characters.animation import AnimationState
from desktop_buddy.core.geometry import Rect, keep_visible
from desktop_buddy.core.metadata import APP_NAME
from desktop_buddy.core.settings import Settings
from desktop_buddy.ui.bubble import SpeechBubble


class PetWindow(QWidget):
    manage_requested = Signal()
    quit_requested = Signal()
    hide_requested = Signal()
    reset_requested = Signal()
    position_changed = Signal(int, int)
    single_clicked = Signal()
    visibility_changed = Signal(bool)

    def __init__(self, animation: AnimationState, settings: Settings):
        flags = Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
        super().__init__(None, flags)
        self.setWindowTitle(f"{APP_NAME} · 캐릭터")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setToolTip("한 번 클릭하면 인사 · 더블클릭하면 관리창 · 드래그로 이동")
        self.animation = animation
        self.settings = settings
        self.bubble = SpeechBubble()
        self._press: QPoint | None = None
        self._origin = QPoint()
        self._dragging = False
        self._double = False
        self._frames = {}
        self._masks = {}
        self._scaled_size = 0
        self._click_timer = QTimer(self)
        self._click_timer.setSingleShot(True)
        self._click_timer.timeout.connect(self.react)
        self.animation_timer = QTimer(self)
        self.animation_timer.timeout.connect(self._advance)
        self.animation.state_changed.connect(self._state_changed)
        self.apply_settings(settings)

    def apply_settings(self, settings: Settings) -> None:
        visible = self.isVisible()
        changed_top = (
            bool(self.windowFlags() & Qt.WindowType.WindowStaysOnTopHint) != settings.always_on_top
        )
        self.settings = settings
        if changed_top:
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, settings.always_on_top)
            if visible:
                self.show()
        self.setFixedSize(settings.size, settings.size)
        if self._scaled_size != settings.size:
            self._scaled_size = settings.size
            self._frames = {
                name: [
                    frame.scaled(
                        self.size(),
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                    for frame in clip.frames
                ]
                for name, clip in self.animation.clips.items()
            }
            # Cache each state's silhouette, excluding invisible reaction decorations at idle.
            for name, frames in self._frames.items():
                mask = QRegion()
                for frame in frames:
                    alpha = frame.toImage().createAlphaMask(
                        Qt.ImageConversionFlag.ThresholdAlphaDither
                    )
                    mask = mask.united(QRegion(QBitmap.fromImage(alpha)))
                self._masks[name] = mask
            self.setMask(self._masks[self.animation.state])
        if not settings.bubbles_enabled:
            self.bubble.hide()
        if settings.reduce_motion:
            self.animation.play("idle")
        self._update_timer()
        self.update()

    def _update_timer(self) -> None:
        if (
            self.isVisible()
            and not self.settings.reduce_motion
            and len(self.animation.clip.frames) > 1
        ):
            self.animation_timer.start(
                max(33, round(100000 / (self.animation.clip.fps * self.settings.animation_speed)))
            )
        else:
            self.animation_timer.stop()

    def _state_changed(self, _state: str) -> None:
        self.setMask(self._masks[self.animation.state])
        self._update_timer()
        self.update()

    def _advance(self) -> None:
        self.animation.advance()
        self.update()

    def react(self) -> None:
        self.single_clicked.emit()
        if not self.settings.reduce_motion:
            self.animation.play("happy")
        self.speak(f"나는 {self.settings.character_name}! 오늘도 편하게 함께해요.")

    def speak(self, text: str) -> None:
        if self.settings.bubbles_enabled and self.isVisible():
            self.bubble.speak(text, self.geometry())

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        frame = self._frames[self.animation.state][self.animation.index]
        painter.drawPixmap(
            (self.width() - frame.width()) // 2, (self.height() - frame.height()) // 2, frame
        )

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._update_timer()
        self.visibility_changed.emit(True)

    def hideEvent(self, event) -> None:
        self.animation_timer.stop()
        self._click_timer.stop()
        self.bubble.hide()
        self.visibility_changed.emit(False)
        super().hideEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._press = event.globalPosition().toPoint()
            self._origin = self.pos()
            self._dragging = False
            self._double = False
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            self.bubble.hide()
            event.accept()

    def mouseMoveEvent(self, event) -> None:
        if self._press is None or not event.buttons() & Qt.MouseButton.LeftButton:
            return
        delta = event.globalPosition().toPoint() - self._press
        if delta.manhattanLength() >= QApplication.startDragDistance():
            self._dragging = True
            self._click_timer.stop()
        if self._dragging:
            point = self._origin + delta
            x, y = self.safe_position(point.x(), point.y())
            self.move(x, y)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton or self._press is None:
            return
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        if self._dragging:
            self.position_changed.emit(self.x(), self.y())
        elif not self._double:
            self._click_timer.start(QApplication.doubleClickInterval())
        self._press = None

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._click_timer.stop()
            self._double = True
            self.manage_requested.emit()
            event.accept()

    def contextMenuEvent(self, event) -> None:
        self._click_timer.stop()
        menu = QMenu(self)
        menu.addAction("관리창 열기", self.manage_requested.emit)
        menu.addAction("인사하기", self.react)
        menu.addSeparator()
        menu.addAction("오른쪽 아래로 이동", self.reset_requested.emit)
        menu.addAction("캐릭터 숨기기", self.hide_requested.emit)
        menu.addSeparator()
        menu.addAction("프로그램 종료", self.quit_requested.emit)
        menu.exec(event.globalPos())

    def safe_position(self, x: int, y: int) -> tuple[int, int]:
        screens = [
            Rect(g.x(), g.y(), g.width(), g.height())
            for g in [screen.availableGeometry() for screen in QGuiApplication.screens()]
        ]
        return keep_visible(x, y, self.width(), screens)

    def ensure_visible_position(self, *_args) -> None:
        self.move(*self.safe_position(self.x(), self.y()))
        self.position_changed.emit(self.x(), self.y())

    def closeEvent(self, event) -> None:
        event.ignore()
        self.hide_requested.emit()
