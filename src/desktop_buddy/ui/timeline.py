from datetime import datetime, time, timedelta
from html import escape

from PySide6.QtCore import QEvent, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QFontMetrics, QPalette, QPen
from PySide6.QtWidgets import (
    QApplication,
    QGraphicsItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from desktop_buddy.calendar.layout import arrange_intervals
from desktop_buddy.ui.common import button


class EventBlock(QGraphicsRectItem):
    def __init__(self, rect, occurrence, callback, color, text_color, caption):
        super().__init__(rect)
        self.occurrence, self.callback = occurrence, callback
        self.setZValue(1)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemClipsChildrenToShape, True)
        self.setBrush(QBrush(color))
        self.setPen(QPen(QColor(occurrence.color), 1))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        full = f"{occurrence.title}\n{occurrence.start:%m.%d %H:%M} ~ {occurrence.end:%m.%d %H:%M}"
        if occurrence.record.description:
            full += "\n" + occurrence.record.description
        self.setToolTip(escape(full).replace("\n", "<br>"))
        text = QGraphicsSimpleTextItem(self)
        font = QFont("Malgun Gothic", 9)
        text.setFont(font)
        text.setText(
            QFontMetrics(font).elidedText(
                caption, Qt.TextElideMode.ElideRight, max(4, int(rect.width() - 10))
            )
        )
        text.setBrush(QBrush(text_color))
        text.setPos(rect.x() + 4, rect.y() + 2)
        text.setAcceptedMouseButtons(Qt.MouseButton.NoButton)

    def mousePressEvent(self, event):
        event.accept()
        occurrence, callback = self.occurrence, self.callback
        QTimer.singleShot(0, lambda: callback(occurrence))


class TimelineView(QWidget):
    occurrence_clicked = Signal(object)
    day_selected = Signal(object)

    def __init__(self):
        super().__init__()
        self.days, self.occurrences = [], []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)
        self.header = QHBoxLayout()
        self.header.setContentsMargins(52, 0, 18, 0)
        layout.addLayout(self.header)
        self.all_day_widget = QWidget()
        self.all_day_strip = QHBoxLayout(self.all_day_widget)
        self.all_day_strip.setContentsMargins(0, 0, 18, 0)
        layout.addWidget(self.all_day_widget)
        self.view = QGraphicsView()
        self.scene = QGraphicsScene(self.view)
        self.view.setScene(self.scene)
        self.view.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.view.viewport().installEventFilter(self)
        self.view.setAccessibleName("시간대별 일정표")
        layout.addWidget(self.view)
        self.redraw_timer = QTimer(self)
        self.redraw_timer.setSingleShot(True)
        self.redraw_timer.timeout.connect(self.redraw)

    def eventFilter(self, watched, event):
        if watched is self.view.viewport() and event.type() == QEvent.Type.Resize:
            self.redraw_timer.start(30)
        return super().eventFilter(watched, event)

    def set_items(self, days, occurrences, reset_scroll=False):
        changed = self.days != days
        self.days, self.occurrences = days, occurrences
        while self.header.count():
            item = self.header.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for day in days:
            caption = QLabel(f"{day.month}/{day.day} ( {'월화수목금토일'[day.weekday()]} )")
            caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.header.addWidget(caption, 1)
        while self.all_day_strip.count():
            item = self.all_day_strip.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        rows = max(
            (sum(value.all_day and value.appears_on(day) for value in occurrences) for day in days),
            default=0,
        )
        self.all_day_widget.setFixedHeight(4 + max(1, min(rows, 3)) * 24)
        caption = QLabel("종일")
        caption.setFixedWidth(46)
        self.all_day_strip.addWidget(caption)
        for day in days:
            cell = QWidget()
            box = QVBoxLayout(cell)
            box.setContentsMargins(2, 2, 2, 2)
            box.setSpacing(2)
            values = [value for value in occurrences if value.all_day and value.appears_on(day)]
            for value in values[:2]:
                entry = button(
                    value.title, lambda _checked=False, v=value: self.occurrence_clicked.emit(v)
                )
                entry.setObjectName("calendarEntry")
                entry.setFixedHeight(22)
                entry.setToolTip(escape(value.title))
                entry.setStyleSheet(f"border-left: 3px solid {value.color};")
                box.addWidget(entry)
            if len(values) > 2:
                more = button(
                    f"+ {len(values) - 2}개",
                    lambda _checked=False, d=day: self.day_selected.emit(d),
                )
                more.setObjectName("calendarMore")
                box.addWidget(more)
            box.addStretch()
            self.all_day_strip.addWidget(cell, 1)
        self.redraw()
        if changed or reset_scroll:
            self.view.verticalScrollBar().setValue(8 * 52)

    def redraw(self):
        if not self.days:
            return
        scroll = self.view.verticalScrollBar().value()
        self.scene.clear()
        width = max(320, self.view.viewport().width() - 2)
        gutter, step = 52, 52
        column = (width - gutter) / len(self.days)
        palette = QApplication.palette()
        dark = palette.color(QPalette.ColorRole.Window).lightness() < 128
        foreground = palette.color(QPalette.ColorRole.WindowText)
        background = palette.color(QPalette.ColorRole.Base)
        grid = palette.color(QPalette.ColorRole.Mid)
        self.scene.setBackgroundBrush(background)
        top = 4
        height = top + 24 * step
        self.scene.setSceneRect(0, 0, width, height)
        for index, day in enumerate(self.days):
            x = gutter + index * column
            self.scene.addLine(x, 0, x, height, QPen(grid, 0.6))
            midnight = datetime.combine(
                day, time(), self.occurrences[0].start.tzinfo if self.occurrences else None
            )
            entries, intervals = [], []
            for value in self.occurrences:
                if value.all_day or not value.appears_on(day):
                    continue
                start = max(value.start, midnight)
                end = min(value.end, midnight + timedelta(days=1))
                left = (start - midnight).total_seconds() / 60
                right = (end - midnight).total_seconds() / 60
                entries.append(value)
                intervals.append((left, right))
            for position in arrange_intervals(intervals):
                value = entries[position.index]
                lane_width = (column - 6) / position.lanes
                rect = QRectF(
                    x + 3 + position.lane * lane_width,
                    top + position.start / 60 * step,
                    max(8, lane_width - 3),
                    max(0.5, (position.end - position.start) / 60 * step - 1),
                )
                color = (
                    QColor(value.color).darker(160) if dark else QColor(value.color).lighter(185)
                )
                caption = ("완료 · " if value.completed else "") + value.title
                block = EventBlock(
                    rect, value, self.occurrence_clicked.emit, color, foreground, caption
                )
                self.scene.addItem(block)
        for hour in range(25):
            y = top + hour * step
            self.scene.addLine(gutter, y, width, y, QPen(grid, 0.6))
            if hour < 24:
                text = self.scene.addSimpleText(f"{hour:02}:00")
                text.setBrush(foreground)
                text.setPos(4, y)
        self.view.verticalScrollBar().setValue(scroll)
