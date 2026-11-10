from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from desktop_buddy.security.credentials import MAX_KEY_LENGTH, CredentialError
from desktop_buddy.services.api_key_service import ApiKeyService
from desktop_buddy.ui.common import WrappedStatus, button, fit_window, label


class ApiKeyDialog(QDialog):
    def __init__(self, service: ApiKeyService, parent=None, *, online=None):
        super().__init__(parent)
        self.service = service
        self.online = online
        self.setWindowTitle("먼작귀 · API 키 관리")
        self.resize(520, 620 if online is not None else 460)
        outer = QVBoxLayout(self)
        self.area = QScrollArea()
        self.area.setWidgetResizable(True)
        page = QWidget()
        self.area.setWidget(page)
        outer.addWidget(self.area)
        body = QVBoxLayout(page)
        body.setContentsMargins(22, 20, 22, 20)
        body.setSpacing(14)
        body.addWidget(label("API 키와 연결", "heading"))
        body.addWidget(label("키를 저장해도 자동으로 연결하지 않아요.", "muted"))
        body.addWidget(
            label("본인의 OpenAI API 키를 입력하세요. 키 보관 자체는 요청·과금이 없어요.")
        )
        self.input = QLineEdit()
        self.input.setEchoMode(QLineEdit.EchoMode.Password)
        self.input.setMaxLength(MAX_KEY_LENGTH + 1)
        self.input.setInputMethodHints(
            Qt.InputMethodHint.ImhHiddenText
            | Qt.InputMethodHint.ImhSensitiveData
            | Qt.InputMethodHint.ImhNoPredictiveText
        )
        self.input.setAccessibleName("OpenAI API 키 입력")
        self.input.setAccessibleDescription("마스킹된 새 키 입력이에요. 처리 후 입력을 지워요.")
        self.input.setPlaceholderText("새 키 입력 · 저장된 키는 다시 표시하지 않아요")
        body.addWidget(self.input)
        body.addWidget(label("키는 이 Windows 계정의 자격 증명 관리자에 보관해요.", "muted"))
        self.status = WrappedStatus()
        self.status.setAccessibleName("API 키 저장 상태")
        body.addWidget(self.status)
        row = QHBoxLayout()
        self.save_button = button("키 저장", self.save, True)
        self.delete_button = button("저장된 키 삭제", self.delete)
        self.check_button = button("저장 상태 확인", self.refresh_status)
        for widget in (self.save_button, self.delete_button, self.check_button):
            widget.setAutoDefault(False)
            row.addWidget(widget)
        body.addLayout(row)
        if online is not None:
            body.addWidget(label("연결할 모델", "heading"))
            self.model = QLineEdit(online.settings.current.ai_model)
            self.model.setMaxLength(129)
            self.model.setAccessibleName("OpenAI 모델 ID")
            body.addWidget(self.model)
            body.addWidget(
                label(
                    "연결 테스트는 저장된 키로 고정 시험 문장만 OpenAI에 보내요. "
                    "API 비용이 발생할 수 있어요. "
                    "취소해도 이미 전송된 요청의 처리·요금이 취소된다는 보장은 없어요.",
                    "muted",
                )
            )
            self.online_status = WrappedStatus()
            self.online_status.setAccessibleName("AI 연결 상태")
            body.addWidget(self.online_status)
            row = QHBoxLayout()
            self.test_button = button("연결 테스트 (API 요청)", self.test_connection, True)
            self.cancel_button = button("요청 취소", online.cancel)
            self.test_button.setAutoDefault(False)
            self.cancel_button.setAutoDefault(False)
            row.addWidget(self.test_button)
            row.addWidget(self.cancel_button)
            body.addLayout(row)
            online.changed.connect(self.refresh_online)
            self.refresh_online()
        self.close_button = button("닫기", self.reject)
        self.close_button.setAutoDefault(False)
        outer.addWidget(self.close_button)
        self.refresh_status()
        self.input.setFocus()

    def refresh_status(self) -> None:
        try:
            present = self.service.stored()
        except CredentialError as error:
            self.status.setText(str(error))
            self.delete_button.setEnabled(False)
            return
        self.delete_button.setEnabled(present)
        self.status.setText(
            "키가 저장되어 있어요. 연결 여부는 채팅의 연결 상태에서 확인해요."
            if present
            else "저장된 키가 없어요. 오프라인 기능은 그대로 사용할 수 있어요."
        )

    def _confirm(self, text: str) -> bool:
        return (
            QMessageBox.question(
                self,
                "API 키 관리",
                text,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            == QMessageBox.StandardButton.Yes
        )

    def save(self) -> None:
        secret = self.input.text()
        self.input.setText("")
        try:
            if self.service.stored() and not self._confirm("이미 저장된 키를 새 키로 바꿀까요?"):
                self.status.setText("키 교체를 취소했어요. 입력은 지웠어요.")
                return
            self.service.save(secret)
            self.delete_button.setEnabled(True)
            self.status.setText("키를 저장했어요. 연결 테스트는 별도로 시작해 주세요.")
        except CredentialError as error:
            self.status.setText(str(error) + " 입력은 지웠어요.")
        finally:
            secret = ""

    def delete(self) -> None:
        self.input.setText("")
        if not self._confirm("이 앱에 저장된 API 키만 삭제할까요? 계획과 공부 기록은 유지돼요."):
            return
        try:
            self.service.delete()
            self.delete_button.setEnabled(False)
            self.status.setText("저장된 키를 삭제했어요. 오프라인 기능은 그대로 사용할 수 있어요.")
        except CredentialError as error:
            self.status.setText(str(error))

    def done(self, result: int) -> None:
        self.input.setText("")
        if self.online is not None and self.online.kind == "test":
            self.online.cancel()
        super().done(result)

    def hideEvent(self, event) -> None:
        self.input.setText("")
        if self.online is not None and self.online.kind == "test":
            self.online.cancel()
        super().hideEvent(event)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        fit_window(self)

    def refresh_online(self) -> None:
        online = self.online
        text = online.status
        if online.usage is not None:
            counts = [str(value) if value is not None else "확인 불가" for value in online.usage]
            text += f"\n입력 {counts[0]} · 출력 {counts[1]} 토큰 (계정 청구액 아님)"
        self.online_status.setText(text)
        self.test_button.setEnabled(not online.busy)
        self.cancel_button.setEnabled(online.busy)
        self.model.setEnabled(not online.busy)

    def test_connection(self) -> None:
        if self.input.text():
            self.input.setText("")
            self.status.setText("입력 중인 키는 지웠어요. 먼저 키를 저장하고 테스트해 주세요.")
            return
        try:
            self.online.set_model(self.model.text())
            self.online.test_connection()
        except ValueError as error:
            self.model.setText(self.online.settings.current.ai_model)
            self.online_status.setText(str(error))
