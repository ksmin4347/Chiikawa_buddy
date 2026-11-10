import json
from uuid import uuid4

import pytest
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAccessible
from PySide6.QtTest import QTest
from test_credentials import MemoryVault

from desktop_buddy.app import BuddyApplication
from desktop_buddy.database.store import Store
from desktop_buddy.security.credentials import TARGET
from desktop_buddy.services.api_key_service import ApiKeyService
from desktop_buddy.services.single_instance import SingleInstance
from desktop_buddy.ui.api_key_dialog import ApiKeyDialog


@pytest.fixture
def key_app(qapp, tmp_path):
    vault = MemoryVault()
    keys = ApiKeyService(vault)
    guard = SingleInstance(tmp_path)
    assert guard.acquire()
    store = Store(tmp_path / "buddy.db")
    buddy = BuddyApplication(qapp, store, guard, tmp_path, show_onboarding=False, api_keys=keys)
    buddy.manager.navigate(buddy.manager.SETTINGS_PAGE)
    yield buddy, keys, vault
    buddy.shutdown()


def show_dialog(key_app, qapp):
    buddy, keys, vault = key_app
    dialog = ApiKeyDialog(keys, buddy.manager)
    dialog.show()
    qapp.processEvents()
    return dialog


def test_key_dialog_masks_input_and_never_loads_the_stored_value(key_app, qapp):
    buddy, keys, vault = key_app
    vault.value = "not-a-real-key-" + uuid4().hex
    dialog = show_dialog(key_app, qapp)
    assert not dialog.input.text() and vault.reads == 0
    dialog.input.setText(vault.value)
    assert dialog.input.echoMode() == dialog.input.EchoMode.Password
    assert vault.value not in dialog.input.displayText()
    interface = QAccessible.queryAccessibleInterface(dialog.input)
    assert interface.text(QAccessible.Text.Value) != vault.value
    assert dialog.delete_button.isEnabled()


def test_save_clears_input_and_undo_without_persisting_secret_in_app_data(key_app, qapp, tmp_path):
    buddy, keys, vault = key_app
    dialog = show_dialog(key_app, qapp)
    canary = "not-a-real-key-" + uuid4().hex
    dialog.input.setText(canary)
    dialog.save_button.click()
    assert vault.value == canary and not dialog.input.text()
    assert not dialog.input.isUndoAvailable()
    QTest.keyClick(dialog.input, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    assert not dialog.input.text() and vault.reads == 0
    assert canary not in "\n".join(buddy.store.connection.iterdump())
    assert canary not in json.dumps(buddy.store.load_settings().__dict__)
    for path in tmp_path.rglob("*"):
        if path.is_file() and path.suffix in (".db", ".json", ".log"):
            assert canary.encode() not in path.read_bytes()


def test_failed_save_wipes_input_and_hides_raw_error(key_app, qapp, caplog):
    buddy, keys, vault = key_app
    dialog = show_dialog(key_app, qapp)
    canary = "not-a-real-key-" + uuid4().hex
    vault.failure = canary
    dialog.input.setText(canary)
    dialog.save()
    assert not dialog.input.text() and vault.value is None
    assert canary not in dialog.status.text() and canary not in caplog.text


@pytest.mark.parametrize("approved", [False, True])
def test_replacement_invalidates_pending_only_after_approved_success(
    key_app, qapp, monkeypatch, approved
):
    buddy, keys, vault = key_app
    vault.value = "not-a-real-old-key-value"
    buddy.chat.submit("할 일 추가: 키 교체 전에 만든 카드")
    pending = buddy.chat.pending
    buddy.focus_timer.start(minutes=2)
    session_id = buddy.focus_timer.session_id
    dialog = show_dialog(key_app, qapp)
    monkeypatch.setattr(dialog, "_confirm", lambda _: approved)
    dialog.input.setText("not-a-real-new-key-value")
    dialog.save()
    assert not dialog.input.text()
    assert buddy.focus_timer.session_id == session_id and buddy.focus_timer.status == "running"
    assert not buddy.planning.repository.records("task")
    if approved:
        assert vault.value == "not-a-real-new-key-value" and buddy.chat.pending is None
    else:
        assert vault.value == "not-a-real-old-key-value" and buddy.chat.pending is pending


@pytest.mark.parametrize("approved", [False, True])
def test_delete_confirmation_preserves_plan_and_offline_timer(key_app, qapp, monkeypatch, approved):
    buddy, keys, vault = key_app
    vault.value = "not-a-real-key-for-deletion"
    dialog = show_dialog(key_app, qapp)
    monkeypatch.setattr(dialog, "_confirm", lambda _: approved)
    buddy.chat.submit("할 일 추가: 키 삭제 뒤에도 오프라인")
    buddy.chat.confirm(buddy.chat.pending.request_id)
    records = buddy.planning.repository.records("task")
    dialog.delete()
    assert (vault.value is None) == approved
    assert buddy.planning.repository.records("task") == records
    buddy.focus_timer.start(minutes=1)
    assert buddy.focus_timer.status == "running"


@pytest.mark.parametrize("action", ["reject", "close", "hide"])
def test_dismissing_dialog_erases_unsubmitted_input(key_app, qapp, action):
    dialog = show_dialog(key_app, qapp)
    dialog.input.setText("not-a-real-key-before-close")
    getattr(dialog, action)()
    qapp.processEvents()
    assert not dialog.input.text() and not dialog.input.isUndoAvailable()
    assert key_app[2].value is None


def test_overlong_key_is_not_silently_saved_as_a_truncated_key(key_app, qapp):
    dialog = show_dialog(key_app, qapp)
    dialog.input.setText("a" * 1000)
    dialog.save()
    assert key_app[2].value is None and not dialog.input.text()


def test_settings_button_opens_real_modal_and_restores_focus(key_app, qapp):
    buddy, keys, vault = key_app
    observed = []

    def close_modal():
        dialog = qapp.activeModalWidget()
        observed.append(isinstance(dialog, ApiKeyDialog))
        dialog.reject()

    QTimer.singleShot(50, close_modal)
    buddy.manager.api_key_button.click()
    qapp.processEvents()
    assert observed == [True] and buddy.manager.api_key_button.hasFocus()


def test_separate_data_folder_does_not_use_production_credential_target(qapp, tmp_path):
    guard = SingleInstance(tmp_path)
    assert guard.acquire()
    buddy = BuddyApplication(
        qapp, Store(tmp_path / "buddy.db"), guard, tmp_path, show_onboarding=False
    )
    try:
        assert buddy.api_keys.vault.target != TARGET
        assert buddy.api_keys.vault.target.startswith("DesktopBuddy/Development/")
        assert buddy.api_keys.vault._library is None
    finally:
        buddy.shutdown()


def test_unavailable_store_and_failed_deletion_do_not_expose_secret(key_app, qapp, monkeypatch):
    buddy, keys, vault = key_app
    vault.value = "not-a-real-stored-credential"
    vault.failure = vault.value
    dialog = show_dialog(key_app, qapp)
    assert not dialog.delete_button.isEnabled()
    assert vault.value not in dialog.status.text()
    vault.failure = None
    dialog.refresh_status()
    assert dialog.delete_button.isEnabled()
    monkeypatch.setattr(dialog, "_confirm", lambda _: True)
    vault.failure = vault.value
    dialog.delete()
    assert vault.value is not None and vault.value not in dialog.status.text()


def test_failed_write_keeps_existing_confirmation_pending(key_app, qapp, monkeypatch):
    buddy, keys, vault = key_app
    dialog = show_dialog(key_app, qapp)
    buddy.chat.submit("할 일 추가: 키 저장 실패 때 유지할 카드")
    pending = buddy.chat.pending
    canary = "not-a-real-key-" + uuid4().hex

    def fail(_):
        raise OSError(canary)

    monkeypatch.setattr(vault, "write", fail)
    dialog.input.setText(canary)
    dialog.save()
    assert buddy.chat.pending is pending and not dialog.input.text()
    assert canary not in dialog.status.text()


def test_default_folder_uses_stable_lazy_target_without_accessing_credentials(
    qapp, tmp_path, monkeypatch
):
    monkeypatch.setattr("desktop_buddy.app.data_directory", lambda: tmp_path)
    guard = SingleInstance(tmp_path)
    assert guard.acquire()
    buddy = BuddyApplication(
        qapp, Store(tmp_path / "buddy.db"), guard, tmp_path, show_onboarding=False
    )
    try:
        assert buddy.api_keys.vault.target == TARGET
        assert buddy.api_keys.vault._library is None
    finally:
        buddy.shutdown()
