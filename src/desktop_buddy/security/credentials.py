"""User-scoped Windows credentials. Never fall back to plaintext storage."""

import ctypes
import sys
from ctypes import wintypes
from typing import Protocol

TARGET = "DesktopBuddy/OpenAI/APIKey"
MAX_KEY_LENGTH = 512
ERROR_NOT_FOUND = 1168
CRED_TYPE_GENERIC = 1
CRED_PERSIST_LOCAL_MACHINE = 2


class CredentialError(RuntimeError):
    """A sanitized error that never includes credential material."""

    def __init__(self, message: str, *, winerror: int | None = None):
        super().__init__(message)
        self.winerror = winerror


class CredentialVault(Protocol):
    def exists(self) -> bool: ...
    def write(self, secret: str) -> None: ...
    def read(self) -> str | None: ...
    def delete(self) -> None: ...


def validate_key(secret: str) -> None:
    # This checks local input limits, not account access or API authentication.
    if not 16 <= len(secret) <= MAX_KEY_LENGTH or any(not 33 <= ord(c) <= 126 for c in secret):
        raise CredentialError("공백 없는 영문·숫자·기호 16~512자로 키를 입력해 주세요.")


class Credential(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR),
        ("LastWritten", wintypes.FILETIME),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


class WindowsCredentialVault:
    def __init__(self, target: str = TARGET):
        if not target.startswith("DesktopBuddy/") or len(target) > 256 or "\0" in target:
            raise ValueError("앱 자격 증명 이름을 확인해 주세요.")
        self.target = target
        self._library = None

    def _api(self):
        if self._library is None:
            if sys.platform != "win32":
                raise CredentialError("Windows 자격 증명 관리자가 필요해요.")
            try:
                library = ctypes.WinDLL("Advapi32.dll", use_last_error=True, winmode=0x800)
                library.CredWriteW.argtypes = [ctypes.POINTER(Credential), wintypes.DWORD]
                library.CredWriteW.restype = wintypes.BOOL
                library.CredReadW.argtypes = [
                    wintypes.LPCWSTR,
                    wintypes.DWORD,
                    wintypes.DWORD,
                    ctypes.POINTER(ctypes.POINTER(Credential)),
                ]
                library.CredReadW.restype = wintypes.BOOL
                library.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
                library.CredDeleteW.restype = wintypes.BOOL
                library.CredFree.argtypes = [ctypes.c_void_p]
                library.CredFree.restype = None
                self._library = library
            except (OSError, AttributeError):
                raise CredentialError("Windows 키 저장소를 열지 못했어요.") from None
        return self._library

    def write(self, secret: str) -> None:
        validate_key(secret)
        library = self._api()
        blob = (ctypes.c_ubyte * len(secret))(*secret.encode("ascii"))
        credential = Credential()
        credential.Type = CRED_TYPE_GENERIC
        credential.TargetName = self.target
        credential.UserName = "OpenAI"
        credential.CredentialBlobSize = len(blob)
        credential.CredentialBlob = blob
        credential.Persist = CRED_PERSIST_LOCAL_MACHINE
        try:
            if not library.CredWriteW(ctypes.byref(credential), 0):
                raise CredentialError(
                    "Windows 키 저장소에 저장하지 못했어요.", winerror=ctypes.get_last_error()
                )
        finally:
            ctypes.memset(blob, 0, len(blob))

    def _read(self, *, presence_only: bool) -> str | bool | None:
        library = self._api()
        pointer = ctypes.POINTER(Credential)()
        if not library.CredReadW(self.target, CRED_TYPE_GENERIC, 0, ctypes.byref(pointer)):
            if ctypes.get_last_error() == ERROR_NOT_FOUND:
                return False if presence_only else None
            raise CredentialError(
                "Windows 키 저장 상태를 확인하지 못했어요.", winerror=ctypes.get_last_error()
            )
        try:
            if not pointer:
                raise CredentialError("저장된 키 항목을 확인해 주세요.")
            credential = pointer.contents
            if presence_only:
                return True
            size = credential.CredentialBlobSize
            if not 16 <= size <= MAX_KEY_LENGTH or not credential.CredentialBlob:
                raise CredentialError("저장된 키 형식을 확인해 주세요.")
            try:
                secret = ctypes.string_at(credential.CredentialBlob, size).decode("ascii")
            except UnicodeDecodeError:
                raise CredentialError("저장된 키 형식을 확인해 주세요.") from None
            validate_key(secret)
            return secret
        finally:
            if pointer:
                credential = pointer.contents
                if credential.CredentialBlob and credential.CredentialBlobSize <= 2560:
                    ctypes.memset(credential.CredentialBlob, 0, credential.CredentialBlobSize)
                library.CredFree(pointer)

    def exists(self) -> bool:
        return self._read(presence_only=True) is True

    def read(self) -> str | None:
        value = self._read(presence_only=False)
        return value if isinstance(value, str) else None

    def delete(self) -> None:
        library = self._api()
        if not library.CredDeleteW(self.target, CRED_TYPE_GENERIC, 0):
            if ctypes.get_last_error() != ERROR_NOT_FOUND:
                raise CredentialError(
                    "Windows 키 저장소에서 삭제하지 못했어요.", winerror=ctypes.get_last_error()
                )
