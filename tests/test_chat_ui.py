import sqlite3

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from test_focus import advance
from test_focus_ui import controller as _controller_fixture

chat_controller = _controller_fixture


def send(page, text):
    page.input.setText(text)
    page.send_button.click()


def test_chat_commands_choice_confirmation_navigation(chat_controller, qapp):
    buddy, _ = chat_controller
    manager = buddy.manager
    manager.open_page(manager.CHAT_PAGE)
    page = manager.chat_page
    assert page.isVisible() and manager.pages.count() == 8
    send(page, "내일 오후 3시에 알고리즘 공부 추가해줘")
    assert page.choices.isVisible() and page.choices.count() == 2
    assert not buddy.planning.repository.records("task")
    page.confirm_button.click()
    assert not page.choices.isVisible() and buddy.chat.pending
    page.confirm_button.click()
    assert len(buddy.planning.repository.records("task")) == 1
    assert not page.proposal.isVisible()
    send(page, "설정 열어줘")
    assert manager.pages.currentIndex() == manager.SETTINGS_PAGE
    manager.open_page(manager.CHAT_PAGE)
    send(page, "캘린더 열어줘")
    assert manager.pages.currentIndex() == 2
    manager.open_page(manager.CHAT_PAGE)
    page.input.setText("오늘 할 일 보여줘")
    QTest.keyClick(page.input, Qt.Key.Key_Return)
    assert not page.input.text() and "할 일" in page.transcript.toPlainText()


def test_ui_failure_retains_input_confirmation_retries_and_secret_clears(
    chat_controller, monkeypatch
):
    buddy, _ = chat_controller
    buddy.manager.open_page(buddy.manager.CHAT_PAGE)
    page = buddy.manager.chat_page
    send(page, "지원하지 않는 문장")
    assert page.input.text() == "지원하지 않는 문장" and page.error.isVisible()
    send(page, "할 일 추가: 저장 실패 복구")
    request_id = buddy.chat.pending.request_id
    original = buddy.chat.executor.repository.complete
    monkeypatch.setattr(
        buddy.chat.executor.repository,
        "complete",
        lambda *args: (_ for _ in ()).throw(sqlite3.OperationalError("full")),
    )
    page.confirm_button.click()
    assert buddy.chat.pending.request_id == request_id
    assert page.confirm_button.isEnabled() and page.error.isVisible()
    assert not buddy.planning.repository.records("task")
    monkeypatch.setattr(buddy.chat.executor.repository, "complete", original)
    page.confirm_button.click()
    assert len(buddy.planning.repository.records("task")) == 1
    canary = "sk-example_" + "NEVER_STORE_0123456789"
    send(page, canary)
    assert not page.input.text() and page.error.isVisible()
    assert canary not in page.transcript.toPlainText()
    assert canary.encode() not in buddy.store.path.read_bytes()


def test_chat_timer_updates_existing_ui_and_history_controls(chat_controller, qapp):
    buddy, clock = chat_controller
    manager = buddy.manager
    manager.open_page(manager.CHAT_PAGE)
    page = manager.chat_page
    send(page, "1분 집중 시작")
    assert buddy.focus_timer.status == "running"
    assert buddy.animation.base_state == "focus"
    advance(buddy.focus_timer, clock, 10)
    send(page, "타이머 일시정지")
    assert buddy.focus_timer.status == "paused"
    send(page, "타이머 중지")
    page.confirm_button.click()
    assert buddy.statistics.all_total() == 10
    page.history.setChecked(False)
    assert not buddy.chat.history_enabled
    send(page, "오늘 얼마나 공부했어?")
    assert "10초" in page.transcript.toPlainText()
    page.history.setChecked(True)
    assert not page.transcript.toPlainText()
    send(page, "안녕")
    assert page.sessions.count() >= 2


def test_plain_text_history_pagination_and_minimum_size(chat_controller, qapp):
    buddy, _ = chat_controller
    manager = buddy.manager
    manager.open_page(manager.CHAT_PAGE)
    page = manager.chat_page
    for _ in range(26):
        buddy.chat.submit("내 상태 알려줘")
    assert len(page._rows) == 50 and page.older.isEnabled()
    page.older.click()
    assert len(page._rows) == 52 and not page.older.isEnabled()
    send(page, "할 일 추가: <b>서식 없는 제목</b>")
    assert "<b>서식 없는 제목</b>" in page.transcript.toPlainText()
    manager.resize(720, 560)
    qapp.processEvents()
    assert manager.size().width() == 720 and manager.size().height() == 560
    assert page.send_button.geometry().right() <= page.width()
    assert page.input.geometry().bottom() <= page.height()
