import asyncio
import json
import threading
import time

import httpx2
import pytest
from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from test_credentials import MemoryVault
from test_online_client import reply

from desktop_buddy.ai.client import ResponsesClient
from desktop_buddy.app import BuddyApplication
from desktop_buddy.database.store import Store
from desktop_buddy.models.online import OnlineError, OnlineResult
from desktop_buddy.services.api_key_service import ApiKeyService
from desktop_buddy.services.single_instance import SingleInstance
from desktop_buddy.ui.api_key_dialog import ApiKeyDialog


class DelayedClient:
    def __init__(self):
        self.calls = []
        self.release = threading.Event()
        self.release.set()
        self.started = threading.Event()
        self.ignore_cancel = False
        self.error = ""
        self.text = "답변 원문\nC:\\work\\print(x).py"
        self.proposal = None

    async def run(self, vault, request, cancelled, *, before_send=None):
        if before_send is not None:
            await before_send()
        self.calls.append((request, threading.get_ident()))
        self.started.set()
        try:
            while not self.release.is_set():
                await asyncio.sleep(0.005)
        except asyncio.CancelledError:
            if not self.ignore_cancel:
                raise
            await asyncio.sleep(0.03)
        if self.error:
            raise OnlineError(self.error)
        return OnlineResult(
            text=self.text, input_tokens=7, output_tokens=11, proposal=self.proposal
        )


def settle(qapp, predicate, seconds=3):
    until = time.monotonic() + seconds
    while not predicate() and time.monotonic() < until:
        qapp.processEvents()
        # Let Python workers run as QApplication.exec() does in the real app.
        # QTest.qWait can retain the GIL and starve a cold SDK import.
        time.sleep(0.005)
    qapp.processEvents()
    assert predicate()


@pytest.fixture
def online_app(qapp, tmp_path):
    vault = MemoryVault()
    vault.value = "not-a-real-key-for-online-tests"
    keys = ApiKeyService(vault)
    guard = SingleInstance(tmp_path)
    assert guard.acquire()
    client = DelayedClient()
    buddy = BuddyApplication(
        qapp,
        Store(tmp_path / "buddy.db"),
        guard,
        tmp_path,
        api_keys=keys,
        online_client=client,
        show_onboarding=False,
    )
    buddy.manager.navigate(buddy.manager.CHAT_PAGE)
    qapp.processEvents()
    yield buddy, client
    job = buddy.online._job
    client.release.set()
    buddy.shutdown()
    if job is not None:
        job.thread.join(timeout=1)
    qapp.processEvents()


def enable(online_app, qapp):
    buddy, client = online_app
    buddy.online.test_connection()
    settle(qapp, lambda: not buddy.online.busy)
    assert buddy.online.ready and not buddy.online.enabled
    buddy.online.set_enabled(True)
    return buddy, client


def test_default_off_and_connection_test_does_not_write_chat(online_app, qapp):
    buddy, client = online_app
    assert not buddy.online.enabled and not buddy.online.ready and not client.calls
    with pytest.raises(ValueError):
        buddy.online.set_enabled(True)
    buddy.online.test_connection()
    settle(qapp, lambda: not buddy.online.busy)
    assert buddy.online.ready and not buddy.online.enabled
    assert client.calls[0][0].text == "Connection test. Reply with OK only."
    assert client.calls[0][1] != threading.get_ident()
    assert not buddy.chat.messages() and buddy.online.usage == (7, 11)


def test_waiting_request_keeps_gui_and_timer_responsive_and_blocks_duplicate_send(online_app, qapp):
    buddy, client = enable(online_app, qapp)
    client.release.clear()
    client.started.clear()
    buddy.focus_timer.start(minutes=2)
    session = buddy.focus_timer.session_id
    beats = []
    timer = QTimer()
    timer.timeout.connect(lambda: beats.append(True))
    timer.start(5)
    request_id = buddy.online.send("자세하게 설명해 줘")
    settle(qapp, client.started.is_set)
    with pytest.raises(ValueError):
        buddy.online.send("중복 요청")
    settle(qapp, lambda: len(beats) >= 3)
    assert buddy.focus_timer.session_id == session and buddy.focus_timer.status == "running"
    assert buddy.online._active.id == request_id
    client.release.set()
    settle(qapp, lambda: not buddy.online.busy)
    timer.stop()
    assert buddy.chat.messages()[-1][2] == client.text
    assert not buddy.planning.repository.records("task")


@pytest.mark.parametrize(
    "transition",
    ["cancel", "mode", "character", "new", "history", "select", "model", "key", "page", "window"],
)
def test_late_reply_is_discarded_after_context_changes(online_app, qapp, transition):
    buddy, client = enable(online_app, qapp)
    buddy.chat.new_session()
    client.ignore_cancel = True
    client.release.clear()
    client.started.clear()
    buddy.online.send("늦게 도착할 질문")
    settle(qapp, client.started.is_set)
    session = buddy.chat.session_id
    if transition == "cancel":
        buddy.online.cancel()
    elif transition == "mode":
        buddy.online.set_enabled(False)
    elif transition == "character":
        buddy.characters.select("usagi")
    elif transition == "new":
        buddy.chat.new_session()
    elif transition == "history":
        buddy.chat.set_history(False)
    elif transition == "select":
        buddy.chat.select_session(session)
    elif transition == "model":
        buddy.online.set_model("gpt-other-model")
    elif transition == "key":
        buddy.api_keys.save("not-a-real-replacement-key")
    elif transition == "page":
        buddy.manager.navigate(0)
    else:
        buddy.manager.close()
    settle(qapp, lambda: not buddy.online.busy)
    assert client.text not in "\n".join(row[2] for row in buddy.chat.messages())
    assert client.text not in "\n".join(buddy.store.connection.iterdump())


def test_deadline_discards_response_and_offline_commands_still_work(online_app, qapp):
    buddy, client = enable(online_app, qapp)
    buddy.online.deadline = 0.03
    client.release.clear()
    buddy.online.send("시간 제한")
    settle(qapp, lambda: not buddy.online.busy)
    assert "제한 시간" in buddy.online.status
    buddy.online.set_enabled(False)
    buddy.chat.submit("25분 집중 시작")
    assert buddy.focus_timer.status == "running"


@pytest.mark.parametrize(
    "code", ["auth", "permission", "rate_limit", "network", "timeout", "model", "unknown"]
)
def test_failures_are_sanitized_and_do_not_automatically_retry(online_app, qapp, code):
    buddy, client = online_app
    client.error = code
    buddy.online.test_connection()
    settle(qapp, lambda: not buddy.online.busy)
    QTest.qWait(20)
    assert len(client.calls) == 1 and not buddy.online.ready and not buddy.online.enabled
    assert buddy.online.usage == (None, None)


@pytest.mark.parametrize("character", ["moru", "chiikawa", "hachiware", "usagi"])
def test_online_history_marks_ai_and_preserves_original_character(online_app, qapp, character):
    buddy, client = enable(online_app, qapp)
    buddy.characters.select(character)
    buddy.online.send("질문")
    settle(qapp, lambda: not buddy.online.busy)
    row = buddy.chat.messages()[-1]
    assert buddy.chat.message_modes([row[0]])[row[0]] == "ai"
    assert buddy.chat.message_speakers([row[0]])[row[0]] == character
    expected = "야하!! (" + client.text + ")" if character == "usagi" else client.text
    assert row[2] == expected
    buddy.characters.select("hachiware" if character != "hachiware" else "usagi")
    assert buddy.chat.messages()[-1][2] == expected


def test_history_off_uses_memory_without_persisting_ai_text(online_app, qapp):
    buddy, client = enable(online_app, qapp)
    buddy.chat.set_history(False)
    buddy.online.send("보관하지 않는 질문")
    settle(qapp, lambda: not buddy.online.busy)
    row = buddy.chat.messages()[-1]
    assert row[2] == client.text and buddy.chat.message_modes([row[0]])[row[0]] == "ai"
    assert client.text not in "\n".join(buddy.store.connection.iterdump())


def test_secret_input_is_rejected_before_saving_or_dispatch(online_app, qapp):
    buddy, client = enable(online_app, qapp)
    before = len(client.calls)
    canary = "sk-test-" + "x" * 32
    with pytest.raises(ValueError):
        buddy.online.send(canary)
    assert len(client.calls) == before and not buddy.chat.messages()


def test_storage_failure_before_send_does_not_make_request(online_app, qapp, monkeypatch):
    buddy, client = enable(online_app, qapp)
    before = len(client.calls)
    monkeypatch.setattr(
        buddy.chat.repository, "append", lambda *a, **k: (_ for _ in ()).throw(OSError())
    )
    buddy.online.send("아직 전송하면 안 되는 질문")
    settle(qapp, lambda: not buddy.online.busy)
    assert len(client.calls) == before and "저장하지 못" in buddy.online.status


def test_storage_failure_after_reply_does_not_report_success(online_app, qapp, monkeypatch):
    buddy, client = enable(online_app, qapp)
    client.release.clear()
    buddy.online.send("질문")
    monkeypatch.setattr(buddy.chat, "accept_online", lambda _: (_ for _ in ()).throw(OSError()))
    client.release.set()
    settle(qapp, lambda: not buddy.online.busy)
    assert "저장하지 못" in buddy.online.status and buddy.online.usage == (7, 11)
    assert len(client.calls) == 2


def test_shutdown_does_not_wait_for_worker_or_write_late_result(online_app, qapp):
    buddy, client = enable(online_app, qapp)
    client.ignore_cancel = True
    client.release.clear()
    client.started.clear()
    buddy.online.send("종료 뒤 남으면 안 되는 답변")
    settle(qapp, client.started.is_set)
    job = buddy.online._job
    started = time.monotonic()
    buddy.shutdown()
    assert time.monotonic() - started < 0.5
    job.thread.join(timeout=1)
    qapp.processEvents()
    assert not job.thread.is_alive()


def test_connection_dialog_blocks_unsaved_key_and_cancels_on_close(online_app, qapp):
    buddy, client = online_app
    dialog = ApiKeyDialog(buddy.api_keys, buddy.manager, online=buddy.online)
    dialog.show()
    dialog.input.setText("not-a-real-unsaved-new-key")
    dialog.test_connection()
    assert not client.calls and not dialog.input.text()
    client.release.clear()
    dialog.test_connection()
    assert buddy.online.busy
    dialog.close()
    settle(qapp, lambda: not buddy.online.busy)
    assert not buddy.online.ready


def test_chat_ui_keeps_failed_draft_and_never_auto_resends(online_app, qapp):
    buddy, client = enable(online_app, qapp)
    page = buddy.manager.chat_page
    client.error = "network"
    page.input.setText("다시 시도할 질문")
    page.send_button.click()
    settle(qapp, lambda: not buddy.online.busy)
    assert page.input.text() == "다시 시도할 질문"
    assert len(client.calls) == 2
    client.error = ""
    page.send_button.click()
    settle(qapp, lambda: not buddy.online.busy)
    assert not page.input.text() and "AI · 계획/타이머 실행 없음" in page.transcript.toPlainText()


def test_finishing_request_preserves_a_new_draft(online_app, qapp):
    buddy, client = enable(online_app, qapp)
    page = buddy.manager.chat_page
    client.release.clear()
    page.input.setText("보낼 질문")
    page.send_button.click()
    page.input.setText("새로 쓰는 초안")
    client.release.set()
    settle(qapp, lambda: not buddy.online.busy)
    assert page.input.text() == "새로 쓰는 초안"


def test_sdk_worker_sends_only_explicit_text_not_local_history_or_plan(
    online_app, qapp, monkeypatch
):
    buddy, _ = online_app
    buddy.chat.submit("할 일 추가: private-database-only-title")
    buddy.chat.confirm(buddy.chat.pending.request_id)
    main_thread = threading.get_ident()
    key_reads = []
    original = buddy.api_keys.vault.read

    def read():
        key_reads.append(threading.get_ident())
        return original()

    monkeypatch.setattr(buddy.api_keys.vault, "read", read)
    requests = []

    async def handler(request):
        requests.append(json.loads(request.content))
        await asyncio.sleep(0.01)
        return httpx2.Response(200, json=reply("저장했다는 텍스트일 뿐"))

    buddy.online.client = ResponsesClient(lambda: httpx2.MockTransport(handler))
    buddy.online.test_connection()
    # Allow cold lazy loading without assuming another test preloaded the SDK.
    settle(qapp, lambda: not buddy.online.busy, seconds=15)
    buddy.online.set_enabled(True)
    buddy.online.send("API 통합 테스트")
    settle(qapp, lambda: not buddy.online.busy)
    assert requests[-1]["input"] == "API 통합 테스트"
    assert "private-database-only-title" not in json.dumps(requests)
    assert all(thread != main_thread for thread in key_reads) and len(key_reads) == 2
    assert len(buddy.planning.repository.records("task")) == 1
    assert buddy.chat.messages()[-1][2] == "저장했다는 텍스트일 뿐"


def test_escape_cancels_ai_and_keeps_draft(online_app, qapp):
    buddy, client = enable(online_app, qapp)
    page = buddy.manager.chat_page
    client.release.clear()
    page.input.setText("취소할 입력")
    page.send_button.click()
    QTest.keyClick(page.input, Qt.Key.Key_Escape)
    settle(qapp, lambda: not buddy.online.busy)
    assert page.input.text() == "취소할 입력"


def test_secret_like_model_is_not_saved_or_dispatched(online_app, qapp):
    buddy, client = online_app
    canary = "sk-test-" + "x" * 32
    with pytest.raises(ValueError):
        buddy.online.set_model(canary)
    assert not client.calls and canary not in "\n".join(buddy.store.connection.iterdump())


def test_thread_start_failure_leaves_no_active_job(online_app, qapp, monkeypatch):
    buddy, client = online_app

    def fail(_):
        raise RuntimeError("do not expose raw error")

    monkeypatch.setattr("desktop_buddy.ai.job.OnlineJob.start", fail)
    with pytest.raises(ValueError):
        buddy.online.test_connection()
    assert not buddy.online.busy and not buddy.online.ready and not client.calls


def test_online_enablement_is_not_persisted(online_app, qapp):
    buddy, client = enable(online_app, qapp)
    assert "enabled" not in buddy.settings.current.to_mapping()
    assert "ai_enabled" not in "\n".join(buddy.store.connection.iterdump())
    buddy.online.set_enabled(False)
    assert not buddy.online.enabled


def test_saved_opaque_key_in_chat_is_neither_saved_nor_sent(online_app, qapp):
    buddy, _ = online_app
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        return httpx2.Response(200, json=reply("OK"))

    buddy.online.client = ResponsesClient(lambda: httpx2.MockTransport(handler))
    buddy.online.test_connection()
    settle(qapp, lambda: not buddy.online.busy, seconds=15)
    buddy.online.set_enabled(True)
    page = buddy.manager.chat_page
    canary = buddy.api_keys.vault.value
    page.input.setText(canary)
    page.send_button.click()
    settle(qapp, lambda: not buddy.online.busy)
    assert len(requests) == 1 and not page.input.text()
    assert canary not in "\n".join(buddy.store.connection.iterdump())


def test_cancel_during_key_lookup_never_starts_http_or_saves_input(online_app, qapp, monkeypatch):
    buddy, _ = enable(online_app, qapp)
    entered, release = threading.Event(), threading.Event()
    calls = []

    def read():
        entered.set()
        release.wait(timeout=2)
        return "not-a-real-key-for-read-test"

    monkeypatch.setattr(buddy.api_keys.vault, "read", read)
    buddy.online.client = ResponsesClient(lambda: httpx2.MockTransport(lambda r: calls.append(r)))
    buddy.online.send("아직 보내지 않을 질문")
    settle(qapp, entered.is_set)
    buddy.online.cancel()
    release.set()
    settle(qapp, lambda: not buddy.online.busy)
    assert not calls and not buddy.chat.messages()


def test_cancelling_after_sensitive_failure_keeps_a_new_normal_draft(online_app, qapp):
    buddy, client = enable(online_app, qapp)
    page = buddy.manager.chat_page
    client.error = "sensitive"
    page.input.setText("첫 번째 질문")
    page.send_button.click()
    settle(qapp, lambda: not buddy.online.busy)
    assert not page.input.text()
    client.error = ""
    client.release.clear()
    page.input.setText("취소해도 남길 초안")
    page.send_button.click()
    buddy.online.cancel()
    settle(qapp, lambda: not buddy.online.busy)
    assert page.input.text() == "취소해도 남길 초안"


def test_wrapped_usage_status_is_not_clipped_after_async_completion(online_app, qapp):
    buddy, client = online_app
    buddy.manager.resize(560, 360)
    dialog = ApiKeyDialog(buddy.api_keys, buddy.manager, online=buddy.online)
    dialog.show()
    dialog.test_connection()
    settle(qapp, lambda: not buddy.online.busy)
    QTest.qWait(30)
    qapp.processEvents()
    assert dialog.online_status.height() + 2 >= dialog.online_status.heightForWidth(
        dialog.online_status.width()
    )
    dialog.close()
    buddy.online.set_enabled(True)
    buddy.online.send("두 줄 상태의 높이 확인")
    settle(qapp, lambda: not buddy.online.busy)
    QTest.qWait(30)
    qapp.processEvents()
    field = buddy.manager.chat_page.ai_status
    assert field.height() + 2 >= field.heightForWidth(field.width())
