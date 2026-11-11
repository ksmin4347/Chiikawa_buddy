import threading
from datetime import timedelta
from pathlib import Path

from PySide6.QtCore import QDate, QObject, Qt, Signal, Slot
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDateEdit,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from desktop_buddy.calendar.file_io import file_token, read_calendar, write_calendar
from desktop_buddy.calendar.ics_codec import parse_calendar, serialize_calendar
from desktop_buddy.models.calendar_transfer import CalendarFileError
from desktop_buddy.services.calendar_transfer import CalendarTransferService, kind_of
from desktop_buddy.services.command_executor import describe
from desktop_buddy.ui.common import WrappedStatus, button, fit_window, label, scroll_page


class FileSignals(QObject):
    finished = Signal(int, object, str)


class FileJob:
    def __init__(self, token, action, signals):
        self.cancelled = threading.Event()
        self.token, self.action, self.signals = token, action, signals
        self.thread = threading.Thread(target=self._run, daemon=True, name="buddy-calendar-file")

    def start(self):
        self.thread.start()

    def _run(self):
        result, error = None, ""
        try:
            result = self.action(self.cancelled.is_set)
        except CalendarFileError as failure:
            error = str(failure)
        except Exception:
            error = "파일을 읽거나 저장하지 못했어요. 파일 위치·권한·형식을 확인해 주세요."
        try:
            self.signals.finished.emit(self.token, result, error)
        except RuntimeError:
            pass


def table(name: str) -> QTableWidget:
    view = QTableWidget(0, 5)
    view.setHorizontalHeaderLabels(("선택", "종류", "제목", "날짜/시각", "상태"))
    view.setAccessibleName(name)
    view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    view.setMinimumHeight(100)
    view.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    for column, width in enumerate((44, 60, 180, 180, 190)):
        view.setColumnWidth(column, width)
    return view


class CalendarTransferDialog(QDialog):
    def __init__(self, planning, parent=None):
        super().__init__(parent)
        self.transfer = CalendarTransferService(planning)
        self._job = None
        self._counter = 0
        self._active = None
        self._closed = False
        self._purpose = ""
        self.file_path = None
        self.import_plan = self.export_plan = None
        self.signals = FileSignals(self)
        self.signals.finished.connect(self._finished, Qt.ConnectionType.QueuedConnection)
        self.setWindowTitle("먼작귀 · ICS 파일 교환")
        self.resize(760, 640)
        outer = QVBoxLayout(self)
        container = QWidget()
        body = QVBoxLayout(container)
        body.addWidget(label("ICS 파일 교환", "heading"))
        body.addWidget(label("선택한 파일을 미리 보고, 선택한 항목만 계획에 반영해요.", "muted"))
        dates = QHBoxLayout()
        self.start = QDateEdit(QDate(planning.today()))
        self.end = QDateEdit(QDate(planning.today() + timedelta(days=30)))
        for widget, name in (
            (self.start, "파일 교환 시작 날짜"),
            (self.end, "파일 교환 마지막 날짜"),
        ):
            widget.setCalendarPopup(True)
            widget.setDisplayFormat("yyyy-MM-dd")
            widget.setDateRange(QDate(1900, 1, 1), QDate(2100, 12, 31))
            widget.setAccessibleName(name)
        dates.addWidget(QLabel("기간"))
        dates.addWidget(self.start)
        dates.addWidget(QLabel("~"))
        dates.addWidget(self.end)
        body.addLayout(dates)
        body.addWidget(
            label(
                "1~366일 · 반복은 이 기간의 개별 항목으로 교환해요. "
                "시간대 없는 시각은 파일의 시간대 또는 서울로 해석해요.",
                "muted",
            )
        )
        self.tabs = QTabWidget()
        body.addWidget(self.tabs)
        self._make_import()
        self._make_export()
        self.status = WrappedStatus()
        self.status.setAccessibleName("ICS 파일 처리 상태")
        self.status.setText("파일을 선택하거나 내보내기 미리보기를 시작해 주세요.")
        body.addWidget(self.status)
        outer.addWidget(scroll_page(container))
        controls = QHBoxLayout()
        controls.addWidget(self.import_apply_button)
        controls.addWidget(self.export_save_button)
        self.cancel_job_button = button("파일 작업 취소", self._cancel_job)
        self.cancel_job_button.setEnabled(False)
        controls.addWidget(self.cancel_job_button)
        controls.addWidget(button("닫기", self.reject))
        outer.addLayout(controls)
        self.tabs.currentChanged.connect(self._show_primary)
        self._show_primary(0)
        self.start.dateChanged.connect(self._invalidate)
        self.end.dateChanged.connect(self._invalidate)
        self.source.textChanged.connect(self._invalidate)
        self.export_kind.currentIndexChanged.connect(self._invalidate)
        self.import_table.itemChanged.connect(self._selection_changed)
        self.export_table.itemChanged.connect(self._selection_changed)
        self.import_table.itemSelectionChanged.connect(self._import_detail)
        self.export_table.itemSelectionChanged.connect(self._export_detail)
        for widget in self.findChildren(type(self.import_apply_button)):
            widget.setAutoDefault(False)

    def _make_import(self):
        page = QWidget()
        body = QVBoxLayout(page)
        body.addWidget(label("출처 이름 · 같은 캘린더를 다시 가져올 때 같은 이름을 사용하세요."))
        self.source = QLineEdit("개인 캘린더")
        self.source.setMaxLength(81)
        self.source.setAccessibleName("ICS 가져오기 출처 이름")
        body.addWidget(self.source)
        self.path_display = QLineEdit()
        self.path_display.setReadOnly(True)
        self.path_display.setAccessibleName("선택한 ICS 파일")
        body.addWidget(self.path_display)
        row = QHBoxLayout()
        self.choose_button = button("ICS 파일 선택", self._choose)
        self.import_preview_button = button("미리보기 다시", self._load)
        self.import_preview_button.setEnabled(False)
        row.addWidget(self.choose_button)
        row.addWidget(self.import_preview_button)
        body.addLayout(row)
        self.import_table = table("ICS 가져오기 미리보기 항목")
        body.addWidget(self.import_table)
        self.import_detail = QPlainTextEdit()
        self.import_detail.setReadOnly(True)
        self.import_detail.setMinimumHeight(80)
        self.import_detail.setMaximumHeight(160)
        self.import_detail.setAccessibleName("ICS 가져오기 항목 상세와 안내")
        body.addWidget(self.import_detail)
        self.import_apply_button = button("선택 항목 가져오기", self._apply, True)
        self.import_apply_button.setEnabled(False)
        body.addWidget(
            label(
                "중복은 건너뛰고, 갱신·충돌·시간 겹침은 직접 선택해야 해요. "
                "기존 항목은 파일에서 사라져도 자동 삭제하지 않아요.",
                "muted",
            )
        )
        self.tabs.addTab(page, "가져오기")

    def _make_export(self):
        page = QWidget()
        body = QVBoxLayout(page)
        self.export_kind = QComboBox()
        for text, kind in (("일정만", "event"), ("할 일만", "task"), ("할 일과 일정", None)):
            self.export_kind.addItem(text, kind)
        self.export_kind.setAccessibleName("ICS 내보내기 항목 종류")
        body.addWidget(self.export_kind)
        self.export_preview_button = button("내보내기 미리보기", self._preview_export)
        body.addWidget(self.export_preview_button)
        self.export_table = table("ICS 내보내기 미리보기 항목")
        body.addWidget(self.export_table)
        self.export_detail = QPlainTextEdit()
        self.export_detail.setReadOnly(True)
        self.export_detail.setMinimumHeight(80)
        self.export_detail.setMaximumHeight(160)
        self.export_detail.setAccessibleName("ICS 내보내기 항목 상세")
        body.addWidget(self.export_detail)
        self.export_save_button = button("선택 항목 ICS 저장", self._save, True)
        self.export_save_button.setEnabled(False)
        body.addWidget(
            label(
                "제목·메모·시각·할 일 완료 상태를 포함해요. "
                "반복 규칙·분류·알람·공부 기록은 포함하지 않아요. "
                "시작 시각 없는 마감 할 일은 00:00 시작으로 기록해요.",
                "muted",
            )
        )
        self.tabs.addTab(page, "내보내기")

    def _show_primary(self, index):
        self.import_apply_button.setVisible(index == 0)
        self.export_save_button.setVisible(index == 1)

    def _dates(self):
        return self.start.date().toPython(), self.end.date().toPython() + timedelta(days=1)

    def _invalidate(self, *args):
        if self._job is not None:
            self._active = None
            self._job.cancelled.set()
        self.transfer.invalidate()
        self.import_plan = self.export_plan = None
        self.import_table.setRowCount(0)
        self.export_table.setRowCount(0)
        self.import_detail.clear()
        self.export_detail.clear()
        self.import_apply_button.setEnabled(False)
        self.export_save_button.setEnabled(False)
        self.status.setText("조건이 바뀌었어요. 미리보기를 다시 만들어 주세요.")

    def _busy(self, busy):
        for widget in (
            self.start,
            self.end,
            self.source,
            self.choose_button,
            self.import_preview_button,
            self.export_preview_button,
            self.export_kind,
            self.import_table,
            self.export_table,
        ):
            widget.setEnabled(not busy)
        self.import_preview_button.setEnabled(not busy and self.file_path is not None)
        self.cancel_job_button.setEnabled(busy)
        self._selection_changed()

    def _dispatch(self, purpose, action):
        if self._job is not None or self._closed:
            return
        self._counter += 1
        self._active = self._counter
        self._purpose = purpose
        self._job = FileJob(self._counter, action, self.signals)
        self._busy(True)
        self.status.setText("파일을 처리하고 있어요. 계획·타이머는 계속 사용할 수 있어요.")
        try:
            self._job.start()
        except Exception:
            self._job = None
            self._active = None
            self._busy(False)
            self.status.setText("파일 작업을 시작하지 못했어요. 다시 시도해 주세요.")

    def _cancel_job(self):
        self._active = None
        if self._job is not None:
            self._job.cancelled.set()
        self.status.setText("취소를 요청했어요. 이미 저장된 파일은 자동 삭제하지 않아요.")

    def _choose(self):
        path, _ = QFileDialog.getOpenFileName(self, "가져올 ICS 파일", "", "iCalendar (*.ics)")
        if not path:
            return
        self._invalidate()
        self.file_path = Path(path)
        self.path_display.setText(path)
        self.path_display.setCursorPosition(0)
        self.import_preview_button.setEnabled(True)
        self._load()

    def _load(self):
        if self.file_path is None:
            return
        self._invalidate()
        start, end = self._dates()
        path = self.file_path
        self._dispatch("import", lambda stop: parse_calendar(read_calendar(path), start, end, stop))

    @Slot(int, object, str)
    def _finished(self, token, result, error):
        if self._job is None or self._job.token != token:
            return
        self._job = None
        if self._closed:
            return
        self._busy(False)
        if self._active != token:
            return
        self._active = None
        if error:
            self.status.setText(error)
            return
        try:
            if self._purpose == "import":
                start, end = self._dates()
                self.import_plan = self.transfer.preview_import(
                    result, self.source.text(), start, end
                )
                self._fill(
                    self.import_table,
                    [
                        (r.entry, r.status, r.action != "", r.status == "새 항목")
                        for r in self.import_plan.rows
                    ],
                )
                self.import_detail.setPlainText("\n".join(self.import_plan.notes))
                if self.import_table.rowCount():
                    self.import_table.setCurrentCell(0, 2)
                self.status.setText(
                    f"가져오기 미리보기 {len(self.import_plan.rows)}개. 아직 저장하지 않았어요."
                )
            else:
                self.status.setText("선택한 항목을 ICS 파일로 저장했어요.")
        except CalendarFileError as failure:
            self.status.setText(str(failure))
        except Exception:
            self.status.setText("미리보기를 만들지 못했어요. 파일과 저장 상태를 확인해 주세요.")
        self._selection_changed()

    def _fill(self, view, rows):
        view.blockSignals(True)
        view.setRowCount(len(rows))
        for index, (entry, status, allowed, checked) in enumerate(rows):
            record = entry.record
            columns = (
                "",
                "할 일" if kind_of(record) == "task" else "일정",
                record.title,
                record.start.astimezone(self.transfer.planning.zone).strftime("%Y-%m-%d %H:%M"),
                status,
            )
            for column, value in enumerate(columns):
                item = QTableWidgetItem(value)
                if column == 0:
                    item.setFlags(
                        Qt.ItemFlag.ItemIsEnabled
                        | Qt.ItemFlag.ItemIsSelectable
                        | (Qt.ItemFlag.ItemIsUserCheckable if allowed else Qt.ItemFlag.NoItemFlags)
                    )
                    if allowed:
                        item.setCheckState(
                            Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
                        )
                view.setItem(index, column, item)
        view.blockSignals(False)
        view.resizeRowsToContents()

    def _selected(self, view):
        return [
            i
            for i in range(view.rowCount())
            if view.item(i, 0).checkState() == Qt.CheckState.Checked
        ]

    def _selection_changed(self, *args):
        self.import_apply_button.setEnabled(
            self._job is None
            and self.import_plan is not None
            and bool(self._selected(self.import_table))
        )
        self.export_save_button.setEnabled(
            self._job is None
            and self.export_plan is not None
            and bool(self._selected(self.export_table))
        )

    def _import_detail(self):
        index = self.import_table.currentRow()
        if self.import_plan is None or not 0 <= index < len(self.import_plan.rows):
            return
        row = self.import_plan.rows[index]
        text = "파일 내용\n" + describe(row.entry.record) + "\n" + row.entry.record.description
        if row.current is not None:
            text += "\n\n현재 앱 내용\n" + describe(row.current) + "\n" + row.current.description
        text += f"\n\n{row.status}\n외부 UID: {row.entry.uid}"
        text += "\n원래 발생일: " + (row.entry.occurrence_key or "단일 항목")
        text += "\n원본 수정 시각: " + (row.entry.modified or "정보 없음")
        text += "\n\n" + "\n".join(self.import_plan.notes)
        self.import_detail.setPlainText(text)

    def _confirm(self, text, path=None):
        dialog = QMessageBox(self)
        dialog.setWindowTitle("ICS 파일 교환 확인")
        dialog.setTextFormat(Qt.TextFormat.PlainText)
        dialog.setText(text)
        if path is not None:
            dialog.setDetailedText(str(path))
        dialog.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        dialog.setDefaultButton(QMessageBox.StandardButton.No)
        return dialog.exec() == QMessageBox.StandardButton.Yes

    def _apply(self):
        plan = self.import_plan
        if plan is None:
            return
        chosen = [plan.rows[i] for i in self._selected(self.import_table)]
        updates = sum(row.action == "update" for row in chosen)
        if not chosen or not self._confirm(
            f"선택한 {len(chosen)}개를 가져올까요?\n"
            f"새로 추가 {len(chosen) - updates}개 · 기존 항목 갱신 {updates}개\n"
            "갱신을 선택한 기존 항목의 제목·메모·시간·완료 상태가 파일 내용으로 바뀔 수 있어요."
        ):
            return
        try:
            added, updated = self.transfer.apply_import(
                plan.id, {row.id for row in chosen}, allow_updates=bool(updates)
            )
            self.import_plan = None
            self._selection_changed()
            self.status.setText(
                f"가져왔어요. 추가 {added}개 · 갱신 {updated}개. 선택하지 않은 항목은 유지했어요."
            )
        except CalendarFileError as failure:
            self.status.setText(str(failure))
        except Exception:
            self.status.setText("가져오기를 저장하지 못했어요. 이번 저장은 되돌렸어요.")

    def _preview_export(self):
        try:
            start, end = self._dates()
            self.export_plan = self.transfer.preview_export(
                start, end, self.export_kind.currentData()
            )
            self._fill(
                self.export_table, [(e, "개별 항목", True, True) for e in self.export_plan.entries]
            )
            self.export_detail.setPlainText("\n".join(self.export_plan.notes))
            self.export_table.setCurrentCell(0, 2)
            total = len(self.export_plan.entries)
            excluded = len(self.export_plan.notes)
            self.status.setText(
                f"미리보기 {total}개 · 제외 {excluded}개. 아직 파일을 저장하지 않았어요."
            )
        except CalendarFileError as failure:
            self.export_plan = None
            self.status.setText(str(failure))
        except Exception:
            self.export_plan = None
            self.status.setText("내보내기 미리보기를 만들지 못했어요.")
        self._selection_changed()

    def _export_detail(self):
        index = self.export_table.currentRow()
        if self.export_plan is not None and 0 <= index < len(self.export_plan.entries):
            entry = self.export_plan.entries[index]
            self.export_detail.setPlainText(
                describe(entry.record)
                + "\n"
                + entry.record.description
                + "\n\n외부 UID: "
                + entry.uid
                + "\n\n"
                + "\n".join(self.export_plan.notes)
            )
            from desktop_buddy.models.planning import Task

            if (
                isinstance(entry.record, Task)
                and entry.record.start_time is None
                and entry.record.due_at
            ):
                self.export_detail.appendPlainText(
                    "\nICS 시작은 해당 날짜 00:00로 기록하고 마감 시각은 유지해요."
                )

    def _save(self):
        if self.export_plan is None:
            return
        try:
            all_entries = self.transfer.export_entries(self.export_plan.id)
            entries = tuple(all_entries[i] for i in self._selected(self.export_table))
            if not entries:
                return
            path, _ = QFileDialog.getSaveFileName(
                self, "선택 항목 ICS 저장", "먼작귀-일정.ics", "iCalendar (*.ics)"
            )
            if not path:
                return
            path = Path(path)
            expected = file_token(path)
            if not self._confirm(
                f"선택한 {len(entries)}개를 ICS 파일로 저장할까요?\n"
                + ("같은 이름의 기존 파일을 교체해요." if expected else "새 파일을 만들어요."),
                path,
            ):
                return
            self.transfer.export_entries(self.export_plan.id)
            self._dispatch(
                "export",
                lambda stop: write_calendar(path, serialize_calendar(entries), expected, stop),
            )
        except CalendarFileError as failure:
            self.status.setText(str(failure))
        except Exception:
            self.status.setText("저장할 파일 위치·권한을 확인해 주세요.")

    def done(self, result):
        self._closed = True
        if self._job is not None:
            self._job.cancelled.set()
        self.transfer.invalidate()
        super().done(result)

    def showEvent(self, event):
        super().showEvent(event)
        fit_window(self)
