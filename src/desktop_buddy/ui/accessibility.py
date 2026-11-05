from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QAccessible, QAccessibleAnnouncementEvent
from PySide6.QtWidgets import QLineEdit, QWidget


def announce(widget: QWidget, text: str, *, urgent: bool = False) -> None:
    if not text or not widget.isVisible() or not QAccessible.isActive():
        return
    event = QAccessibleAnnouncementEvent(widget, text)
    event.setPoliteness(
        QAccessible.AnnouncementPoliteness.Assertive
        if urgent
        else QAccessible.AnnouncementPoliteness.Polite
    )
    QAccessible.updateAccessibility(event)


class CommandInput(QLineEdit):
    """Keep command shortcuts from consuming an unfinished IME composition."""

    composing = False

    def inputMethodEvent(self, event) -> None:
        self.composing = bool(event.preeditString())
        super().inputMethodEvent(event)

    def focusOutEvent(self, event) -> None:
        super().focusOutEvent(event)
        self.composing = False

    def event(self, event) -> bool:
        if (
            self.composing
            and event.type() == QEvent.Type.ShortcutOverride
            and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Escape)
        ):
            event.accept()
            return True
        return super().event(event)
