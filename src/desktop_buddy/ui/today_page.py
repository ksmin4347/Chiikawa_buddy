from datetime import timedelta

from PySide6.QtCore import QDate, QSignalBlocker, Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDateEdit,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QProgressBar,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from desktop_buddy.models.planning import Task
from desktop_buddy.ui.common import button, label


class TodayPage(QWidget):
    def __init__(self, service, actions):
        super().__init__()
        self.service, self.actions = service, actions
        self.setObjectName("page")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(26, 24, 26, 24)
        layout.setSpacing(14)
        header = QHBoxLayout()
        header.addWidget(label("오늘의 계획", "title"), 1)
        header.addWidget(button("상세 추가", lambda: self.actions.add_task(self.day)))
        layout.addLayout(header)
        self.summary = label("", "muted")
        layout.addWidget(self.summary)
        row = QHBoxLayout()
        self.date_edit = QDateEdit(QDate.currentDate())
        self.date_edit.setDate(
            QDate(service.today().year, service.today().month, service.today().day)
        )
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("yyyy-MM-dd (ddd)")
        self.date_edit.setAccessibleName("계획 날짜")
        self.date_edit.dateChanged.connect(self.refresh)
        row.addWidget(self.date_edit)
        row.addWidget(button("오늘", self.go_today))
        self.filter_combo = QComboBox()
        for text, value in [
            ("모두", "all"),
            ("미완료", "incomplete"),
            ("완료", "completed"),
            ("이전 미완료", "overdue"),
        ]:
            self.filter_combo.addItem(text, value)
        self.filter_combo.setAccessibleName("할 일 상태 필터")
        self.filter_combo.currentIndexChanged.connect(self.refresh)
        row.addWidget(self.filter_combo)
        self.category_filter = QComboBox()
        self.category_filter.setAccessibleName("카테고리 필터")
        self.category_filter.currentIndexChanged.connect(self.refresh)
        row.addWidget(self.category_filter, 1)
        layout.addLayout(row)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setFixedHeight(18)
        layout.addWidget(self.progress)
        row = QHBoxLayout()
        self.quick_title = QLineEdit()
        self.quick_title.setMaxLength(200)
        self.quick_title.setPlaceholderText("제목만 적고 Enter를 눌러 빠르게 추가해요")
        self.quick_title.setAccessibleName("빠른 할 일 제목")
        self.quick_title.returnPressed.connect(self.quick_add)
        row.addWidget(self.quick_title, 1)
        row.addWidget(button("추가", self.quick_add, True))
        layout.addLayout(row)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["완료", "할 일", "시간 · 마감", "카테고리", "우선순위"]
        )
        self.table.verticalHeader().hide()
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for column, width in [(0, 48), (2, 144), (3, 90), (4, 76)]:
            self.table.setColumnWidth(column, width)
        self.table.setAccessibleName("할 일 목록")
        self.table.itemChanged.connect(self._check_changed)
        self.table.cellDoubleClicked.connect(
            lambda row, col: self.actions.edit(self._at(row)) if col else None
        )
        layout.addWidget(self.table, 1)
        self.empty_label = label("할 일이 없어요. 위에서 오늘 할 일을 하나 적어 보세요.", "muted")
        layout.addWidget(self.empty_label)
        row = QHBoxLayout()
        self.edit_button = button("수정", lambda: self.actions.edit(self.selected()))
        self.move_button = button(
            "날짜 바꾸기", lambda: self.actions.edit(self.selected(), focus_date=True)
        )
        self.delete_button = button("삭제", lambda: self.actions.delete(self.selected()))
        for widget in [self.edit_button, self.move_button, self.delete_button]:
            row.addWidget(widget)
        row.addStretch()
        row.addWidget(button("카테고리", actions.manage_categories))
        layout.addLayout(row)
        self.error_label = label("", "muted")
        layout.addWidget(self.error_label)
        self.table.itemSelectionChanged.connect(self._selection)
        service.changed.connect(self.refresh)
        self.refresh()

    @property
    def day(self):
        return self.date_edit.date().toPython()

    def roll_day(self, previous, current) -> None:
        if self.day == previous:
            self.date_edit.setDate(QDate(current))

    def go_today(self):
        day = self.service.today()
        self.date_edit.setDate(QDate(day.year, day.month, day.day))

    def quick_add(self):
        try:
            self.service.save(Task(self.quick_title.text(), self.day))
        except (ValueError, LookupError) as error:
            self.error_label.setText(str(error))
        except Exception:
            self.error_label.setText("추가하지 못했어요. 입력한 제목은 유지했어요.")
        else:
            self.quick_title.clear()
            self.error_label.setText("추가했어요.")
            self.quick_title.setFocus()

    def _at(self, row):
        item = self.table.item(row, 1)
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def selected(self):
        return self._at(self.table.currentRow())

    def _selection(self):
        enabled = self.selected() is not None
        for widget in [self.edit_button, self.move_button, self.delete_button]:
            widget.setEnabled(enabled)

    def _check_changed(self, item):
        if item.column() != 0:
            return
        occurrence = self._at(item.row())
        completed = item.checkState() == Qt.CheckState.Checked
        if occurrence:
            QTimer.singleShot(0, lambda: self._complete(occurrence, completed))

    def _complete(self, occurrence, completed):
        try:
            self.service.set_completed(occurrence, completed)
        except Exception:
            self.error_label.setText("완료 상태를 저장하지 못했어요. 다시 시도해 주세요.")
            self.refresh()

    def refresh(self, *_args):
        selected = self.selected()
        selected_key = (selected.item_id, selected.key) if selected else None
        blocker = QSignalBlocker(self.category_filter)
        category_id = self.category_filter.currentData()
        self.category_filter.clear()
        self.category_filter.addItem("모든 분류", None)
        for category in self.service.categories():
            self.category_filter.addItem(category.name, category.id)
        self.category_filter.setCurrentIndex(max(0, self.category_filter.findData(category_id)))
        del blocker
        try:
            all_items = self.service.occurrences(self.day, self.day + timedelta(days=1), "task")
            filter_kind = self.filter_combo.currentData()
            items = self.service.overdue_tasks(self.day) if filter_kind == "overdue" else all_items
            if filter_kind == "completed":
                items = [item for item in items if item.completed]
            elif filter_kind == "incomplete":
                items = [item for item in items if not item.completed]
            category_id = self.category_filter.currentData()
            if category_id is not None:
                items = [item for item in items if item.record.category_id == category_id]
        except Exception:
            self.error_label.setText("목록을 불러오지 못했어요. 저장 공간을 확인해 주세요.")
            return
        completed = sum(item.completed for item in all_items)
        self.progress.setValue(round(completed / len(all_items) * 100) if all_items else 0)
        self.summary.setText(
            f"{self.day.month}월 {self.day.day}일 · {len(all_items)}개 중 {completed}개 완료"
            + (f" · 이전 미완료 {len(items)}개" if filter_kind == "overdue" else "")
        )
        blocker = QSignalBlocker(self.table)
        self.table.setRowCount(len(items))
        chosen_row = -1
        for row, occurrence in enumerate(items):
            check = QTableWidgetItem()
            check.setFlags(
                Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
                | Qt.ItemFlag.ItemIsUserCheckable
            )
            check.setCheckState(
                Qt.CheckState.Checked if occurrence.completed else Qt.CheckState.Unchecked
            )
            self.table.setItem(row, 0, check)
            title = occurrence.title + (" · 반복" if occurrence.repeated else "")
            if filter_kind == "overdue":
                title = f"{occurrence.start:%m.%d}  {title}"
            item = QTableWidgetItem(title)
            item.setData(Qt.ItemDataRole.UserRole, occurrence)
            item.setToolTip(occurrence.record.description or occurrence.title)
            font = item.font()
            font.setStrikeOut(occurrence.completed)
            item.setFont(font)
            self.table.setItem(row, 1, item)
            record = occurrence.record
            when = record.start_time.strftime("%H:%M") if record.start_time else "시간 없음"
            if record.due_at:
                due = record.due_at.astimezone(self.service.zone)
                when += f"\n마감 {due:%m.%d %H:%M}"
            self.table.setItem(row, 2, QTableWidgetItem(when))
            category = QTableWidgetItem(
                occurrence.category.name if occurrence.category else "분류 없음"
            )
            category.setForeground(QColor(occurrence.color))
            self.table.setItem(row, 3, category)
            self.table.setItem(
                row, 4, QTableWidgetItem({0: "낮음", 1: "보통", 2: "높음"}[record.priority])
            )
            self.table.setRowHeight(row, 58)
            if (occurrence.item_id, occurrence.key) == selected_key:
                chosen_row = row
        del blocker
        if chosen_row >= 0:
            self.table.selectRow(chosen_row)
        elif items:
            self.table.selectRow(0)
        self.empty_label.setVisible(not items)
        self._selection()
