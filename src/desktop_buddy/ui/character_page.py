from PySide6.QtCore import QSignalBlocker, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from desktop_buddy.characters.dialogue_profiles import PROFILES
from desktop_buddy.core.metadata import APP_NAME
from desktop_buddy.ui.common import button, card, label

STATE_NAMES = {
    "idle": "평소",
    "happy": "인사",
    "focus": "집중",
    "break": "휴식",
    "complete": "완료",
    "sad": "시무룩",
    "worried": "걱정",
    "sleep": "수면",
    "run_right": "오른쪽 달리기",
    "run_left": "왼쪽 달리기",
    "look": "시선 (16방향)",
}


class CharacterPage(QScrollArea):
    selected = Signal()

    def __init__(self, characters, *, include_moru=True):
        super().__init__()
        self.characters = characters
        self._loaded = False
        self.setWidgetResizable(True)
        page = QWidget()
        page.setObjectName("page")
        self.setWidget(page)
        body = QVBoxLayout(page)
        body.setContentsMargins(24, 24, 24, 24)
        body.addWidget(label("함께할 친구를 골라요", "title"))
        body.addWidget(
            label("그림과 말투를 함께 바꿔요. 계획과 공부 기록은 그대로 유지돼요.", "muted")
        )
        self.state = QComboBox()
        self.state.setAccessibleName("캐릭터 모습 미리보기")
        for key, name in STATE_NAMES.items():
            self.state.addItem(name, key)
        self.state.currentIndexChanged.connect(self.load_previews)
        body.addWidget(self.state)
        row = QHBoxLayout()
        self.previews, self.buttons = {}, {}
        for item in PROFILES[1:]:
            frame, content = card(item.name)
            picture = QLabel()
            picture.setAlignment(Qt.AlignmentFlag.AlignCenter)
            picture.setMinimumSize(96, 96)
            picture.setAccessibleName(f"{item.name} 미리보기")
            content.addWidget(picture)
            select = button("선택하기", lambda _checked=False, key=item.id: self.choose(key), True)
            content.addWidget(select)
            self.previews[item.id], self.buttons[item.id] = picture, select
            row.addWidget(frame, 1)
        body.addLayout(row)
        if include_moru:
            body.addWidget(button("기본 캐릭터 모루 사용", lambda: self.choose("moru")))
            frame, content = card("캐릭터의 움직임")
            self.look_enabled = QCheckBox("마우스 방향 바라보기")
            self.roaming_enabled = QCheckBox("가끔 주변을 돌아다니기")
            self.look_enabled.toggled.connect(
                lambda enabled: self.change_behavior(cursor_look_enabled=enabled)
            )
            self.roaming_enabled.toggled.connect(
                lambda enabled: self.change_behavior(roaming_enabled=enabled)
            )
            content.addWidget(self.look_enabled)
            content.addWidget(self.roaming_enabled)
            self.behavior_hint = label("", "muted")
            content.addWidget(self.behavior_hint)
            body.addWidget(frame)
        body.addWidget(label("없는 표정은 같은 캐릭터의 기본 모습으로 표시해요.", "muted"))
        self.status = label("")
        body.addWidget(self.status)
        body.addStretch()
        characters.changed.connect(self.refresh)
        characters.settings.changed.connect(self.refresh)
        self.refresh()

    def change_behavior(self, **changes) -> None:
        if not self.characters.settings.update(**changes):
            self.status.setText("움직임 설정을 저장하지 못했어요. 다시 시도해 주세요.")
        self.refresh()

    def showEvent(self, event):
        super().showEvent(event)
        if not self._loaded:
            self.load_previews()

    def load_previews(self):
        self._loaded = True
        for key, picture in self.previews.items():
            try:
                clips = self.characters.catalog.load(key)
                image = clips.get(self.state.currentData(), clips["idle"]).frames[0]
                picture.setPixmap(
                    image.scaled(
                        112,
                        112,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
                self.buttons[key].setEnabled(True)
            except ValueError:
                picture.setText("이미지 확인 필요")
                self.buttons[key].setEnabled(False)
        self.refresh()

    def refresh(self, *_args):
        for key, select in self.buttons.items():
            select.setText("선택됨" if key == self.characters.active_id else "선택하기")
        if hasattr(self, "look_enabled"):
            current = self.characters.settings.current
            with QSignalBlocker(self.look_enabled), QSignalBlocker(self.roaming_enabled):
                self.look_enabled.setChecked(current.cursor_look_enabled)
                self.roaming_enabled.setChecked(current.roaming_enabled)
            supported = {"look", "run_left", "run_right"} <= self.characters.clips.keys()
            self.look_enabled.setEnabled(supported)
            self.roaming_enabled.setEnabled(supported)
            self.behavior_hint.setText(
                "집중·수면·방해 금지·움직임 줄이기 중에는 쉬어요. 포인터가 가까우면 이동을 멈춰요."
                if supported
                else "치이카와·하치와레·우사기를 선택하면 사용할 수 있어요."
            )

    def choose(self, character_id):
        try:
            if not self.characters.select(character_id):
                self.status.setText("선택을 저장하지 못했어요. 다시 시도해 주세요.")
                return
        except ValueError as error:
            self.status.setText(str(error))
            return
        except Exception:
            self.status.setText("캐릭터를 바꾸지 못했어요. 다시 시도해 주세요.")
            return
        self.status.setText("선택했어요. 새 그림과 말투로 함께할게요.")
        self.refresh()
        self.selected.emit()


class CharacterPicker(QDialog):
    def __init__(self, characters, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"{APP_NAME} · 첫 캐릭터 선택")
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.resize(640, 480)
        body = QVBoxLayout(self)
        self.page = CharacterPage(characters, include_moru=False)
        self.page.selected.connect(self.accept)
        body.addWidget(self.page)
        body.addWidget(button("나중에 선택", self.reject))
