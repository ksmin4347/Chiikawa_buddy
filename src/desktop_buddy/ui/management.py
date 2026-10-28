from datetime import datetime

from PySide6.QtCore import QSignalBlocker, Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from desktop_buddy.core.metadata import APP_NAME, VERSION
from desktop_buddy.services.settings_service import SettingsService


def label(text: str, kind: str = "") -> QLabel:
    widget = QLabel(text)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    widget.setWordWrap(True)
    if kind:
        widget.setProperty("kind", kind)
    return widget


def button(text: str, action, primary: bool = False) -> QPushButton:
    widget = QPushButton(text)
    widget.setCursor(Qt.CursorShape.PointingHandCursor)
    widget.setProperty("primary", primary)
    widget.clicked.connect(action)
    return widget


def card(title: str) -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setObjectName("card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(22, 20, 22, 20)
    layout.setSpacing(14)
    layout.addWidget(label(title, "heading"))
    return frame, layout


class ManagementWindow(QMainWindow):
    greet_requested = Signal()
    find_requested = Signal()
    toggle_pet_requested = Signal()
    quit_requested = Signal()
    reset_requested = Signal()
    closing = Signal()

    def __init__(self, service: SettingsService, preview, data_dir):
        super().__init__()
        self.service = service
        self.setWindowTitle(f"{APP_NAME} · 관리창")
        self.setWindowIcon(QIcon(preview))
        self.resize(960, 760)
        self.setMinimumSize(720, 560)
        root = QWidget()
        self.setCentralWidget(root)
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        side = QFrame()
        side.setObjectName("sidebar")
        side.setFixedWidth(184)
        nav_layout = QVBoxLayout(side)
        nav_layout.setContentsMargins(18, 28, 18, 22)
        logo = QLabel()
        logo.setPixmap(
            preview.scaled(
                68,
                68,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        nav_layout.addWidget(logo)
        nav_layout.addWidget(label(APP_NAME.replace(" ", "\n", 1), "heading"))
        nav_layout.addWidget(label("나의 작은 데스크톱 친구", "muted"))
        nav_layout.addSpacing(28)
        self.pages = QStackedWidget()
        self.nav_group = QButtonGroup(self)
        for index, title in enumerate(["홈", "설정"]):
            nav = QPushButton(title)
            nav.setCheckable(True)
            nav.setProperty("nav", True)
            nav.setCursor(Qt.CursorShape.PointingHandCursor)
            nav.clicked.connect(lambda _checked=False, i=index: self.pages.setCurrentIndex(i))
            self.nav_group.addButton(nav, index)
            nav_layout.addWidget(nav)
        self.nav_group.button(0).setChecked(True)
        nav_layout.addStretch()
        nav_layout.addWidget(label("인터넷 없이도 함께해요\n내 컴퓨터에만 저장", "muted"))
        nav_layout.addSpacing(10)
        nav_layout.addWidget(label(f"v{VERSION} · 초기 버전", "muted"))
        layout.addWidget(side)
        layout.addWidget(self.pages, 1)
        self._make_home(preview)
        self._make_settings(data_dir)
        service.changed.connect(self.refresh)
        self.refresh(service.current)

    def _page(self) -> QVBoxLayout:
        area = QScrollArea()
        area.setWidgetResizable(True)
        page = QWidget()
        page.setObjectName("page")
        body = QVBoxLayout(page)
        body.setContentsMargins(30, 28, 30, 28)
        body.setSpacing(20)
        area.setWidget(page)
        self.pages.addWidget(area)
        return body

    def _make_home(self, preview) -> None:
        body = self._page()
        weekdays = "월화수목금토일"
        today = datetime.now().astimezone()
        body.addWidget(
            label(f"{today.month}월 {today.day}일 {weekdays[today.weekday()]}요일", "eyebrow")
        )
        body.addWidget(label("작은 친구와, 편안한 하루", "title"))
        body.addWidget(label("바탕화면 한쪽에서 조용히 함께할게요.", "muted"))
        hero = QFrame()
        hero.setObjectName("hero")
        hero_layout = QHBoxLayout(hero)
        hero_layout.setContentsMargins(20, 20, 24, 20)
        picture = QLabel()
        picture.setPixmap(
            preview.scaled(
                160,
                160,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        picture.setFixedSize(160, 160)
        picture.setAccessibleName("오리지널 기본 캐릭터 모루")
        hero_layout.addWidget(picture)
        words = QVBoxLayout()
        words.addWidget(label("HELLO, MY LITTLE FRIEND", "eyebrow"))
        self.greeting = label("", "heading")
        words.addWidget(self.greeting)
        words.addWidget(label("불러 주면 반갑게 인사해요.\n원하는 곳으로 살짝 옮겨 보세요."))
        words.addWidget(button("캐릭터와 인사하기", self.greet_requested.emit, True))
        hero_layout.addLayout(words, 1)
        body.addWidget(hero)
        frame, content = card("이렇게 함께해요")
        for title, detail in [
            ("한 번 클릭", "짧은 표정 변화와 말풍선으로 인사해요."),
            ("더블클릭", "지금 보고 있는 관리창을 열어요."),
            ("드래그 · 마우스 오른쪽 클릭", "위치를 옮기거나 간단한 메뉴를 열어요."),
        ]:
            row = QHBoxLayout()
            heading = label(title)
            heading.setMinimumWidth(180)
            row.addWidget(heading)
            row.addWidget(label(detail, "muted"), 1)
            content.addLayout(row)
        body.addWidget(frame)
        actions = QHBoxLayout()
        actions.addWidget(button("캐릭터 찾기", self.find_requested.emit))
        self.visibility_button = button("캐릭터 숨기기", self.toggle_pet_requested.emit)
        actions.addWidget(self.visibility_button)
        body.addLayout(actions)
        body.addWidget(
            label(
                "지금은 캐릭터와 기본 설정을 사용할 수 있어요.\n"
                "계획 · 캘린더 → 집중 · 통계 → 채팅 순서로 개발 예정이에요.",
                "muted",
            )
        )
        body.addStretch()

    def _make_settings(self, data_dir) -> None:
        body = self._page()
        body.addWidget(label("나에게 맞는 작은 친구", "title"))
        body.addWidget(label("변경사항은 바로 적용되고 이 컴퓨터에 저장돼요.", "muted"))
        frame, content = card("캐릭터")
        form = QFormLayout()
        form.setHorizontalSpacing(28)
        form.setVerticalSpacing(12)
        self.name_edit = QLineEdit()
        self.name_edit.setMaxLength(20)
        self.name_edit.setAccessibleName("캐릭터 이름")
        self.name_edit.editingFinished.connect(
            lambda: self.service.update(character_name=self.name_edit.text())
        )
        form.addRow("부르는 이름", self.name_edit)
        self.size_spin = QSpinBox()
        self.size_spin.setRange(96, 320)
        self.size_spin.setSingleStep(8)
        self.size_spin.setSuffix(" px")
        self.size_spin.setAccessibleName("캐릭터 크기")
        self.size_spin.valueChanged.connect(lambda value: self.service.update(size=value))
        form.addRow("크기", self.size_spin)
        self.speed_combo = QComboBox()
        for text, value in [("느긋하게 (50%)", 50), ("보통 (100%)", 100), ("활기차게 (150%)", 150)]:
            self.speed_combo.addItem(text, value)
        self.speed_combo.setAccessibleName("애니메이션 속도")
        self.speed_combo.currentIndexChanged.connect(
            lambda _index: self.service.update(animation_speed=self.speed_combo.currentData())
        )
        form.addRow("움직임 속도", self.speed_combo)
        content.addLayout(form)
        self.motion_check = QCheckBox("움직임 줄이기 · 정지 이미지로 표시")
        self.motion_check.toggled.connect(lambda value: self.service.update(reduce_motion=value))
        content.addWidget(self.motion_check)
        self.bubble_check = QCheckBox("인사 말풍선 표시")
        self.bubble_check.toggled.connect(lambda value: self.service.update(bubbles_enabled=value))
        content.addWidget(self.bubble_check)
        content.addWidget(button("캐릭터를 오른쪽 아래로 이동", self.reset_requested.emit))
        body.addWidget(frame)
        frame, content = card("화면과 실행")
        self.top_check = QCheckBox("캐릭터를 항상 위에 표시")
        self.top_check.toggled.connect(lambda value: self.service.update(always_on_top=value))
        content.addWidget(self.top_check)
        self.start_check = QCheckBox("앱을 시작하면 캐릭터 표시")
        self.start_check.toggled.connect(lambda value: self.service.update(show_on_start=value))
        content.addWidget(self.start_check)
        content.addWidget(label("Windows 시작 프로그램에는 자동 등록하지 않아요.", "muted"))
        form = QFormLayout()
        self.theme_combo = QComboBox()
        self.theme_combo.addItem("밝은 화면", "light")
        self.theme_combo.addItem("어두운 화면", "dark")
        self.theme_combo.setAccessibleName("화면 테마")
        self.theme_combo.currentIndexChanged.connect(
            lambda _index: self.service.update(theme=self.theme_combo.currentData())
        )
        form.addRow("화면 테마", self.theme_combo)
        content.addLayout(form)
        body.addWidget(frame)
        frame, content = card("데이터와 프로그램")
        content.addWidget(label("설정과 캐릭터 위치는 아래 폴더에 보관해요.", "muted"))
        path_label = label(str(data_dir))
        path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        content.addWidget(path_label)
        content.addWidget(
            label(
                "관리창을 닫아도 캐릭터와 트레이는 계속 실행돼요.\n"
                "완전히 끝내려면 아래 버튼이나 트레이의 종료 메뉴를 사용하세요.",
                "muted",
            )
        )
        content.addWidget(button("프로그램 종료", self.quit_requested.emit))
        body.addWidget(frame)
        self.save_status = label("모든 설정이 저장되어 있어요.", "muted")
        self.save_status.setAccessibleName("설정 저장 상태")
        body.addWidget(self.save_status)
        body.addStretch()

    def refresh(self, settings) -> None:
        widgets = [
            self.name_edit,
            self.size_spin,
            self.speed_combo,
            self.motion_check,
            self.bubble_check,
            self.top_check,
            self.start_check,
            self.theme_combo,
        ]
        blockers = [QSignalBlocker(widget) for widget in widgets]
        self.name_edit.setText(settings.character_name)
        self.size_spin.setValue(settings.size)
        self.speed_combo.setCurrentIndex(self.speed_combo.findData(settings.animation_speed))
        self.motion_check.setChecked(settings.reduce_motion)
        self.bubble_check.setChecked(settings.bubbles_enabled)
        self.top_check.setChecked(settings.always_on_top)
        self.start_check.setChecked(settings.show_on_start)
        self.theme_combo.setCurrentIndex(self.theme_combo.findData(settings.theme))
        self.greeting.setText(f"안녕, 나는 {settings.character_name}!")
        self.save_status.setText("모든 설정이 저장되어 있어요.")
        del blockers

    def set_pet_visible(self, visible: bool) -> None:
        self.visibility_button.setText("캐릭터 숨기기" if visible else "캐릭터 다시 표시")

    def open_page(self, index: int = 0) -> None:
        self.pages.setCurrentIndex(index)
        self.nav_group.button(index).setChecked(True)
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event) -> None:
        self.closing.emit()
        self.hide()
        event.ignore()
