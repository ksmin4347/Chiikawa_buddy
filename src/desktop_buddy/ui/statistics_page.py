import calendar
from collections import defaultdict
from datetime import date, datetime, timedelta

from PySide6.QtCore import QDate, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QTextCharFormat
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCalendarWidget,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from desktop_buddy.ui.common import button, card, label
from desktop_buddy.ui.mini_timer import duration
from desktop_buddy.ui.planning_dialogs import confirm_delete


class DailyChart(QWidget):
    def __init__(self):
        super().__init__()
        self.values = []
        self.setMinimumHeight(190)
        self.setAccessibleName("날짜별 집중 시간 막대 그래프")

    def set_values(self, values) -> None:
        self.values = values
        self.setToolTip("\n".join(f"{day}  {duration(value)}" for day, value in values))
        self.update()

    def paintEvent(self, _event) -> None:
        if not self.values:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        area = QRectF(12, 30, self.width() - 24, self.height() - 60)
        peak = max(60, max(value for _, value in self.values))
        painter.setPen(self.palette().text().color())
        painter.drawText(QRectF(12, 0, self.width() - 24, 25), f"최대 {duration(peak)}")
        step = area.width() / len(self.values)
        for index, (day, value) in enumerate(self.values):
            height = area.height() * value / peak
            rect = QRectF(
                area.left() + index * step + step * 0.18,
                area.bottom() - max(2, height),
                step * 0.64,
                max(2, height),
            )
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#518767" if value else "#b6c5bc"))
            painter.drawRoundedRect(rect, 3, 3)
            if len(self.values) <= 7 or index % 5 == 0 or index == len(self.values) - 1:
                painter.setPen(self.palette().text().color())
                painter.drawText(
                    QRectF(area.left() + index * step - 9, area.bottom() + 6, step + 18, 23),
                    Qt.AlignmentFlag.AlignCenter,
                    day,
                )
        painter.end()


class StatisticsPage(QScrollArea):
    def __init__(self, statistics, planning):
        super().__init__()
        self.statistics, self.planning = statistics, planning
        self.dirty = True
        self._formatted_days = []
        self.setWidgetResizable(True)
        page = QWidget()
        self.setWidget(page)
        body = QVBoxLayout(page)
        body.setContentsMargins(30, 28, 30, 28)
        body.setSpacing(18)
        body.addWidget(label("차곡차곡 쌓인 나의 시간", "title"))
        body.addWidget(label("일시정지와 휴식을 제외한 실제 집중 시간이에요.", "muted"))
        row = QHBoxLayout()
        self.total_labels = []
        for title in ("오늘", "이번 주", "이번 달", "전체 누적"):
            frame, content = card(title)
            value = label("0분", "heading")
            content.addWidget(value)
            self.total_labels.append(value)
            row.addWidget(frame)
        body.addLayout(row)
        self.period = QComboBox()
        self.period.addItem("최근 7일", "7")
        self.period.addItem("최근 30일", "30")
        self.period.addItem("아래 달력의 한 달", "month")
        self.period.addItem("최근 8주 · 주별", "weeks")
        self.period.addItem("최근 6개월 · 월별", "months")
        self.period.currentIndexChanged.connect(self.refresh)
        body.addWidget(self.period)
        self.last_focus = label("", "muted")
        body.addWidget(self.last_focus)
        frame, content = card("기간별 집중 시간")
        self.summary = label("", "muted")
        self.chart = DailyChart()
        content.addWidget(self.summary)
        content.addWidget(self.chart)
        body.addWidget(frame)
        row = QHBoxLayout()
        self.category_table = self.group_table()
        self.task_table = self.group_table()
        for title, table in [
            ("분류별 집중", self.category_table),
            ("할 일별 집중", self.task_table),
        ]:
            frame, content = card(title)
            content.addWidget(table)
            row.addWidget(frame)
        body.addLayout(row)
        frame, content = card("공부 달력")
        self.calendar = QCalendarWidget()
        self.calendar.setVerticalHeaderFormat(QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader)
        self.calendar.setMinimumHeight(270)
        self.calendar.currentPageChanged.connect(self.month_changed)
        self.calendar.selectionChanged.connect(self.select_day)
        self.day_summary = label("", "muted")
        content.addWidget(self.calendar)
        content.addWidget(self.day_summary)
        content.addWidget(
            label("진할수록 오래 집중한 날이에요. 날짜를 누르면 시간을 볼 수 있어요.", "muted")
        )
        body.addWidget(frame)
        frame, content = card("집중 기록 · 선택 기간의 최근 100개")
        self.records = QTableWidget(0, 7)
        self.records.setHorizontalHeaderLabels(
            ["시작", "할 일 · 분류", "예정", "실제", "멈춤", "상태", "기록 ID"]
        )
        self.records.setColumnHidden(6, True)
        self.records.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.records.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.records.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.records.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        self.records.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.records.verticalHeader().hide()
        self.records.setMinimumHeight(225)
        content.addWidget(self.records)
        row = QHBoxLayout()
        self.edit_category = QComboBox()
        row.addWidget(self.edit_category)
        row.addWidget(button("선택 기록 분류 변경", self.change_category))
        row.addWidget(button("선택 기록 삭제", self.delete))
        content.addLayout(row)
        self.message = label("", "muted")
        content.addWidget(self.message)
        content.addWidget(
            label(
                "중지한 집중도 누적에 포함돼요. 완료 횟수는 끝까지 마친 집중만 세요.\n"
                "기록 삭제는 누적 시간과 그래프에 바로 반영돼요.",
                "muted",
            )
        )
        body.addWidget(frame)
        statistics.changed.connect(self.invalidate)
        planning.changed.connect(self.invalidate)
        statistics.timer.settings.changed.connect(self.invalidate)
        self.refresh_timer = QTimer(self)
        self.refresh_timer.setInterval(30000)
        self.refresh_timer.timeout.connect(self.invalidate)
        self.refresh_timer.start()

    @staticmethod
    def group_table():
        table = QTableWidget(0, 2)
        table.setHorizontalHeaderLabels(["이름", "집중 시간"])
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        table.verticalHeader().hide()
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setMinimumHeight(150)
        return table

    @staticmethod
    def fill_groups(table, groups) -> None:
        table.setRowCount(len(groups))
        for index, (name, seconds) in enumerate(sorted(groups.items(), key=lambda v: -v[1])):
            table.setItem(index, 0, QTableWidgetItem(name))
            table.setItem(index, 1, QTableWidgetItem(duration(seconds)))

    def invalidate(self, *_args) -> None:
        self.dirty = True
        if self.isVisible():
            self.refresh()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.refresh()

    def month_changed(self, *_args) -> None:
        self.refresh()

    def refresh(self, *_args) -> None:
        try:
            self._refresh()
            self.dirty = False
        except Exception:
            self.message.setText("통계를 불러오지 못했어요. 저장 공간을 확인해 주세요.")

    def _refresh(self) -> None:
        today = self.planning.today()
        tomorrow = today + timedelta(days=1)
        week_start = self.statistics.timer.settings.current.week_start
        starts = [
            today,
            today - timedelta(days=(today.weekday() - week_start) % 7),
            today.replace(day=1),
        ]
        self.calendar.setFirstDayOfWeek(
            Qt.DayOfWeek.Sunday if week_start == 6 else Qt.DayOfWeek.Monday
        )
        totals = [self.statistics.totals(start, tomorrow)["seconds"] for start in starts]
        totals.append(self.statistics.all_total())
        for widget, value in zip(self.total_labels, totals, strict=True):
            widget.setText(duration(value))
        month = date(self.calendar.yearShown(), self.calendar.monthShown(), 1)
        month_end = month + timedelta(days=calendar.monthrange(month.year, month.month)[1])
        monthly = self.statistics.totals(month, month_end)
        last = self.statistics.last_focus_date()
        self.last_focus.setText(
            f"최근 공부한 날짜 · {last:%Y.%m.%d}" if last else "아직 집중 기록이 없어요."
        )
        mode = self.period.currentData()
        if mode == "month":
            start, end, data = month, month_end, monthly
        elif mode == "weeks":
            start, end = starts[1] - timedelta(weeks=7), tomorrow
            data = self.statistics.totals(start, end)
        elif mode == "months":
            month_index = today.year * 12 + today.month - 1 - 5
            start, end = date(month_index // 12, month_index % 12 + 1, 1), tomorrow
            data = self.statistics.totals(start, end)
        else:
            start, end = today - timedelta(days=int(mode) - 1), tomorrow
            data = self.statistics.totals(start, end)
        self.summary.setText(
            f"{start:%Y.%m.%d} ~ {end - timedelta(days=1):%m.%d} · "
            f"집중 {duration(data['seconds'])} · 완료 {data['completed']}회 · "
            f"완료한 집중 평균 {duration(data['average'])}"
        )
        buckets = defaultdict(float)
        for index in range((end - start).days):
            day = start + timedelta(days=index)
            if mode == "weeks":
                key = day - timedelta(days=(day.weekday() - week_start) % 7)
            elif mode == "months":
                key = day.replace(day=1)
            else:
                key = day
            buckets[key] += data["daily"].get(day, 0)
        self.chart.set_values(
            [
                (
                    f"{key.year}.{key.month:02}"
                    if mode == "months"
                    else f"{key.month}/{key.day}" + ("~" if mode == "weeks" else ""),
                    value,
                )
                for key, value in buckets.items()
            ]
        )
        self.fill_groups(self.category_table, data["categories"])
        self.fill_groups(self.task_table, data["tasks"])
        for day in self._formatted_days:
            self.calendar.setDateTextFormat(QDate(day), QTextCharFormat())
        self._formatted_days = list(monthly["daily"])
        self.monthly_daily = monthly["daily"]
        for day, seconds in monthly["daily"].items():
            formatting = QTextCharFormat()
            formatting.setBackground(
                QColor("#d4e9d7" if seconds < 1800 else "#89bc96" if seconds < 5400 else "#386d4b")
            )
            formatting.setForeground(QColor("#183823" if seconds < 5400 else "#ffffff"))
            formatting.setToolTip(f"{day:%m/%d}  {duration(seconds)}")
            self.calendar.setDateTextFormat(QDate(day), formatting)
        self.select_day()
        selected_id = self.selected_id()
        self.records.setRowCount(len(data["records"]))
        for index, record in enumerate(data["records"]):
            when = datetime.fromisoformat(record["started_at"]).astimezone(self.planning.zone)
            state = (
                "완료" if record["completed"] else "중지" if record["ended_at"] else "진행/일시정지"
            )
            texts = [
                when.strftime("%m/%d %H:%M"),
                f"{record['task_title'] or '연결 없음'} · {record['category_name']}",
                duration(record["planned_seconds"]),
                duration(record["active_seconds"]),
                duration(record["paused_seconds"]),
                state,
                str(record["id"]),
            ]
            for column, text in enumerate(texts):
                self.records.setItem(index, column, QTableWidgetItem(text))
            if record["id"] == selected_id:
                self.records.selectRow(index)
        old_category = self.edit_category.currentData()
        self.edit_category.clear()
        self.edit_category.addItem("분류 없음", None)
        for category in self.planning.categories():
            self.edit_category.addItem(category.name, category.id)
        self.edit_category.setCurrentIndex(max(0, self.edit_category.findData(old_category)))

    def select_day(self) -> None:
        day = self.calendar.selectedDate().toPython()
        self.day_summary.setText(
            f"{day:%Y.%m.%d}  {duration(getattr(self, 'monthly_daily', {}).get(day, 0))}"
        )

    def selected_id(self):
        row = self.records.currentRow()
        item = self.records.item(row, 6) if row >= 0 else None
        return int(item.text()) if item else None

    def change_category(self) -> None:
        item_id = self.selected_id()
        if item_id is None:
            self.message.setText("먼저 기록을 선택해 주세요.")
            return
        try:
            self.statistics.change_category(item_id, self.edit_category.currentData())
            self.message.setText("분류를 변경했어요.")
        except (ValueError, LookupError) as error:
            self.message.setText(str(error))
        except Exception:
            self.message.setText("분류를 저장하지 못했어요. 저장 공간을 확인해 주세요.")

    def delete(self) -> None:
        item_id = self.selected_id()
        if item_id is None:
            self.message.setText("먼저 기록을 선택해 주세요.")
            return
        if not confirm_delete(self, "선택한 집중 기록을 삭제할까요? 누적 시간에서도 빠져요."):
            return
        try:
            self.statistics.delete_record(item_id)
            self.message.setText("기록을 삭제했어요.")
        except (ValueError, LookupError) as error:
            self.message.setText(str(error))
        except Exception:
            self.message.setText("기록을 삭제하지 못했어요. 저장 공간을 확인해 주세요.")
