from PySide6.QtCore import QObject, Signal

from desktop_buddy.security.credentials import CredentialError, CredentialVault, validate_key


class ApiKeyService(QObject):
    changed = Signal()

    def __init__(self, vault: CredentialVault):
        super().__init__()
        self.vault = vault

    def stored(self) -> bool:
        try:
            return self.vault.exists()
        except Exception:
            raise CredentialError("Windows 키 저장 상태를 확인하지 못했어요.") from None

    def save(self, secret: str) -> None:
        validate_key(secret)
        try:
            self.vault.write(secret)
        except Exception:
            raise CredentialError("키를 저장하지 못했어요. 입력을 다시 확인해 주세요.") from None
        self.changed.emit()

    def delete(self) -> None:
        try:
            self.vault.delete()
        except Exception:
            raise CredentialError(
                "키를 삭제하지 못했어요. 저장 상태를 다시 확인해 주세요."
            ) from None
        self.changed.emit()
