# ruff: noqa: F811 -- Shared pytest fixture.
from datetime import datetime, time, timedelta

import pytest
from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtGui import QAccessible, QInputMethodEvent, QKeyEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QAbstractSpinBox, QApplication, QComboBox, QScrollArea, QWidget
from test_focus import advance
from test_focus_ui import controller  # noqa: F401

from desktop_buddy.models.planning import CalendarEvent, Task
from desktop_buddy.ui import accessibility
from desktop_buddy.ui.keyboard_help import KeyboardHelp
from desktop_buddy.ui.planning_dialogs import ItemEditor


def settle(qapp):
    qapp.processEvents()
    QTest.qWait(30)
    qapp.processEvents()


@pytest.mark.parametrize("index", range(9))
def test_number_shortcuts_open_page_and_focus_its_primary_control(controller, qapp, index):
    buddy, clock = controller
    manager = buddy.manager
    manager.open_page()
    manager.activateWindow()
    settle(qapp)
    QTest.keyClick(manager, Qt.Key.Key_1 + index, Qt.KeyboardModifier.ControlModifier)
    settle(qapp)
    assert manager.pages.currentIndex() == index
    focus = qapp.focusWidget()
    assert focus is not None and focus.isVisible() and focus.isEnabled()
    page = manager.pages.currentWidget()
    assert focus is page or page.isAncestorOf(focus)


def test_chat_focus_shortcut_preserves_draft_and_timer(controller, qapp):
    buddy, clock = controller
    manager = buddy.manager
    buddy.focus_timer.start(minutes=2)
    advance(buddy.focus_timer, clock, 5)
    session_id = buddy.focus_timer.session_id
    page = manager.chat_page
    page.input.setText("아직 보내지 않은 한글 명령")
    manager.open_page(1)
    settle(qapp)
    QTest.keyClick(
        manager.today_page.quick_title, Qt.Key.Key_L, Qt.KeyboardModifier.ControlModifier
    )
    settle(qapp)
    assert manager.pages.currentIndex() == manager.CHAT_PAGE
    assert page.input.hasFocus()
    assert page.input.text() == "아직 보내지 않은 한글 명령"
    assert buddy.focus_timer.session_id == session_id and buddy.focus_timer.status == "running"
    assert not buddy.planning.repository.records("task")


def test_ctrl_enter_applies_pending_once_and_escape_only_cancels_card(controller, qapp):
    buddy, clock = controller
    buddy.manager.navigate(buddy.manager.CHAT_PAGE)
    page = buddy.manager.chat_page
    settle(qapp)
    page.input.setText("할 일 추가: 키보드 확인")
    QTest.keyClick(page.input, Qt.Key.Key_Return)
    settle(qapp)
    assert buddy.chat.pending is not None
    QTest.keyClick(page.input, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
    settle(qapp)
    assert [item.title for item in buddy.planning.repository.records("task")] == ["키보드 확인"]
    messages = len(buddy.chat.messages())
    QTest.keyClick(page.input, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
    settle(qapp)
    assert len(buddy.chat.messages()) == messages
    assert len(buddy.planning.repository.records("task")) == 1
    page.input.setText("할 일 추가: 취소할 확인")
    QTest.keyClick(page.input, Qt.Key.Key_Return)
    settle(qapp)
    page.input.setText("다음 명령 초안")
    QTest.keyClick(page.input, Qt.Key.Key_Escape)
    settle(qapp)
    assert buddy.chat.pending is None
    assert page.input.text() == "다음 명령 초안"
    assert len(buddy.planning.repository.records("task")) == 1


def test_keyboard_choice_requires_a_second_confirmation_before_save(controller, qapp):
    buddy, clock = controller
    buddy.manager.navigate(buddy.manager.CHAT_PAGE)
    page = buddy.manager.chat_page
    buddy.chat.submit("내일 오후 3시에 알고리즘 공부 추가해줘")
    settle(qapp)
    assert buddy.chat.pending.choices
    QTest.keyClick(page.input, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
    settle(qapp)
    assert buddy.chat.pending is not None
    assert not buddy.chat.pending.choices
    assert not buddy.planning.repository.records("task")
    assert not buddy.planning.repository.records("event")
    QTest.keyClick(page.input, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
    settle(qapp)
    assert len(buddy.planning.repository.records("task")) == 1


def test_held_confirmation_does_not_repeat_into_the_next_card(controller, qapp):
    buddy, clock = controller
    buddy.manager.navigate(buddy.manager.CHAT_PAGE)
    page = buddy.manager.chat_page
    buddy.chat.submit("내일 오후 3시에 알고리즘 공부 추가해줘")
    settle(qapp)
    QTest.keyPress(page.input, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
    settle(qapp)
    assert buddy.chat.pending is not None and not buddy.chat.pending.choices
    request_id = buddy.chat.pending.request_id
    repeated = QKeyEvent(
        QEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier, "", True
    )
    QApplication.sendEvent(page.input, repeated)
    settle(qapp)
    QTest.keyRelease(page.input, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
    assert buddy.chat.pending is not None and buddy.chat.pending.request_id == request_id
    assert not buddy.planning.repository.records("task")
    assert not buddy.planning.repository.records("event")


def test_expired_card_cannot_be_applied_by_keyboard(controller, qapp):
    buddy, clock = controller
    buddy.manager.navigate(buddy.manager.CHAT_PAGE)
    page = buddy.manager.chat_page
    buddy.chat.submit("할 일 추가: 만료된 키보드 확인")
    page.input.setText("남겨 둘 초안")
    clock.advance(301)
    settle(qapp)
    QTest.keyClick(page.input, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
    settle(qapp)
    assert not buddy.planning.repository.records("task")
    assert page.input.text() == "남겨 둘 초안"
    assert page.error.isVisible()


@pytest.mark.parametrize(
    "key,modifier",
    [
        (Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier),
        (Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier),
        (Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier),
    ],
)
def test_composition_keeps_existing_card_and_does_not_execute(controller, qapp, key, modifier):
    buddy, clock = controller
    buddy.manager.navigate(buddy.manager.CHAT_PAGE)
    page = buddy.manager.chat_page
    buddy.chat.submit("할 일 추가: 조합 중 보호")
    request_id = buddy.chat.pending.request_id
    page.input.setFocus()
    QApplication.sendEvent(page.input, QInputMethodEvent("한글", []))
    assert page.input.composing
    QTest.keyClick(page.input, key, modifier)
    settle(qapp)
    assert buddy.chat.pending.request_id == request_id
    assert not buddy.planning.repository.records("task")
    commit = QInputMethodEvent()
    commit.setCommitString("한글")
    QApplication.sendEvent(page.input, commit)
    assert not page.input.composing
    assert page.input.text() == "한글"


def test_leaving_the_input_clears_composition_guard(controller, qapp):
    buddy, clock = controller
    buddy.manager.navigate(buddy.manager.CHAT_PAGE)
    settle(qapp)
    page = buddy.manager.chat_page
    QApplication.sendEvent(page.input, QInputMethodEvent("조합", []))
    assert page.input.composing
    page.send_button.setFocus()
    settle(qapp)
    assert not page.input.composing


def test_shortcuts_do_not_operate_the_main_window_under_modal_editor(controller, qapp):
    buddy, clock = controller
    manager = buddy.manager
    manager.navigate(manager.CHAT_PAGE)
    buddy.chat.submit("할 일 추가: 편집창 뒤의 확인")
    pending = buddy.chat.pending.request_id
    editor = ItemEditor(
        buddy.planning, Task("", buddy.planning.today()), buddy.planning.save, manager
    )

    def exercise():
        QTest.keyClick(editor.title_edit, Qt.Key.Key_1, Qt.KeyboardModifier.ControlModifier)
        QTest.keyClick(editor.title_edit, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
        editor.reject()

    QTimer.singleShot(40, exercise)
    editor.exec()
    assert manager.pages.currentIndex() == manager.CHAT_PAGE
    assert buddy.chat.pending.request_id == pending
    assert not buddy.planning.repository.records("task")
    editor.deleteLater()


def test_f1_opens_real_help_and_escape_restores_draft_focus(controller, qapp):
    buddy, clock = controller
    manager = buddy.manager
    manager.navigate(manager.CHAT_PAGE)
    settle(qapp)
    page = manager.chat_page
    page.input.setText("도움말을 열기 전 초안")
    observed = []

    def inspect_dialog():
        dialog = qapp.activeModalWidget()
        observed.append(isinstance(dialog, KeyboardHelp))
        observed.append(dialog.table.rowCount() == 16)
        QTest.keyClick(dialog, Qt.Key.Key_Escape)

    QTimer.singleShot(50, inspect_dialog)
    QTest.keyClick(page.input, Qt.Key.Key_F1)
    settle(qapp)
    assert observed == [True, True]
    assert qapp.activeModalWidget() is None
    assert page.input.hasFocus() and page.input.text() == "도움말을 열기 전 초안"


def test_focus_page_shortcut_selects_pause_or_resume_for_running_session(controller, qapp):
    buddy, clock = controller
    buddy.focus_timer.start(minutes=2)
    buddy.manager.navigate(0)
    settle(qapp)
    QTest.keyClick(buddy.manager.greet_button, Qt.Key.Key_4, Qt.KeyboardModifier.ControlModifier)
    settle(qapp)
    assert buddy.manager.focus_page.pause_button.hasFocus()
    buddy.focus_timer.pause()
    buddy.manager.navigate(0)
    settle(qapp)
    QTest.keyClick(buddy.manager.greet_button, Qt.Key.Key_4, Qt.KeyboardModifier.ControlModifier)
    settle(qapp)
    assert buddy.manager.focus_page.resume_button.hasFocus()


def test_page_and_editor_input_names_exist_in_the_accessible_interface(controller, qapp):
    buddy, clock = controller
    manager = buddy.manager
    for index in range(9):
        manager.open_page(index)
        settle(qapp)
        for widget in manager.pages.currentWidget().findChildren(QWidget):
            if widget.isVisible() and isinstance(widget, (QComboBox, QAbstractSpinBox)):
                interface = QAccessible.queryAccessibleInterface(widget)
                assert interface.text(QAccessible.Text.Name).strip(), (index, widget)
    day = buddy.planning.today()
    start = datetime.combine(day, time(9), buddy.planning.zone)
    for record in (Task("한글", day), CalendarEvent("일정", start, start + timedelta(hours=1))):
        editor = ItemEditor(buddy.planning, record, buddy.planning.save, manager)
        editor.show()
        settle(qapp)
        for widget in editor.findChildren(QWidget):
            if isinstance(widget, (QComboBox, QAbstractSpinBox)):
                interface = QAccessible.queryAccessibleInterface(widget)
                assert interface.text(QAccessible.Text.Name).strip(), widget
        editor.close()
        editor.deleteLater()


def test_accessibility_announcements_are_visible_only_and_timer_status_not_every_tick(
    controller, qapp, monkeypatch
):
    buddy, clock = controller
    events = []
    monkeypatch.setattr(accessibility.QAccessible, "isActive", lambda: True)
    monkeypatch.setattr(accessibility.QAccessible, "updateAccessibility", events.append)
    buddy.manager.navigate(buddy.manager.CHAT_PAGE)
    buddy.chat.submit("할 일 추가: 화면 읽기 확인")
    settle(qapp)
    assert any("확인할 내용" in event.message() for event in events)
    buddy.manager.navigate(buddy.manager.FOCUS_PAGE)
    events.clear()
    buddy.focus_timer.start(minutes=2)
    advance(buddy.focus_timer, clock, 5)
    assert len(events) == 1 and "진행 중" in events[0].message()
    buddy.focus_timer.pause()
    assert len(events) == 2 and "일시정지" in events[1].message()
    buddy.manager.hide()
    events.clear()
    buddy.focus_timer.resume()
    assert events == []


def test_tab_and_shift_tab_reach_confirm_and_input_in_small_window(controller, qapp):
    buddy, clock = controller
    manager = buddy.manager
    manager.resize(720, 480)
    manager.navigate(manager.CHAT_PAGE)
    buddy.chat.submit("할 일 추가: 작은 창 키보드")
    settle(qapp)
    page = manager.chat_page
    page.confirm_button.setFocus()
    QTest.keyClick(page.confirm_button, Qt.Key.Key_Tab)
    QTest.keyClick(qapp.focusWidget(), Qt.Key.Key_Tab)
    settle(qapp)
    assert page.input.hasFocus()
    area = manager.pages.currentWidget()
    assert isinstance(area, QScrollArea)
    assert (
        area.viewport()
        .rect()
        .contains(page.input.mapTo(area.viewport(), page.input.rect().bottomRight()))
    )
    QTest.keyClick(page.input, Qt.Key.Key_Backtab, Qt.KeyboardModifier.ShiftModifier)
    QTest.keyClick(qapp.focusWidget(), Qt.Key.Key_Backtab, Qt.KeyboardModifier.ShiftModifier)
    settle(qapp)
    assert page.confirm_button.hasFocus()
