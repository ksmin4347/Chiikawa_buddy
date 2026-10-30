from datetime import timedelta

from PySide6.QtCore import QDate, QSignalBlocker, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QFormLayout,
    QHBoxLayout,
    QProgressBar,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from desktop_buddy.ui.common import button, card, label
from desktop_buddy.ui.mini_timer import PHASE_NAMES, countdown, duration
from desktop_buddy.ui.planning_dialogs import confirm_delete


class FocusPage(QScrollArea):
    def __init__(self, timer, planning, settings):
        super().__init__()
        self.timer, self.planning, self.settings = timer, planning, settings
        self.setWidgetResizable(True)
        page = QWidget()
        self.setWidget(page)
        body = QVBoxLayout(page)
        body.setContentsMargins(30, 28, 30, 28)
        body.setSpacing(18)
        body.addWidget(label("지금, 한 가지에 집중해요", "title"))
        body.addWidget(label("내 속도로 집중하고, 쉬는 시간도 챙겨요.", "muted"))
        frame, content = card("나의 집중 시간")
        self.phase_label = label("집중", "heading")
        self.time_label = label("25:00")
        self.time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.time_label.setProperty("kind", "countdown")
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setTextVisible(False)
        self.detail = label("", "muted")
        self.reason = label("", "muted")
        for widget in (self.phase_label, self.time_label, self.progress, self.detail, self.reason):
            content.addWidget(widget)
        row = QHBoxLayout()
        self.start_button = button("시작", self.start, True)
        self.pause_button = button("일시정지", lambda: self.run(self.timer.pause))
        self.resume_button = button("재개", lambda: self.run(self.timer.resume), True)
        self.stop_button = button("중지", lambda: self.run(self.timer.stop))
        self.reset_button = button("초기화", self.reset)
        for widget in (
            self.start_button,
            self.pause_button,
            self.resume_button,
            self.stop_button,
            self.reset_button,
        ):
            row.addWidget(widget)
        content.addLayout(row)
        row = QHBoxLayout()
        self.next_button = button("다음 단계 시작", lambda: self.run(self.timer.start_next), True)
        self.skip_button = button("휴식 건너뛰고 집중", lambda: self.run(self.timer.skip_break))
        row.addWidget(self.next_button)
        row.addWidget(self.skip_button)
        content.addLayout(row)
        self.error_label = label("", "muted")
        content.addWidget(self.error_label)
        body.addWidget(frame)
        frame, content = card("시작할 시간과 할 일")
        form = QFormLayout()
        self.kind = QComboBox()
        for key, title in PHASE_NAMES.items():
            self.kind.addItem(title, key)
        self.minutes = QSpinBox()
        self.minutes.setRange(1, 1440)
        self.minutes.setSuffix(" 분")
        self.kind.currentIndexChanged.connect(self.default_minutes)
        form.addRow("종류", self.kind)
        form.addRow("이번 시간", self.minutes)
        self.task_date = QDateEdit(QDate(planning.today()))
        self.task_date.setCalendarPopup(True)
        self.task_date.setDisplayFormat("yyyy-MM-dd")
        self.task_date.dateChanged.connect(self.refresh_links)
        self.task = QComboBox()
        self.task.setMinimumContentsLength(12)
        self.task.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.task.currentIndexChanged.connect(self.select_task)
        self.category = QComboBox()
        form.addRow("할 일 날짜", self.task_date)
        form.addRow("연결할 할 일", self.task)
        form.addRow("집중 분류", self.category)
        content.addLayout(form)
        content.addWidget(
            label("연결은 시작할 때 적용돼요. 할 일 완료 여부는 바꾸지 않아요.", "muted")
        )
        body.addWidget(frame)
        frame, content = card("뽀모도로와 표시 설정")
        form = QFormLayout()
        self.config_spins = {}
        for field, title, upper in [
            ("focus_minutes", "기본 집중", 1440),
            ("break_minutes", "짧은 휴식", 240),
            ("long_break_minutes", "긴 휴식", 240),
            ("long_break_interval", "긴 휴식까지 집중 횟수", 12),
        ]:
            spin = QSpinBox()
            spin.setRange(1, upper)
            spin.setSuffix(" 회" if field == "long_break_interval" else " 분")
            spin.valueChanged.connect(lambda value, key=field: settings.update(**{key: value}))
            self.config_spins[field] = spin
            form.addRow(title, spin)
        self.mini_mode = QComboBox()
        for title, mode in [
            ("집중 중에만", "focus"),
            ("항상", "always"),
            ("캐릭터 위에 마우스를 올릴 때", "hover"),
            ("표시 안 함", "never"),
        ]:
            self.mini_mode.addItem(title, mode)
        self.mini_mode.currentIndexChanged.connect(
            lambda: settings.update(mini_timer_mode=self.mini_mode.currentData())
        )
        form.addRow("캐릭터 옆 작은 타이머", self.mini_mode)
        content.addLayout(form)
        self.auto_next = QCheckBox("완료하면 다음 집중·휴식을 자동 시작")
        self.auto_next.toggled.connect(self.set_auto)
        self.end_notice = QCheckBox("타이머 완료 알림 받기")
        self.end_notice.toggled.connect(lambda value: settings.update(timer_notifications=value))
        self.quiet = QCheckBox("집중 중에는 일정·할 일 알림 쉬기")
        self.quiet.toggled.connect(lambda value: settings.update(focus_quiet=value))
        for widget in (self.auto_next, self.end_notice, self.quiet):
            content.addWidget(widget)
        content.addWidget(
            label(
                "기본 시간은 새로 시작할 때 적용돼요. 자동 시작은 바로 적용돼요.\n"
                "절전·긴 응답 지연·시계 변경 뒤에는 멈추고, 재개를 기다려요.\n"
                "초기화해도 공부 기록은 남아요.",
                "muted",
            )
        )
        body.addWidget(frame)
        body.addStretch()
        settings.changed.connect(self.refresh_settings)
        planning.changed.connect(self.refresh_links)
        timer.updated.connect(self.refresh)
        timer.error.connect(self.error_label.setText)
        self.refresh_settings(settings.current)
        self.refresh_links()
        self.today_completed = timer.completed_today()
        timer.records_changed.connect(self.refresh_counts)
        self.refresh(timer.snapshot)

    def run(self, action) -> None:
        try:
            self.error_label.clear()
            action()
        except (ValueError, LookupError) as error:
            self.error_label.setText(str(error))
        except Exception as error:
            self.timer._storage_error(error)
            self.refresh(self.timer.snapshot)

    def start(self) -> None:
        self.run(
            lambda: self.timer.start(
                self.kind.currentData(),
                self.minutes.value(),
                self.task.currentData(),
                self.category.currentData(),
            )
        )

    def reset(self) -> None:
        if self.timer.status in ("running", "paused") and not confirm_delete(
            self, "진행 중인 타이머를 중지하고 초기화할까요? 지금까지의 기록은 남아요."
        ):
            return
        self.run(self.timer.reset)

    def set_auto(self, enabled: bool) -> None:
        self.settings.update(auto_next_phase=enabled)
        self.run(lambda: self.timer.set_auto_next(self.settings.current.auto_next_phase))

    def default_minutes(self) -> None:
        field = {
            "focus": "focus_minutes",
            "short_break": "break_minutes",
            "long_break": "long_break_minutes",
        }[self.kind.currentData()]
        self.minutes.setValue(getattr(self.settings.current, field))

    def refresh_settings(self, current) -> None:
        widgets = [
            *self.config_spins.values(),
            self.auto_next,
            self.end_notice,
            self.quiet,
            self.mini_mode,
        ]
        blockers = [QSignalBlocker(widget) for widget in widgets]
        for key, spin in self.config_spins.items():
            spin.setValue(getattr(current, key))
        self.auto_next.setChecked(current.auto_next_phase)
        self.end_notice.setChecked(current.timer_notifications)
        self.quiet.setChecked(current.focus_quiet)
        self.mini_mode.setCurrentIndex(self.mini_mode.findData(current.mini_timer_mode))
        del blockers
        if self.timer.status == "idle":
            self.default_minutes()

    def refresh_links(self) -> None:
        old = self.task.currentData()
        category_id = self.category.currentData()
        blockers = [QSignalBlocker(self.task), QSignalBlocker(self.category)]
        day = self.task_date.date().toPython()
        self.task.clear()
        self.task.addItem("연결하지 않음", None)
        for item in self.planning.occurrences(day, day + timedelta(days=1), "task"):
            self.task.addItem(("완료 · " if item.completed else "") + item.title, item)
        if old is not None:
            for index in range(1, self.task.count()):
                value = self.task.itemData(index)
                if (value.item_id, value.key) == (old.item_id, old.key):
                    self.task.setCurrentIndex(index)
                    break
        self.category.clear()
        self.category.addItem("분류 없음", None)
        for category in self.planning.categories():
            self.category.addItem(category.name, category.id)
        self.category.setCurrentIndex(max(0, self.category.findData(category_id)))
        del blockers

    def select_task(self) -> None:
        task = self.task.currentData()
        if task is not None:
            category_id = task.category.id if task.category else None
            self.category.setCurrentIndex(max(0, self.category.findData(category_id)))

    def refresh_counts(self) -> None:
        try:
            self.today_completed = self.timer.completed_today()
            self.refresh(self.timer.snapshot)
        except Exception:
            self.error_label.setText("오늘 완료 횟수를 불러오지 못했어요.")

    def refresh(self, snapshot) -> None:
        active = snapshot.status in ("running", "paused")
        self.phase_label.setText(
            PHASE_NAMES[snapshot.phase] + (" · 일시정지" if snapshot.status == "paused" else "")
        )
        self.time_label.setText(countdown(snapshot.remaining_seconds))
        self.progress.setValue(round(snapshot.elapsed_seconds / snapshot.planned_seconds * 1000))
        self.detail.setText(
            f"진행 {duration(snapshot.elapsed_seconds)} · "
            f"일시정지 {duration(snapshot.paused_seconds)} · "
            f"이번 흐름 완료 {snapshot.completed_rounds}회\n"
            f"집중 순서 {snapshot.completed_rounds % self.timer.plan['interval'] + 1}/"
            f"{self.timer.plan['interval']} · 오늘 완료 {self.today_completed}회\n"
            f"{snapshot.task_title or '연결한 할 일 없음'} · {snapshot.category_name}"
        )
        reasons = {
            "recovered": "저장된 기록을 복구했어요. 확인한 뒤 재개해 주세요.",
            "app_closed": "지난 타이머를 이어갈 수 있어요.",
            "suspended": "절전 전에 멈췄어요. 돌아오면 재개해 주세요.",
            "resumed": "컴퓨터가 깨어나 타이머를 멈췄어요.",
            "long_gap": "긴 시간 응답이 없어 멈췄어요. 공백은 집중에 넣지 않았어요.",
            "clock_changed": "시계 변경을 감지해 멈췄어요. 확인한 뒤 재개해 주세요.",
            "storage_error": "기록 저장을 확인한 뒤 재개해 주세요.",
        }
        text = reasons.get(snapshot.reason, "")
        if snapshot.status == "ready":
            text = f"완료했어요! 다음은 {PHASE_NAMES[snapshot.next_phase]}예요."
        self.reason.setText(text)
        self.start_button.setEnabled(not active)
        self.pause_button.setVisible(snapshot.status == "running")
        self.resume_button.setVisible(snapshot.status == "paused")
        self.stop_button.setEnabled(active or snapshot.status == "ready")
        self.next_button.setVisible(snapshot.status == "ready")
        self.skip_button.setVisible(snapshot.status == "ready" and snapshot.next_phase != "focus")
        for widget in (self.kind, self.minutes, self.task, self.task_date, self.category):
            widget.setEnabled(not active)
