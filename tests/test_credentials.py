import ctypes
import sys
from unittest.mock import Mock

import pytest

from desktop_buddy.security import credentials
from desktop_buddy.security.credentials import Credential, CredentialError, WindowsCredentialVault
from desktop_buddy.services.api_key_service import ApiKeyService


class MemoryVault:
    def __init__(self):
        self.value = None
        self.failure = None
        self.reads = 0

    def _check(self):
        if self.failure:
            raise RuntimeError(self.failure)

    def exists(self):
        self._check()
        return self.value is not None

    def write(self, secret):
        self._check()
        self.value = secret

    def read(self):
        self.reads += 1
        self._check()
        return self.value

    def delete(self):
        self._check()
        self.value = None


class NativeApi:
    def __init__(self):
        self.value = b"not-a-real-credential-value"
        self.fail = False
        self.CredReadW = Mock(side_effect=self._read)
        self.CredWriteW = Mock(side_effect=self._write)
        self.CredDeleteW = Mock(side_effect=lambda *_: not self.fail)
        self.CredFree = Mock()

    def _read(self, target, kind, flags, output):
        assert kind == 1 and flags == 0
        if self.fail:
            return False
        self.blob = (ctypes.c_ubyte * len(self.value))(*self.value)
        self.record = Credential()
        self.record.CredentialBlobSize = len(self.blob)
        self.record.CredentialBlob = self.blob
        ctypes.cast(output, ctypes.POINTER(ctypes.POINTER(Credential)))[0] = ctypes.pointer(
            self.record
        )
        return True

    def _write(self, pointer, flags):
        record = ctypes.cast(pointer, ctypes.POINTER(Credential)).contents
        assert flags == 0 and record.Type == 1 and record.Persist == 2
        assert record.TargetName == credentials.TARGET
        self.written = ctypes.string_at(record.CredentialBlob, record.CredentialBlobSize)
        return not self.fail


@pytest.fixture
def native(monkeypatch):
    api = NativeApi()
    loader = Mock(return_value=api)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(ctypes, "WinDLL", loader, raising=False)
    return WindowsCredentialVault(), api, loader


@pytest.mark.parametrize(
    "value", ["", "short", "x" * 513, "x" * 16 + " ", "x" * 16 + "\n", "한글" * 16, "x" * 16 + "\0"]
)
def test_invalid_input_never_reaches_storage(value):
    vault = MemoryVault()
    with pytest.raises(CredentialError):
        ApiKeyService(vault).save(value)
    assert vault.value is None


@pytest.mark.parametrize("length", [16, 512])
def test_supported_input_bounds_and_notifications(length, qapp):
    vault = MemoryVault()
    service = ApiKeyService(vault)
    observed = []
    service.changed.connect(lambda *args: observed.append(args))
    service.save("a" * length)
    assert service.stored() and vault.reads == 0
    service.delete()
    service.delete()
    assert not service.stored() and observed == [(), (), ()]


@pytest.mark.parametrize("operation", ["stored", "save", "delete"])
def test_storage_failures_are_sanitized_without_success_signals(operation, qapp, caplog):
    canary = "not-a-real-key-for-failure-test"
    vault = MemoryVault()
    vault.failure = canary
    service = ApiKeyService(vault)
    changed = []
    service.changed.connect(lambda: changed.append(True))
    with pytest.raises(CredentialError) as caught:
        getattr(service, operation)(*([canary] if operation == "save" else []))
    assert canary not in str(caught.value) and canary not in caplog.text
    assert not changed


def test_native_read_is_bounded_freed_and_scrubbed(native):
    vault, api, loader = native
    assert vault.read() == api.value.decode("ascii")
    assert bytes(api.blob) == b"\0" * len(api.value)
    api.CredFree.assert_called_once()
    loader.assert_called_once_with("Advapi32.dll", use_last_error=True, winmode=0x800)


def test_presence_check_does_not_decode_or_materialize_the_key(native, monkeypatch):
    vault, api, loader = native
    monkeypatch.setattr(ctypes, "string_at", Mock(side_effect=AssertionError("decoded secret")))
    assert vault.exists()
    api.CredFree.assert_called_once()
    assert bytes(api.blob) == b"\0" * len(api.value)


def test_invalid_existing_item_can_still_be_replaced_or_deleted(native):
    vault, api, loader = native
    for invalid in (b"", b"short", b"x" * 513, b"\xff" * 20):
        api.value = invalid
        assert vault.exists()
        with pytest.raises(CredentialError):
            vault.read()
    assert api.CredFree.call_count == 8


@pytest.mark.parametrize("content", [b"short", b"x" * 513, b"\xff" * 20])
def test_bad_native_blob_is_rejected_and_freed(native, content):
    vault, api, loader = native
    api.value = content
    with pytest.raises(CredentialError):
        vault.read()
    api.CredFree.assert_called_once()


@pytest.mark.parametrize("success", [True, False])
def test_native_write_scrubs_the_temporary_buffer_even_on_failure(native, monkeypatch, success):
    vault, api, loader = native
    api.fail = not success
    original = ctypes.memset
    erased = []

    def scrub(pointer, value, size):
        result = original(pointer, value, size)
        erased.append(ctypes.string_at(pointer, size))
        return result

    monkeypatch.setattr(ctypes, "memset", scrub)
    if success:
        vault.write(api.value.decode("ascii"))
    else:
        with pytest.raises(CredentialError):
            vault.write(api.value.decode("ascii"))
    assert api.written == api.value
    assert erased == [b"\0" * len(api.value)]


@pytest.mark.parametrize("error", [1168, 5, 1312])
def test_missing_credential_is_distinct_from_access_failure(native, monkeypatch, error):
    vault, api, loader = native
    api.fail = True
    monkeypatch.setattr(ctypes, "get_last_error", lambda: error, raising=False)
    if error == 1168:
        assert vault.read() is None and not vault.exists()
        vault.delete()
    else:
        for operation in (vault.read, vault.exists, vault.delete):
            with pytest.raises(CredentialError):
                operation()
    api.CredFree.assert_not_called()


def test_unsupported_platform_does_not_create_plaintext_fallback(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "linux")
    with pytest.raises(CredentialError, match="Windows"):
        WindowsCredentialVault().write("not-a-real-key-for-test")
    assert not list(tmp_path.iterdir())
