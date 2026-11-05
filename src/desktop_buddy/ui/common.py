from html import escape

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStyle,
    QStyleOptionButton,
    QStylePainter,
    QVBoxLayout,
    QWidget,
)


def label(text: str, kind: str = "") -> QLabel:
    widget = QLabel(text)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    widget.setWordWrap(True)
    if kind:
        widget.setProperty("kind", kind)
    return widget


def button(text: str, action, primary: bool = False) -> QPushButton:
    widget = QPushButton(text)
    widget.setCursor(Qt.CursorShape.PointingHandCursor)
    widget.setProperty("primary", primary)
    widget.clicked.connect(action)
    return widget


def card(title: str) -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setObjectName("card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(22, 20, 22, 20)
    layout.setSpacing(14)
    layout.addWidget(label(title, "heading"))
    return frame, layout


def compact_combo(widget: QComboBox, characters: int = 10) -> None:
    """Keep long choices available without making the whole page wider."""
    widget.setMinimumContentsLength(characters)
    widget.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
    widget.currentTextChanged.connect(lambda text: widget.setToolTip(escape(text)))
    widget.setToolTip(escape(widget.currentText()))


def wrap_form(form: QFormLayout) -> None:
    form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
    form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)


def scroll_page(page: QWidget) -> QScrollArea:
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setWidget(page)
    return area


def fit_window(window: QWidget) -> None:
    """Fit the decorated window in its current screen's logical work area."""
    if window.isMaximized() or window.isFullScreen():
        return
    screen = window.screen()
    if screen is None:
        return
    area = screen.availableGeometry()
    handle = window.windowHandle()
    margins = handle.frameMargins() if handle is not None else None
    width = max(1, area.width() - (margins.left() + margins.right() if margins else 0))
    height = max(1, area.height() - (margins.top() + margins.bottom() if margins else 0))
    window.setMinimumSize(min(window.minimumWidth(), width), min(window.minimumHeight(), height))
    window.resize(min(window.width(), width), min(window.height(), height))
    frame = window.frameGeometry()
    window.move(
        max(area.left(), min(frame.left(), area.right() - frame.width() + 1)),
        max(area.top(), min(frame.top(), area.bottom() - frame.height() + 1)),
    )


class ElidedButton(QPushButton):
    """Calendar entries keep their full accessible text while painting an ellipsis."""

    def __init__(self, text: str):
        super().__init__(text)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def minimumSizeHint(self) -> QSize:
        size = super().minimumSizeHint()
        size.setWidth(0)
        return size

    def paintEvent(self, _event) -> None:
        option = QStyleOptionButton()
        self.initStyleOption(option)
        contents = self.style().subElementRect(
            QStyle.SubElement.SE_PushButtonContents, option, self
        )
        option.text = (
            self.fontMetrics()
            .elidedText(self.text(), Qt.TextElideMode.ElideRight, max(0, contents.width()))
            .replace("&", "&&")
        )
        painter = QStylePainter(self)
        painter.drawControl(QStyle.ControlElement.CE_PushButton, option)


class ResponsiveGrid(QWidget):
    def __init__(self, widgets: list[QWidget], columns: tuple[int, ...], minimum_width: int):
        super().__init__()
        self.widgets, self.columns, self.minimum_width = widgets, columns, minimum_width
        self._columns = 0
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(14)
        self._reflow()

    def minimumSizeHint(self) -> QSize:
        size = super().minimumSizeHint()
        size.setWidth(min(size.width(), self.minimum_width))
        return size

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._reflow()

    def _reflow(self) -> None:
        columns = next(
            (n for n in self.columns if self.width() >= n * self.minimum_width + (n - 1) * 14),
            1,
        )
        if columns == self._columns:
            return
        self._columns = columns
        while self.grid.count():
            self.grid.takeAt(0)
        for index, widget in enumerate(self.widgets):
            self.grid.addWidget(widget, index // columns, index % columns)
        for column in range(max(self.columns)):
            self.grid.setColumnStretch(column, 1 if column < columns else 0)
        self.updateGeometry()
