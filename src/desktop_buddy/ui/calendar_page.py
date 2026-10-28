import calendar
from datetime import timedelta
from html import escape

from PySide6.QtCore import QDate, QSignalBlocker, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDateEdit,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QListWidget,
    QListWidgetItem,
    QStackedWidget,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from desktop_buddy.ui.common import button, label
from desktop_buddy.ui.timeline import TimelineView


class DayCell(QFrame):
    selected = Signal(object)
    add_requested = Signal(object)
    occurrence_clicked = Signal(object)

    def __init__(self, day, selected, today, active_month, occurrences):
        super().__init__()
        self.day = day
        self.setObjectName("dayCell")
        self.setProperty("selected", day == selected)
        self.setProperty("outside", day.month != active_month)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 2, 5, 2)
        layout.setSpacing(1)
        day_button = button(
            str(day.day) + (" · 오늘" if day == today else ""), lambda: self.selected.emit(day)
        )
        day_button.setObjectName("dayNumber")
        day_button.setFixedHeight(22)
        day_button.setToolTip(day.isoformat())
        if day.weekday() == 6:
            day_button.setProperty("sunday", True)
        elif day.weekday() == 5:
            day_button.setProperty("saturday", True)
        layout.addWidget(day_button)
        if occurrences:
            value = occurrences[0]
            prefix = (
                "완료 · "
                if value.completed
                else (value.start.strftime("%H:%M ") if not value.all_day else "")
            )
            text = prefix + value.title
            entry = button(text, lambda: self.occurrence_clicked.emit(value))
            entry.setObjectName("calendarEntry")
            entry.setFixedHeight(20)
            entry.setToolTip(escape(text))
            entry.setStyleSheet(f"border-left:3px solid {value.color};")
            layout.addWidget(entry)
            if len(occurrences) > 1:
                more = button(f"+ {len(occurrences) - 1}개 더", lambda: self.selected.emit(day))
                more.setObjectName("calendarMore")
                more.setFixedHeight(18)
                layout.addWidget(more)
        layout.addStretch()

    def mousePressEvent(self, event):
        self.selected.emit(self.day)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.add_requested.emit(self.day)
        event.accept()


class CalendarPage(QWidget):
    def __init__(self, service, settings, actions):
        super().__init__()
        self.service, self.settings, self.actions = service, settings, actions
        self.setObjectName("page")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(10)
        header = QHBoxLayout()
        header.addWidget(label("캘린더", "title"), 1)
        header.addWidget(button("할 일 추가", lambda: actions.add_task(self.day)))
        header.addWidget(button("일정 추가", lambda: actions.add_event(self.day), True))
        layout.addLayout(header)
        self.period_label = label("", "heading")
        self.date_edit = QDateEdit(
            QDate(service.today().year, service.today().month, service.today().day)
        )
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("yyyy-MM-dd")
        self.date_edit.setAccessibleName("캘린더 날짜 이동")
        self.date_edit.dateChanged.connect(self.refresh)
        row = QHBoxLayout()
        previous = button("‹", lambda: self.navigate(-1))
        previous.setToolTip("이전 기간")
        previous.setAccessibleName("이전 기간")
        following = button("›", lambda: self.navigate(1))
        following.setToolTip("다음 기간")
        following.setAccessibleName("다음 기간")
        row.addWidget(previous)
        row.addWidget(button("오늘", self.go_today))
        row.addWidget(following)
        row.addWidget(self.period_label, 1)
        self.mode_combo = QComboBox()
        for text, value in [("월간", "month"), ("주간", "week"), ("일간", "day")]:
            self.mode_combo.addItem(text, value)
        self.mode_combo.setAccessibleName("캘린더 보기")
        self.mode_combo.currentIndexChanged.connect(self.refresh)
        row.addWidget(self.mode_combo)
        row.addWidget(self.date_edit)
        layout.addLayout(row)
        self.views = QStackedWidget()
        self.month_table = QTableWidget(6, 7)
        self.month_table.setAccessibleName("월간 캘린더")
        self.month_table.verticalHeader().hide()
        self.month_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.month_table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.month_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.month_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.month_table.setMinimumHeight(300)
        self.views.addWidget(self.month_table)
        self.timeline = TimelineView()
        self.timeline.occurrence_clicked.connect(actions.edit)
        self.timeline.day_selected.connect(self.select_day)
        self.views.addWidget(self.timeline)
        layout.addWidget(self.views, 1)
        self.detail_label = label("", "eyebrow")
        layout.addWidget(self.detail_label)
        self.details = QListWidget()
        self.details.setAccessibleName("선택 날짜의 전체 항목")
        self.details.setMaximumHeight(112)
        self.details.setMinimumHeight(65)
        self.details.itemDoubleClicked.connect(
            lambda item: actions.edit(item.data(Qt.ItemDataRole.UserRole))
        )
        self.details.currentItemChanged.connect(self._selection)
        layout.addWidget(self.details)
        row = QHBoxLayout()
        self.edit_button = button("수정", lambda: actions.edit(self.selected()))
        self.delete_button = button("삭제", lambda: actions.delete(self.selected()))
        self.complete_button = button("완료 / 취소", self._complete)
        for widget in [self.edit_button, self.delete_button, self.complete_button]:
            row.addWidget(widget)
        row.addStretch()
        row.addWidget(label("반복 항목 지원 · 날짜 빈 곳 더블클릭으로 일정 추가", "muted"))
        layout.addLayout(row)
        self.error_label = label("", "muted")
        layout.addWidget(self.error_label)
        service.changed.connect(self.refresh)
        settings.changed.connect(self.refresh)
        self.refresh()

    @property
    def day(self):
        return self.date_edit.date().toPython()

    def select_day(self, day):
        self.date_edit.setDate(QDate(day.year, day.month, day.day))

    def go_today(self):
        self.select_day(self.service.today())

    def navigate(self, direction):
        value = self.date_edit.date()
        mode = self.mode_combo.currentData()
        value = (
            value.addMonths(direction)
            if mode == "month"
            else value.addDays(direction * (7 if mode == "week" else 1))
        )
        self.date_edit.setDate(value)

    def selected(self):
        item = self.details.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _selection(self, *_args):
        selected = self.selected()
        self.edit_button.setEnabled(selected is not None)
        self.delete_button.setEnabled(selected is not None)
        self.complete_button.setEnabled(selected is not None and selected.kind == "task")

    def _complete(self):
        selected = self.selected()
        if selected and selected.kind == "task":
            try:
                self.service.set_completed(selected, not selected.completed)
            except Exception:
                self.error_label.setText("완료 상태를 저장하지 못했어요.")

    def refresh(self, *_args):
        day = self.day
        mode = self.mode_combo.currentData()
        try:
            if mode == "month":
                weeks = calendar.Calendar(self.settings.current.week_start).monthdatescalendar(
                    day.year, day.month
                )
                while len(weeks) < 6:
                    weeks.append([weeks[-1][-1] + timedelta(days=i) for i in range(1, 8)])
                start, end = weeks[0][0], weeks[-1][-1] + timedelta(days=1)
                occurrences = self.service.occurrences(start, end)
                headers = ["월화수목금토일"[value.weekday()] for value in weeks[0]]
                self.month_table.setHorizontalHeaderLabels(headers)
                for row, week in enumerate(weeks):
                    for column, value in enumerate(week):
                        entries = [item for item in occurrences if item.appears_on(value)]
                        cell = DayCell(value, day, self.service.today(), day.month, entries)
                        cell.selected.connect(self.select_day)
                        cell.add_requested.connect(self.actions.add_event)
                        cell.occurrence_clicked.connect(self.actions.edit)
                        self.month_table.setCellWidget(row, column, cell)
                self.views.setCurrentIndex(0)
                self.period_label.setText(f"{day.year}년 {day.month}월")
            else:
                first = (
                    day - timedelta(days=(day.weekday() - self.settings.current.week_start) % 7)
                    if mode == "week"
                    else day
                )
                days = [first + timedelta(days=i) for i in range(7 if mode == "week" else 1)]
                occurrences = self.service.occurrences(first, days[-1] + timedelta(days=1))
                self.views.setCurrentIndex(1)
                self.timeline.set_items(days, occurrences)
                self.period_label.setText(
                    f"{first:%m.%d} ~ {days[-1]:%m.%d}" if mode == "week" else f"{day:%Y.%m.%d}"
                )
            selected_items = self.service.occurrences(day, day + timedelta(days=1))
        except Exception:
            self.error_label.setText(
                "캘린더를 불러오지 못했어요. 저장 공간과 날짜를 확인해 주세요."
            )
            return
        self.error_label.clear()
        self.detail_label.setText(
            f"{day.month}월 {day.day}일 · {len(selected_items)}개 항목 · 더블클릭으로 상세 수정"
        )
        previous = self.selected()
        old_key = (previous.kind, previous.item_id, previous.key) if previous else None
        blocker = QSignalBlocker(self.details)
        self.details.clear()
        chosen = 0
        for index, value in enumerate(selected_items):
            when = "종일" if value.all_day else value.start.strftime("%H:%M")
            if value.start.date() != day:
                when = "이전 날부터"
            prefix = ("완료 · " if value.completed else "할 일 · ") if value.kind == "task" else ""
            text = f"{when}  {prefix}{value.title}" + (" · 반복" if value.repeated else "")
            if value.category:
                text += f"  · {value.category.name}"
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, value)
            item.setToolTip(escape(value.record.description or value.title))
            self.details.addItem(item)
            if (value.kind, value.item_id, value.key) == old_key:
                chosen = index
        if not selected_items:
            self.details.addItem("등록된 일정이나 할 일이 없어요.")
        else:
            self.details.setCurrentRow(chosen)
        del blocker
        self._selection()
