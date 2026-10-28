from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QLabel


class SpeechBubble(QLabel):
    def __init__(self):
        super().__init__(None, Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setWindowFlag(Qt.WindowType.WindowTransparentForInput)
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setWordWrap(True)
        self.setMaximumWidth(260)
        self.setStyleSheet(
            "QLabel { background: #fffdf5; color: #293e34; border: 1px solid #cfd9c8;"
            "border-radius: 12px; padding: 12px 16px; font-size: 13px; }"
        )
        self.dismiss_timer = QTimer(self)
        self.dismiss_timer.setSingleShot(True)
        self.dismiss_timer.timeout.connect(self.hide)

    def speak(self, text: str, pet_rect) -> None:
        self.setText(text)
        self.adjustSize()
        anchor = pet_rect.center()
        screen = QGuiApplication.screenAt(anchor) or QGuiApplication.primaryScreen()
        area = screen.availableGeometry()
        x = anchor.x() - self.width() // 2
        y = pet_rect.top() - self.height() - 6
        if y < area.top():
            y = pet_rect.bottom() + 6
        self.move(
            QPoint(
                max(area.left(), min(x, area.right() - self.width() + 1)),
                max(area.top(), min(y, area.bottom() - self.height() + 1)),
            )
        )
        self.show()
        self.dismiss_timer.start(3500)
