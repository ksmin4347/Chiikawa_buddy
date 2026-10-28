from datetime import UTC, datetime, time

from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QFormLayout,
    QHBoxLayout,
    QSpinBox,
    QWidget,
)

from desktop_buddy.calendar.recurrence import WEEKDAYS, encode, parts


class RepeatEditor(QWidget):
    def __init__(self, rule: str | None, start: datetime, parent=None):
        super().__init__(parent)
        self.zone = start.tzinfo
        form = QFormLayout(self)
        form.setContentsMargins(0, 0, 0, 0)
        self.frequency = QComboBox()
        for title, value in [
            ("반복 안 함", None),
            ("매일", "DAILY"),
            ("매주 · 요일 선택", "WEEKLY"),
            ("매월 같은 날짜", "MONTHLY"),
            ("매년 같은 날짜", "YEARLY"),
        ]:
            self.frequency.addItem(title, value)
        self.frequency.setAccessibleName("반복 방식")
        self.interval = QSpinBox()
        self.interval.setRange(1, 365)
        self.interval.setSuffix(" 간격")
        row = QHBoxLayout()
        row.addWidget(self.frequency, 1)
        row.addWidget(self.interval)
        form.addRow("반복", row)
        weekdays = QHBoxLayout()
        self.days = []
        for index, text in enumerate("월화수목금토일"):
            check = QCheckBox(text)
            check.setChecked(index == start.weekday())
            weekdays.addWidget(check)
            self.days.append(check)
        form.addRow("요일", weekdays)
        self.end_kind = QComboBox()
        for title, value in [("종료 없음", "none"), ("날짜까지", "date"), ("횟수만큼", "count")]:
            self.end_kind.addItem(title, value)
        self.end_date = QDateEdit(QDate(start.year, start.month, start.day).addMonths(1))
        self.end_date.setCalendarPopup(True)
        self.end_date.setDisplayFormat("yyyy-MM-dd")
        self.count = QSpinBox()
        self.count.setRange(1, 10000)
        self.count.setValue(10)
        row = QHBoxLayout()
        row.addWidget(self.end_kind)
        row.addWidget(self.end_date)
        row.addWidget(self.count)
        form.addRow("반복 종료", row)
        if rule:
            values = parts(rule)
            self.frequency.setCurrentIndex(self.frequency.findData(values.get("FREQ")))
            self.interval.setValue(int(values.get("INTERVAL", 1)))
            if "BYDAY" in values:
                for index, check in enumerate(self.days):
                    check.setChecked(WEEKDAYS[index] in values["BYDAY"].split(","))
            if "COUNT" in values:
                self.end_kind.setCurrentIndex(2)
                self.count.setValue(int(values["COUNT"]))
            elif "UNTIL" in values:
                end = (
                    datetime.strptime(values["UNTIL"], "%Y%m%dT%H%M%SZ")
                    .replace(tzinfo=UTC)
                    .astimezone(self.zone)
                )
                self.end_kind.setCurrentIndex(1)
                self.end_date.setDate(QDate(end.year, end.month, end.day))
        self.frequency.currentIndexChanged.connect(self._enabled)
        self.end_kind.currentIndexChanged.connect(self._enabled)
        self._enabled()

    def _enabled(self, *_args) -> None:
        repeating = self.frequency.currentData() is not None
        self.interval.setEnabled(repeating)
        self.end_kind.setEnabled(repeating)
        self.end_date.setEnabled(repeating and self.end_kind.currentData() == "date")
        self.count.setEnabled(repeating and self.end_kind.currentData() == "count")
        for check in self.days:
            check.setEnabled(self.frequency.currentData() == "WEEKLY")

    def rule(self, start: datetime) -> str | None:
        frequency = self.frequency.currentData()
        if not frequency:
            return None
        values = {"FREQ": frequency, "INTERVAL": str(self.interval.value())}
        if frequency == "WEEKLY":
            selected = [
                WEEKDAYS[index] for index, check in enumerate(self.days) if check.isChecked()
            ]
            if not selected:
                raise ValueError("반복할 요일을 하나 이상 선택해 주세요.")
            values["BYDAY"] = ",".join(selected)
        if self.end_kind.currentData() == "count":
            values["COUNT"] = str(self.count.value())
        elif self.end_kind.currentData() == "date":
            day = self.end_date.date().toPython()
            end = datetime.combine(day, time(23, 59, 59), start.tzinfo)
            values["UNTIL"] = end.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
        return encode(values)
