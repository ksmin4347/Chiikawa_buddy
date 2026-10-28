import logging
from dataclasses import replace
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from PySide6.QtCore import QDate, QDateTime, QSignalBlocker, Qt, QTime
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDateEdit,
    QDateTimeEdit,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QRadioButton,
    QScrollArea,
    QTextEdit,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from desktop_buddy.models.planning import Record, Task, aware
from desktop_buddy.ui.common import button, label
from desktop_buddy.ui.repeat_editor import RepeatEditor


def qdatetime(value: datetime) -> QDateTime:
    return QDateTime(QDate(value.year, value.month, value.day), QTime(value.hour, value.minute))


def confirm_delete(parent, text: str) -> bool:
    box = QMessageBox(parent)
    box.setWindowTitle("삭제 확인")
    box.setTextFormat(Qt.TextFormat.PlainText)
    box.setText(text)
    box.setIcon(QMessageBox.Icon.Warning)
    yes = box.addButton("삭제", QMessageBox.ButtonRole.DestructiveRole)
    cancel = box.addButton("취소", QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(cancel)
    box.exec()
    return box.clickedButton() == yes


class ScopeDialog(QDialog):
    def __init__(self, occurrence, deleting=False, parent=None):
        super().__init__(parent)
        self.setWindowTitle("반복 항목 삭제" if deleting else "반복 항목 수정")
        self.setMinimumWidth(400)
        layout = QVBoxLayout(self)
        layout.addWidget(label(occurrence.title, "heading"))
        layout.addWidget(label("어느 범위에 적용할까요?"))
        self.choices = []
        for text, value in [
            ("이번 항목만", "one"),
            ("이번 항목부터 이후 모두", "following"),
            ("전체 반복", "all"),
        ]:
            radio = QRadioButton(text)
            self.choices.append((radio, value))
            layout.addWidget(radio)
        self.choices[0][0].setChecked(True)
        layout.addWidget(
            label(
                "이후 수정 시 기존 개별 수정·완료 내역은 보존해요."
                if not deleting
                else "선택한 범위의 항목과 관련 예외·완료 내역을 삭제해요.",
                "muted",
            )
        )
        row = QHBoxLayout()
        row.addWidget(button("취소", self.reject))
        row.addWidget(button("삭제" if deleting else "계속", self.accept, True))
        layout.addLayout(row)

    @property
    def scope(self):
        return next(value for radio, value in self.choices if radio.isChecked())


class ItemEditor(QDialog):
    def __init__(self, service, record: Record, commit, parent=None, single=False):
        super().__init__(parent)
        self.service, self.record, self.commit = service, record, commit
        self.is_task = isinstance(record, Task)
        self.setWindowTitle(
            ("할 일" if self.is_task else "일정") + (" 수정" if record.id else " 추가")
        )
        self.setMinimumWidth(540)
        self.resize(580, 740)
        outer = QVBoxLayout(self)
        area = QScrollArea()
        area.setWidgetResizable(True)
        content = QWidget()
        form = QFormLayout(content)
        form.setContentsMargins(18, 18, 18, 18)
        form.setVerticalSpacing(12)
        self.title_edit = QLineEdit(record.title)
        self.title_edit.setMaxLength(200)
        self.title_edit.setAccessibleName("제목")
        self.title_edit.setPlaceholderText("무엇을 할까요?")
        form.addRow("제목", self.title_edit)
        self.description = QTextEdit()
        self.description.setAcceptRichText(False)
        self.description.setPlainText(record.description)
        self.description.setMaximumHeight(80)
        self.description.setAccessibleName("메모")
        form.addRow("메모", self.description)
        if self.is_task:
            self.date_edit = QDateEdit(
                QDate(
                    record.scheduled_date.year,
                    record.scheduled_date.month,
                    record.scheduled_date.day,
                )
            )
            self.date_edit.setCalendarPopup(True)
            self.date_edit.setDisplayFormat("yyyy-MM-dd")
            self.date_edit.setAccessibleName("예정 날짜")
            form.addRow("예정 날짜", self.date_edit)
            self.start_enabled = QCheckBox("시작 시간 사용")
            self.start_enabled.setChecked(record.start_time is not None)
            initial_time = record.start_time or time(9)
            self.time_edit = QTimeEdit(QTime(initial_time.hour, initial_time.minute))
            self.time_edit.setDisplayFormat("HH:mm")
            row = QHBoxLayout()
            row.addWidget(self.start_enabled)
            row.addWidget(self.time_edit)
            form.addRow("시작 시간", row)
            self.start_enabled.toggled.connect(self.time_edit.setEnabled)
            self.time_edit.setEnabled(self.start_enabled.isChecked())
            self.due_enabled = QCheckBox("마감 사용")
            self.due_enabled.setChecked(record.due_at is not None)
            due = (
                aware(record.due_at, record.timezone)
                if record.due_at
                else record.start.replace(hour=18)
            )
            self.due_edit = QDateTimeEdit(qdatetime(due))
            self.due_edit.setCalendarPopup(True)
            self.due_edit.setDisplayFormat("yyyy-MM-dd HH:mm")
            row = QHBoxLayout()
            row.addWidget(self.due_enabled)
            row.addWidget(self.due_edit)
            form.addRow("마감", row)
            self.due_enabled.toggled.connect(self.due_edit.setEnabled)
            self.due_edit.setEnabled(self.due_enabled.isChecked())
            self.priority = QComboBox()
            for title, value in [("높음", 2), ("보통", 1), ("낮음", 0)]:
                self.priority.addItem(title, value)
            self.priority.setCurrentIndex(self.priority.findData(record.priority))
            form.addRow("우선순위", self.priority)
        else:
            self.all_day = QCheckBox("종일 일정")
            self.all_day.setChecked(record.all_day)
            form.addRow("", self.all_day)
            self.start_edit = QDateTimeEdit(qdatetime(record.start))
            initial_end = record.end - timedelta(days=1) if record.all_day else record.end
            self.end_edit = QDateTimeEdit(qdatetime(initial_end))
            for field in (self.start_edit, self.end_edit):
                field.setCalendarPopup(True)
            self.start_edit.setAccessibleName("일정 시작")
            self.end_edit.setAccessibleName("일정 종료")
            form.addRow("시작", self.start_edit)
            form.addRow("종료", self.end_edit)
            self.all_day.toggled.connect(self._event_format)
            self._event_format()
            form.addRow("", label("종일 일정은 선택한 종료 날짜까지 포함해요.", "muted"))
        self.category_combo = QComboBox()
        self.category_combo.setAccessibleName("카테고리")
        self._categories(record.category_id)
        service.changed.connect(self._refresh_categories)
        row = QHBoxLayout()
        row.addWidget(self.category_combo, 1)
        row.addWidget(button("관리", lambda: CategoryDialog(service, self).exec()))
        form.addRow("카테고리", row)
        self.reminder = QComboBox()
        for title, value in [
            ("알림 없음", None),
            ("정시", 0),
            ("5분 전", 5),
            ("10분 전", 10),
            ("30분 전", 30),
            ("1시간 전", 60),
            ("하루 전", 1440),
        ]:
            self.reminder.addItem(title, value)
        index = self.reminder.findData(record.reminder_minutes)
        if index < 0:
            self.reminder.addItem(f"{record.reminder_minutes}분 전", record.reminder_minutes)
            index = self.reminder.count() - 1
        self.reminder.setCurrentIndex(index)
        form.addRow("알림", self.reminder)
        if self.is_task:
            form.addRow("", label("할 일 알림은 마감 시각을 기준으로 알려줘요.", "muted"))
        self.repeat = RepeatEditor(record.recurrence, record.start)
        self.repeat.setEnabled(not single)
        form.addRow(self.repeat)
        if single:
            form.addRow(label("이번 항목만 바꿔요. 나머지 반복은 그대로 유지돼요.", "muted"))
        form.addRow(label("앱이 실행 중일 때만 알림을 받을 수 있어요.", "muted"))
        area.setWidget(content)
        outer.addWidget(area, 1)
        self.error_label = label("")
        self.error_label.setStyleSheet("color: #b03b35;")
        outer.addWidget(self.error_label)
        buttons = QDialogButtonBox()
        buttons.addButton("취소", QDialogButtonBox.ButtonRole.RejectRole)
        self.save_button = buttons.addButton("저장", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self._submit)
        outer.addWidget(buttons)
        self.title_edit.setFocus()

    def _event_format(self, *_args) -> None:
        value = "yyyy-MM-dd" if self.all_day.isChecked() else "yyyy-MM-dd HH:mm"
        self.start_edit.setDisplayFormat(value)
        self.end_edit.setDisplayFormat(value)

    def _categories(self, selected=None) -> None:
        blocker = QSignalBlocker(self.category_combo)
        self.category_combo.clear()
        self.category_combo.addItem("분류 없음", None)
        for category in self.service.categories():
            self.category_combo.addItem(category.name, category.id)
        self.category_combo.setCurrentIndex(max(0, self.category_combo.findData(selected)))
        del blocker

    def _refresh_categories(self) -> None:
        self._categories(self.category_combo.currentData())

    def value(self) -> Record:
        zone = ZoneInfo(self.record.timezone)
        if self.is_task:
            record = replace(
                self.record,
                title=self.title_edit.text(),
                description=self.description.toPlainText(),
                scheduled_date=self.date_edit.date().toPython(),
                start_time=self.time_edit.time().toPython()
                if self.start_enabled.isChecked()
                else None,
                due_at=self.due_edit.dateTime().toPython().replace(tzinfo=zone)
                if self.due_enabled.isChecked()
                else None,
                priority=self.priority.currentData(),
                category_id=self.category_combo.currentData(),
                reminder_minutes=self.reminder.currentData(),
            )
        else:
            start = self.start_edit.dateTime().toPython().replace(tzinfo=zone)
            end = self.end_edit.dateTime().toPython().replace(tzinfo=zone)
            if self.all_day.isChecked():
                start = start.replace(hour=0, minute=0, second=0, microsecond=0)
                end = end.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
            record = replace(
                self.record,
                title=self.title_edit.text(),
                description=self.description.toPlainText(),
                start_at=start,
                end_at=end,
                all_day=self.all_day.isChecked(),
                category_id=self.category_combo.currentData(),
                reminder_minutes=self.reminder.currentData(),
            )
        return replace(record, recurrence=self.repeat.rule(record.start))

    def _submit(self) -> None:
        try:
            self.commit(self.value())
        except (ValueError, LookupError) as error:
            self.error_label.setText(str(error))
        except Exception as error:
            logging.getLogger(__name__).warning("Planning save failed (%s)", type(error).__name__)
            self.error_label.setText(
                "저장하지 못했어요. 입력 내용을 유지했으니 저장 공간을 확인하고 다시 시도해 주세요."
            )
        else:
            self.accept()


class CategoryDialog(QDialog):
    def __init__(self, service, parent=None):
        super().__init__(parent)
        self.service, self.selected_id, self.color = service, None, "#4e8061"
        self.setWindowTitle("카테고리 관리")
        self.resize(420, 460)
        layout = QVBoxLayout(self)
        layout.addWidget(label("카테고리", "heading"))
        self.items = QListWidget()
        self.items.currentRowChanged.connect(self._select)
        layout.addWidget(self.items)
        self.name_edit = QLineEdit()
        self.name_edit.setMaxLength(30)
        self.name_edit.setPlaceholderText("카테고리 이름")
        layout.addWidget(self.name_edit)
        self.color_button = button("색상 선택", self._choose_color)
        layout.addWidget(self.color_button)
        row = QHBoxLayout()
        row.addWidget(button("새 항목", self._new))
        row.addWidget(button("저장", self._save, True))
        row.addWidget(button("삭제", self._delete))
        layout.addLayout(row)
        self.error_label = label("")
        layout.addWidget(self.error_label)
        layout.addWidget(button("닫기", self.accept))
        self._reload()

    def _reload(self):
        self.categories = self.service.categories()
        self.items.clear()
        for category in self.categories:
            self.items.addItem(category.name)
        self._new()

    def _new(self):
        self.items.setCurrentRow(-1)
        self.selected_id = None
        self.name_edit.clear()
        self.color = "#4e8061"
        self._color_style()

    def _select(self, index):
        if index >= 0:
            category = self.categories[index]
            self.selected_id, self.color = category.id, category.color
            self.name_edit.setText(category.name)
            self._color_style()

    def _color_style(self):
        foreground = "#ffffff" if QColor(self.color).lightness() < 145 else "#18251d"
        self.color_button.setStyleSheet(f"background:{self.color};color:{foreground};")

    def _choose_color(self):
        color = QColorDialog.getColor(QColor(self.color), self, "카테고리 색상")
        if color.isValid():
            self.color = color.name()
            self._color_style()

    def _save(self):
        try:
            self.service.save_category(self.name_edit.text(), self.color, self.selected_id)
            self._reload()
            self.error_label.setText("저장했어요.")
        except Exception:
            self.error_label.setText("이름이 겹치지 않는지, 저장 공간이 충분한지 확인해 주세요.")

    def _delete(self):
        if self.selected_id is not None and confirm_delete(
            self, "이 카테고리를 삭제할까요? 등록된 할 일과 일정은 분류 없이 유지돼요."
        ):
            try:
                self.service.delete_category(self.selected_id)
                self._reload()
            except Exception:
                self.error_label.setText("삭제하지 못했어요. 다시 시도해 주세요.")
