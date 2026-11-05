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

from desktop_buddy.ui.accessibility import announce
from desktop_buddy.ui.common import button, card, compact_combo, label, wrap_form
from desktop_buddy.ui.mini_timer import PHASE_NAMES, countdown, duration
from desktop_buddy.ui.planning_dialogs import confirm_delete


class FocusPage(QScrollArea):
    def __init__(self, timer, planning, settings):
        super().__init__()
        self.timer, self.planning, self.settings = timer, planning, settings
        self.celebration = None
        self._defaults = {}
        self._announced_status = None
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
        self.time_label.setAccessibleName("남은 타이머 시간")
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setTextVisible(False)
        self.progress.setAccessibleName("타이머 진행률")
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
        wrap_form(form)
        self.kind = QComboBox()
        self.kind.setAccessibleName("타이머 종류")
        for key, title in PHASE_NAMES.items():
            self.kind.addItem(title, key)
        self.minutes = QSpinBox()
        self.minutes.setAccessibleName("이번 타이머 시간 · 분")
        self.minutes.setRange(1, 1440)
        self.minutes.setSuffix(" 분")
        self.kind.currentIndexChanged.connect(self.default_minutes)
        form.addRow("종류", self.kind)
        form.addRow("이번 시간", self.minutes)
        self.presets = []
        preset_row = QHBoxLayout()
        for minutes in (15, 25, 30, 60):
            preset = button(
                f"{minutes}분", lambda _checked=False, value=minutes: self.minutes.setValue(value)
            )
            preset.setAccessibleName(f"이번 타이머 {minutes}분 선택")
            self.presets.append(preset)
            preset_row.addWidget(preset)
        form.addRow("빠른 시간 선택", preset_row)
        self.task_date = QDateEdit(QDate(planning.today()))
        self.task_date.setAccessibleName("연결할 할 일의 날짜")
        self.task_date.setCalendarPopup(True)
        self.task_date.setDisplayFormat("yyyy-MM-dd")
        self.task_date.dateChanged.connect(self.refresh_links)
        self.task = QComboBox()
        self.task.setAccessibleName("집중에 연결할 할 일")
        self.task.setMinimumContentsLength(12)
        self.task.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.task.currentIndexChanged.connect(self.select_task)
        self.category = QComboBox()
        self.category.setAccessibleName("집중 기록 분류")
        compact_combo(self.category)
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
        wrap_form(form)
        self.config_spins = {}
        for field, title, upper in [
            ("focus_minutes", "기본 집중", 1440),
            ("break_minutes", "짧은 휴식", 240),
            ("long_break_minutes", "긴 휴식", 240),
            ("long_break_interval", "긴 휴식까지 집중 횟수", 12),
        ]:
            spin = QSpinBox()
            spin.setAccessibleName(title)
            spin.setRange(1, upper)
            spin.setSuffix(" 회" if field == "long_break_interval" else " 분")
            spin.valueChanged.connect(lambda value, key=field: settings.update(**{key: value}))
            self.config_spins[field] = spin
            form.addRow(title, spin)
        self.mini_mode = QComboBox()
        self.mini_mode.setAccessibleName("작은 타이머 표시 조건")
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
        self.mini_style = QComboBox()
        self.mini_style.setAccessibleName("작은 타이머 모양")
        self.mini_style.addItem("숫자", "pill")
        self.mini_style.addItem("원형 진행", "ring")
        self.mini_style.currentIndexChanged.connect(
            lambda: settings.update(mini_timer_style=self.mini_style.currentData())
        )
        form.addRow("작은 타이머 모양", self.mini_style)
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
        frame, content = card("집중 완료 축하")
        self.completion_style = QComboBox()
        for title, key in (
            ("짧게 축하하기 (기본)", "simple"),
            ("점프·인사 공연", "party"),
            ("축하 동작 끄기", "off"),
        ):
            self.completion_style.addItem(title, key)
        self.completion_style.setAccessibleName("집중 완료 축하 동작")
        self.completion_style.currentIndexChanged.connect(
            lambda: self.change_completion(completion_style=self.completion_style.currentData())
        )
        content.addWidget(self.completion_style)
        self.completion_sound = QCheckBox("캐릭터별 완료 음악 재생")
        self.completion_sound.toggled.connect(
            lambda enabled: self.change_completion(completion_sound_enabled=enabled)
        )
        content.addWidget(self.completion_sound)
        self.completion_hint = label("", "muted")
        content.addWidget(self.completion_hint)
        row = QHBoxLayout()
        self.completion_preview = button("축하 미리보기", self.preview_completion)
        self.completion_stop = button("축하·음악 멈추기", self.stop_completion)
        row.addWidget(self.completion_preview)
        row.addWidget(self.completion_stop)
        content.addLayout(row)
        self.completion_status = label("", "muted")
        self.completion_status.setAccessibleName("완료 축하 재생 상태")
        content.addWidget(self.completion_status)
        self.completion_error = label("", "muted")
        content.addWidget(self.completion_error)
        content.addWidget(
            label(
                "음악은 기본 꺼짐이에요. 공연은 소리 없이 6초, 음악을 켜면 곡 길이에 맞춰 보여요.\n"
                "숨김·수면·방해 금지 중에는 쉬어요. 완료 알림을 끄면 자동 축하도 쉬어요.\n"
                "새 타이머나 직접 조작은 축하를 멈춰요. 자동 다음 단계는 짧게만 축하해요.",
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

    def bind_celebration(self, service) -> None:
        self.celebration = service
        service.changed.connect(self.refresh_completion)
        service.failed.connect(self.completion_failed)
        self.refresh_completion()

    def change_completion(self, **changes) -> None:
        if not self.settings.update(**changes):
            self.completion_failed("축하 설정을 저장하지 못했어요. 다시 시도해 주세요.")
        else:
            self.completion_error.clear()
        self.refresh_settings(self.settings.current)

    def completion_failed(self, text: str) -> None:
        self.error_label.setText(text)
        self.completion_error.setText(text)

    def preview_completion(self) -> None:
        if self.celebration is not None:
            self.completion_error.clear()
            try:
                self.celebration.preview()
            except ValueError as error:
                self.completion_failed(str(error))
            except Exception:
                self.completion_failed(
                    "축하를 재생하지 못했어요. 설정을 확인하고 다시 시도해 주세요."
                )

    def stop_completion(self) -> None:
        if self.celebration is not None:
            self.celebration.stop()

    def refresh_completion(self) -> None:
        current = self.settings.current
        active = self.celebration is not None and self.celebration.active
        supported = current.character_id in ("chiikawa", "hachiware", "usagi")
        self.completion_sound.setEnabled(supported)
        self.completion_hint.setText(
            "음악 길이: 치이카와 27초 · 하치와레 57초 · 우사기 16초"
            if supported
            else "기본 모루는 축하 동작만 있어요. 세 캐릭터를 고르면 음악도 사용할 수 있어요."
        )
        output = (current.completion_style != "off" and not current.reduce_motion) or (
            current.completion_sound_enabled and supported
        )
        self.completion_preview.setEnabled(
            self.celebration is not None
            and self.timer.status not in ("running", "paused")
            and output
        )
        self.completion_stop.setEnabled(active)
        self.completion_status.setText("축하를 재생하고 있어요." if active else "")

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
            self.mini_style,
            self.completion_style,
            self.completion_sound,
        ]
        blockers = [QSignalBlocker(widget) for widget in widgets]
        for key, spin in self.config_spins.items():
            spin.setValue(getattr(current, key))
        self.auto_next.setChecked(current.auto_next_phase)
        self.end_notice.setChecked(current.timer_notifications)
        self.quiet.setChecked(current.focus_quiet)
        self.mini_mode.setCurrentIndex(self.mini_mode.findData(current.mini_timer_mode))
        self.mini_style.setCurrentIndex(self.mini_style.findData(current.mini_timer_style))
        self.completion_style.setCurrentIndex(
            self.completion_style.findData(current.completion_style)
        )
        self.completion_sound.setChecked(current.completion_sound_enabled)
        del blockers
        self.refresh_completion()
        defaults = {
            "focus": current.focus_minutes,
            "short_break": current.break_minutes,
            "long_break": current.long_break_minutes,
        }
        kind = self.kind.currentData()
        previous = self._defaults.get(kind)
        self._defaults = defaults
        if self.timer.status == "idle" and (previous is None or self.minutes.value() == previous):
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
        self.time_label.setAccessibleDescription(
            PHASE_NAMES[snapshot.phase] + " · " + self.time_label.text()
        )
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
        key = snapshot.phase, snapshot.status
        if self._announced_status is not None and key != self._announced_status:
            status = {"idle": "대기", "running": "진행 중", "paused": "일시정지", "ready": "완료"}
            announce(
                self.phase_label, PHASE_NAMES[snapshot.phase] + " · " + status[snapshot.status]
            )
        self._announced_status = key
        self.start_button.setEnabled(not active)
        for preset in self.presets:
            preset.setEnabled(not active)
        self.pause_button.setVisible(snapshot.status == "running")
        self.resume_button.setVisible(snapshot.status == "paused")
        self.stop_button.setEnabled(active or snapshot.status == "ready")
        self.next_button.setVisible(snapshot.status == "ready")
        self.skip_button.setVisible(snapshot.status == "ready" and snapshot.next_phase != "focus")
        for widget in (self.kind, self.minutes, self.task, self.task_date, self.category):
            widget.setEnabled(not active)
        self.refresh_completion()
