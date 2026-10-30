from PySide6.QtCore import QDate, QSignalBlocker, QTime, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QScrollArea,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from desktop_buddy.ui.common import button, card, label
from desktop_buddy.ui.planning_dialogs import confirm_delete


class CompanionPage(QScrollArea):
    briefing_requested = Signal()

    def __init__(self, companion, settings):
        super().__init__()
        self.companion, self.settings = companion, settings
        self.setWidgetResizable(True)
        page = QWidget()
        page.setObjectName("page")
        self.setWidget(page)
        body = QVBoxLayout(page)
        body.setContentsMargins(30, 28, 30, 28)
        body.setSpacing(18)
        body.addWidget(label("내 생활에 맞춰 함께해요", "title"))
        body.addWidget(label("공부하는 날도, 쉬는 날도 내 속도로 보내요.", "muted"))
        frame, content = card("지금의 작은 친구")
        self.state_label = label("", "heading")
        self.state_detail = label("", "muted")
        self.clock_button = button("날짜를 확인했어요 · 현재 날짜로 계속", self.confirm_clock)
        for widget in (self.state_label, self.state_detail, self.clock_button):
            content.addWidget(widget)
        body.addWidget(frame)
        self.checks = {}
        self.spins = {}
        self.times = {}
        frame, content = card("공부 기록과 감정")
        self.add_check(content, "record_focus", "새로 시작하는 집중의 공부 기록 저장")
        self.add_check(content, "emotion_enabled", "공부 공백에 따른 표정 변화")
        form = QFormLayout()
        for key, title, lower, upper, suffix in [
            ("emotion_gap_days", "시무룩해지는 기준", 2, 30, " 일"),
            ("valid_focus_minutes", "유효한 집중 · 끝까지 완료", 1, 1440, " 분 이상"),
            ("emotion_message_days", "짧은 안부 간격 · 0은 끄기", 0, 30, " 일"),
        ]:
            spin = QSpinBox()
            spin.setRange(lower, upper)
            spin.setSuffix(suffix)
            spin.valueChanged.connect(lambda value, key=key: settings.update(**{key: value}))
            self.spins[key] = spin
            form.addRow(title, spin)
        content.addLayout(form)
        content.addWidget(
            label(
                "처음 유효한 집중을 마치기 전에는 공부 공백을 판단하지 않아요.\n"
                "쉬는 날짜는 공백에서 빼고, 안부는 방해되지 않을 때만 조용히 전해요.\n"
                "기록을 꺼도 기존 기록은 남아요. 새 집중의 임시 정보는 복구에 사용해요.\n"
                "끝난 임시 세션은 정리하고 통계에는 넣지 않아요.",
                "muted",
            )
        )
        body.addWidget(frame)
        frame, content = card("쉬는 날과 휴식 기간")
        row = QHBoxLayout()
        self.weekdays = []
        for title in "월화수목금토일":
            check = QCheckBox(title)
            check.toggled.connect(self.save_weekdays)
            self.weekdays.append(check)
            row.addWidget(check)
        content.addLayout(row)
        row = QHBoxLayout()
        today = companion.clock.now().astimezone(companion.focus.planning.zone).date()
        self.rest_start = QDateEdit(QDate(today))
        self.rest_end = QDateEdit(QDate(today))
        for widget in (self.rest_start, self.rest_end):
            widget.setCalendarPopup(True)
            widget.setDisplayFormat("yyyy-MM-dd")
        row.addWidget(self.rest_start)
        row.addWidget(label("~"))
        row.addWidget(self.rest_end)
        row.addWidget(button("휴식 기간 추가", self.add_rest))
        content.addLayout(row)
        self.periods = QTableWidget(0, 2)
        self.periods.setHorizontalHeaderLabels(["시작일", "종료일 · 이 날까지 쉬어요"])
        self.periods.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.periods.verticalHeader().hide()
        self.periods.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.periods.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.periods.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.periods.setMinimumHeight(145)
        content.addWidget(self.periods)
        content.addWidget(button("선택한 휴식 기간 삭제", self.delete_rest))
        content.addWidget(
            label(
                "휴식 기간은 자동으로 적용돼요. 지난 기간도 남겨 두면 공백 계산에서 계속 빠져요.\n"
                "쉬는 날에도 원하면 집중할 수 있어요.",
                "muted",
            )
        )
        body.addWidget(frame)
        frame, content = card("수면과 집중 중 표시")
        self.add_check(content, "sleep_enabled", "수면 시간에는 잠자는 모습으로 조용히 있기")
        form = QFormLayout()
        for key, title in [("sleep_start", "잠드는 시간"), ("sleep_end", "깨어나는 시간")]:
            widget = QTimeEdit()
            widget.setDisplayFormat("HH:mm")
            widget.timeChanged.connect(
                lambda value, key=key: settings.update(**{key: value.toString("HH:mm")})
            )
            self.times[key] = widget
            form.addRow(title, widget)
        self.appearance = QComboBox()
        for title, value in [
            ("평소대로", "normal"),
            ("움직임을 천천히", "calm"),
            ("작게 표시", "small"),
            ("작은 타이머만", "timer_only"),
            ("모두 숨김", "hidden"),
        ]:
            self.appearance.addItem(title, value)
        self.appearance.currentIndexChanged.connect(
            lambda: settings.update(focus_appearance=self.appearance.currentData())
        )
        form.addRow("집중 중 캐릭터", self.appearance)
        content.addLayout(form)
        self.add_check(
            content, "fullscreen_hide", "Windows가 전체 화면·발표 상태를 감지하면 자동 숨김"
        )
        self.add_check(
            content, "timer_alert_during_quiet", "방해 금지·수면 중에도 타이머 완료 알림 허용"
        )
        content.addWidget(
            label(
                "집중이 끝나면 원래 크기·속도·표시로 돌아와요. 직접 숨긴 상태는 유지해요.\n"
                "Windows 감지는 일부 전체 화면 앱을 놓칠 수 있어요.\n"
                "필요하면 우클릭·트레이에서 직접 숨길 수 있어요.\n"
                "방해 금지 시간과 알림 잠시 쉬기는 설정에서 바꿔요.\n"
                "다른 앱의 알림은 바꾸지 않아요.",
                "muted",
            )
        )
        body.addWidget(frame)
        frame, content = card("하루 브리핑")
        self.add_check(content, "briefing_enabled", "하루 한 번 오늘의 계획 브리핑 받기")
        self.add_check(content, "briefing_on_start", "앱을 시작할 때도 오늘 브리핑 받기")
        self.add_check(content, "briefing_detailed", "할 일·마감·공부 계획까지 자세히 표시")
        self.briefing_time = QTimeEdit()
        self.briefing_time.setDisplayFormat("HH:mm")
        self.briefing_time.timeChanged.connect(
            lambda value: settings.update(briefing_time=value.toString("HH:mm"))
        )
        form = QFormLayout()
        form.addRow("브리핑 시각", self.briefing_time)
        content.addLayout(form)
        content.addWidget(button("오늘 브리핑 보기", self.briefing_requested.emit, True))
        content.addWidget(
            label(
                "시간 기준은 한국(서울)이에요. 앱이 실행 중이어야 자동으로 표시돼요.\n"
                "집중·수면·방해 금지 중에는 기다리고, 지난날 브리핑은 쌓아 띄우지 않아요.\n"
                "자동 브리핑은 재실행해도 하루 한 번이에요. 직접 보기는 언제든 가능해요.",
                "muted",
            )
        )
        body.addWidget(frame)
        self.message = label("", "muted")
        body.addWidget(self.message)
        body.addStretch()
        settings.changed.connect(self.refresh_settings)
        companion.changed.connect(self.refresh)
        companion.failed.connect(self.message.setText)
        self.refresh_settings(settings.current)
        self.refresh(companion.snapshot)

    def add_check(self, layout, key: str, title: str) -> None:
        widget = QCheckBox(title)
        widget.toggled.connect(lambda value: self.settings.update(**{key: value}))
        self.checks[key] = widget
        layout.addWidget(widget)

    def refresh_settings(self, current) -> None:
        widgets = [
            *self.checks.values(),
            *self.spins.values(),
            *self.times.values(),
            *self.weekdays,
            self.appearance,
            self.briefing_time,
        ]
        blockers = [QSignalBlocker(widget) for widget in widgets]
        for key, widget in self.checks.items():
            widget.setChecked(getattr(current, key))
        for key, widget in self.spins.items():
            widget.setValue(getattr(current, key))
        for key, widget in self.times.items():
            widget.setTime(QTime.fromString(getattr(current, key), "HH:mm"))
            widget.setEnabled(current.sleep_enabled)
        for index, check in enumerate(self.weekdays):
            check.setChecked(index in current.rest_weekdays)
        self.appearance.setCurrentIndex(self.appearance.findData(current.focus_appearance))
        self.briefing_time.setTime(QTime.fromString(current.briefing_time, "HH:mm"))
        self.briefing_time.setEnabled(current.briefing_enabled)

        del blockers

    def save_weekdays(self) -> None:
        self.settings.update(
            rest_weekdays=tuple(
                index for index, check in enumerate(self.weekdays) if check.isChecked()
            )
        )

    def refresh(self, snapshot) -> None:
        self.state_label.setText(snapshot.description)
        self.state_detail.setText(
            f"최근 유효 집중 · {snapshot.last_valid_date:%Y.%m.%d} · "
            f"쉬는 날 제외 공백 {snapshot.gap_days}일"
            if snapshot.last_valid_date
            else "아직 유효한 집중 완료 기록이 없어요. 편하게 시작해요."
        )
        self.clock_button.setVisible(snapshot.clock_warning)
        self.refresh_periods()

    def refresh_periods(self) -> None:
        self.rows = self.companion.repository.periods()
        self.periods.setRowCount(len(self.rows))
        for index, row in enumerate(self.rows):
            self.periods.setItem(index, 0, QTableWidgetItem(row["start_date"].isoformat()))
            self.periods.setItem(index, 1, QTableWidgetItem(row["end_date"].isoformat()))

    def confirm_clock(self) -> None:
        try:
            self.companion.acknowledge_clock()
        except Exception:
            self.message.setText("날짜 확인을 저장하지 못했어요. 저장 공간을 확인해 주세요.")

    def add_rest(self) -> None:
        try:
            self.companion.add_rest_period(
                self.rest_start.date().toPython(), self.rest_end.date().toPython()
            )
            self.refresh_periods()
            self.message.setText("휴식 기간을 저장했어요.")
        except ValueError as error:
            self.message.setText(str(error))
        except Exception:
            self.message.setText("휴식 기간을 저장하지 못했어요. 저장 공간을 확인해 주세요.")

    def delete_rest(self) -> None:
        row = self.periods.currentRow()
        if row < 0:
            self.message.setText("먼저 휴식 기간을 선택해 주세요.")
            return
        if not confirm_delete(self, "선택한 휴식 기간을 삭제할까요? 공부 공백을 다시 계산해요."):
            return
        try:
            self.companion.delete_rest_period(self.rows[row]["id"])
            self.refresh_periods()
        except Exception:
            self.message.setText("휴식 기간을 삭제하지 못했어요. 저장 공간을 확인해 주세요.")
