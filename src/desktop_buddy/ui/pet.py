from PySide6.QtCore import QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QBitmap, QGuiApplication, QPainter, QRegion
from PySide6.QtWidgets import QApplication, QMenu, QWidget

from desktop_buddy.characters.animation import AnimationState
from desktop_buddy.characters.dialogue_voice import DialogueVoice
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
    geometry_changed = Signal()
    hover_changed = Signal(bool)
    timer_requested = Signal()
    character_requested = Signal()
    quick_focus_requested = Signal(int)
    timer_control_requested = Signal(str)

    def __init__(self, animation: AnimationState, settings: Settings):
        flags = Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
        super().__init__(None, flags)
        self.allow_close = False
        self.timer_status = lambda: "idle"
        self.speech_guard = lambda **kwargs: True
        self.setWindowTitle(f"{APP_NAME} · 캐릭터")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setToolTip("한 번 클릭하면 인사 · 더블클릭하면 관리창 · 드래그로 이동")
        self.animation = animation
        self.settings = settings
        self.voice = DialogueVoice(lambda: self.settings.chat_character_id)
        self.bubble = SpeechBubble()
        self.bubble_explicit = False
        self.bubble_essential = False
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
        if self.settings.chat_character_id != settings.chat_character_id:
            self.bubble.hide()
        self.settings = settings
        if changed_top:
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, settings.always_on_top)
            if visible:
                self.show()
        self.setFixedSize(settings.size, settings.size)
        if self._scaled_size != settings.size:
            self._scaled_size = settings.size
            self._frames, self._masks = self.prepare_pack(self.animation.clips)
            self.setMask(self._masks[self.animation.state])
        if not settings.bubbles_enabled:
            self.bubble.hide()
        if settings.reduce_motion:
            self.animation.play(self.animation.base_state, force=True)
        self._update_timer()
        self.update()
        self.geometry_changed.emit()

    def prepare_pack(self, clips):
        frames = {
            name: [
                frame.scaled(
                    self.size(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                for frame in clip.frames
            ]
            for name, clip in clips.items()
        }
        if any(image.isNull() for images in frames.values() for image in images):
            raise ValueError("캐릭터 표시 자료를 준비하지 못했어요.")
        masks = {}
        for name, images in frames.items():
            mask = QRegion()
            for frame in images:
                alpha = frame.toImage().createAlphaMask(Qt.ImageConversionFlag.ThresholdAlphaDither)
                mask = mask.united(QRegion(QBitmap.fromImage(alpha)))
            masks[name] = mask
        return frames, masks

    def activate_pack(self, clips, prepared):
        self.animation_timer.stop()
        self.bubble.hide()
        self._frames, self._masks = prepared
        self._scaled_size = self.width()
        self.animation.replace_clips(clips)

    def _update_timer(self) -> None:
        if (
            self.isVisible()
            and not self.settings.reduce_motion
            and (len(self.animation.clip.frames) > 1 or not self.animation.clip.loop)
        ):
            self.animation_timer.start(
                max(33, round(self.animation.frame_delay_ms * 100 / self.settings.animation_speed))
            )
        else:
            self.animation_timer.stop()

    def _state_changed(self, _state: str) -> None:
        self.setMask(self._masks[self.animation.state])
        self._update_timer()
        self.update()

    def _advance(self) -> None:
        self.animation.advance()
        self._update_timer()
        self.update()

    def react(self) -> None:
        self.single_clicked.emit()
        if not self.settings.reduce_motion:
            self.animation.play("happy", priority=100)
        self.speak(
            f"나는 {self.settings.character_name}! 오늘도 편하게 함께해요.",
            explicit=True,
            event="greeting",
        )

    def speak(
        self,
        text: str,
        *,
        explicit: bool = False,
        essential: bool = False,
        event: str = "notice",
        details: str | None = None,
        already_styled: bool = False,
    ) -> None:
        if (
            self.settings.bubbles_enabled
            and self.isVisible()
            and self.speech_guard(explicit=explicit, essential=essential)
        ):
            self.bubble_explicit, self.bubble_essential = explicit, essential
            if not already_styled:
                text = self.voice.render(
                    event,
                    moru_text=text,
                    details=(text if event == "notice" else "") if details is None else details,
                )
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
        self.hover_changed.emit(False)
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

    def create_context_menu(self):
        menu = QMenu(self)
        menu.addAction("관리창 열기", self.manage_requested.emit)
        menu.addAction("캐릭터 선택", self.character_requested.emit)
        menu.addAction("집중 타이머", self.timer_requested.emit)
        quick = menu.addMenu("집중 바로 시작")
        active = self.timer_status() in ("running", "paused")
        for minutes in (15, 25, 30, 60):
            action = quick.addAction(
                f"{minutes}분",
                lambda _checked=False, value=minutes: self.quick_focus_requested.emit(value),
            )
            action.setEnabled(not active)
        if active:
            command = "pause" if self.timer_status() == "running" else "resume"
            menu.addAction(
                "일시정지" if command == "pause" else "재개",
                lambda: self.timer_control_requested.emit(command),
            )
            menu.addAction("타이머 중지", lambda: self.timer_control_requested.emit("stop"))
        menu.addAction("인사하기", self.react)
        menu.addSeparator()
        menu.addAction("오른쪽 아래로 이동", self.reset_requested.emit)
        menu.addAction("캐릭터 숨기기", self.hide_requested.emit)
        menu.addSeparator()
        menu.addAction("프로그램 종료", self.quit_requested.emit)
        return menu

    def contextMenuEvent(self, event) -> None:
        self._click_timer.stop()
        menu = self.create_context_menu()
        try:
            menu.exec(event.globalPos())
        finally:
            menu.deleteLater()

    def safe_position(self, x: int, y: int) -> tuple[int, int]:
        screens = [
            Rect(g.x(), g.y(), g.width(), g.height())
            for g in [screen.availableGeometry() for screen in QGuiApplication.screens()]
        ]
        return keep_visible(x, y, self.width(), screens)

    def ensure_visible_position(self, *_args) -> None:
        self.move(*self.safe_position(self.x(), self.y()))
        self.position_changed.emit(self.x(), self.y())

    def moveEvent(self, event) -> None:
        super().moveEvent(event)
        self.geometry_changed.emit()

    def enterEvent(self, event) -> None:
        super().enterEvent(event)
        self.hover_changed.emit(True)

    def leaveEvent(self, event) -> None:
        super().leaveEvent(event)
        self.hover_changed.emit(False)

    def closeEvent(self, event) -> None:
        if self.allow_close:
            event.accept()
            return
        event.ignore()
        self.hide_requested.emit()
