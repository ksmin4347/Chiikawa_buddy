from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLineEdit, QMessageBox, QVBoxLayout

from desktop_buddy.security.credentials import MAX_KEY_LENGTH, CredentialError
from desktop_buddy.services.api_key_service import ApiKeyService
from desktop_buddy.ui.common import button, fit_window, label


class ApiKeyDialog(QDialog):
    def __init__(self, service: ApiKeyService, parent=None):
        super().__init__(parent)
        self.service = service
        self.setWindowTitle("먼작귀 · API 키 관리")
        self.resize(500, 430)
        body = QVBoxLayout(self)
        body.setContentsMargins(22, 20, 22, 20)
        body.setSpacing(14)
        body.addWidget(label("AI 연결을 준비해요", "heading"))
        body.addWidget(label("현재는 오프라인 모드예요. 여기에서는 키 보관만 관리해요.", "muted"))
        body.addWidget(
            label("본인의 OpenAI API 키를 입력하세요. 저장해도 요청·과금은 발생하지 않아요.")
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
        self.status = label("")
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
        self.close_button = button("닫기", self.reject)
        self.close_button.setAutoDefault(False)
        body.addWidget(self.close_button)
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
            "키가 저장되어 있어요. 연결·키 유효성은 아직 확인하지 않았어요."
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
            self.status.setText("키를 저장했어요. 연결·키 유효성 확인은 아직 수행하지 않았어요.")
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
        super().done(result)

    def hideEvent(self, event) -> None:
        self.input.setText("")
        super().hideEvent(event)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        fit_window(self)
