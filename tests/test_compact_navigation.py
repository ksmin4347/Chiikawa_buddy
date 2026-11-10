# ruff: noqa: F811 -- Shared pytest fixture.
import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QScrollArea
from test_focus import advance
from test_focus_ui import controller  # noqa: F401


def settle(qapp):
    qapp.processEvents()
    QTest.qWait(25)
    qapp.processEvents()


@pytest.mark.parametrize("theme", ["light", "dark"])
@pytest.mark.parametrize("size", [(560, 360), (640, 480)])
def test_narrow_pages_use_full_width_without_horizontal_page_scroll(controller, qapp, theme, size):
    buddy, clock = controller
    manager = buddy.manager
    buddy.planning.save_category("긴카테고리이름" * 4, "#4e8061")
    buddy.characters.select("chiikawa")
    buddy.settings.update(theme=theme)
    manager.resize(*size)
    for index in range(9):
        manager.open_page(index)
        settle(qapp)
        assert manager.compact_bar.isVisible() and not manager.sidebar.isVisible()
        assert manager.compact_menu.currentIndex() == index
        for area in manager.findChildren(QScrollArea):
            if area.isVisible():
                assert area.horizontalScrollBar().maximum() == 0, (index, type(area))
    assert manager.size().width() == size[0] and manager.size().height() == size[1]


def test_compact_menu_and_shortcuts_keep_draft_and_active_timer(controller, qapp):
    buddy, clock = controller
    manager = buddy.manager
    manager.resize(640, 480)
    manager.open_page(0)
    buddy.focus_timer.start(minutes=2)
    advance(buddy.focus_timer, clock, 5)
    session_id = buddy.focus_timer.session_id
    manager.chat_page.input.setText("아직 보내지 않은 초안")
    for index in range(9):
        manager.compact_menu.setCurrentIndex(index)
        manager.compact_menu.activated.emit(index)
        settle(qapp)
        assert manager.pages.currentIndex() == index
        assert manager.nav_group.button(index).isChecked()
    QTest.keyClick(manager.name_edit, Qt.Key.Key_L, Qt.KeyboardModifier.ControlModifier)
    settle(qapp)
    assert manager.compact_menu.currentIndex() == manager.CHAT_PAGE
    assert manager.chat_page.input.hasFocus()
    assert manager.chat_page.input.text() == "아직 보내지 않은 초안"
    assert buddy.focus_timer.session_id == session_id and buddy.focus_timer.status == "running"


def test_navigation_focus_moves_out_of_the_bar_that_disappears(controller, qapp):
    buddy, clock = controller
    manager = buddy.manager
    manager.open_page(0)
    manager.resize(960, 760)
    settle(qapp)
    assert manager.sidebar.isVisible()
    manager.nav_group.button(0).setFocus()
    manager.resize(640, 480)
    settle(qapp)
    assert manager.compact_menu.hasFocus()
    manager.resize(960, 760)
    settle(qapp)
    assert not manager.compact_bar.isVisible() and manager.sidebar.isVisible()
    assert QApplication.focusWidget() is manager.nav_group.button(0)


def test_resize_keeps_an_existing_confirmation_without_applying_it(controller, qapp):
    buddy, clock = controller
    manager = buddy.manager
    manager.navigate(manager.CHAT_PAGE)
    buddy.chat.submit("할 일 추가: 크기 변경 중 확인")
    request_id = buddy.chat.pending.request_id
    for size in ((560, 360), (960, 760), (640, 480)):
        manager.resize(*size)
        settle(qapp)
        assert buddy.chat.pending.request_id == request_id
        assert not buddy.planning.repository.records("task")
    QTest.keyClick(manager.chat_page.input, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
    settle(qapp)
    assert len(buddy.planning.repository.records("task")) == 1
