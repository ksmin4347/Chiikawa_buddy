# ruff: noqa: F811 -- Shared pytest fixture.
from datetime import datetime, time, timedelta
from html import escape
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QInputMethodEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QAbstractButton, QApplication, QLabel, QScrollArea, QWidget
from test_focus import advance
from test_focus_ui import controller  # noqa: F401

from desktop_buddy.models.planning import CalendarEvent, Task
from desktop_buddy.ui.common import fit_window
from desktop_buddy.ui.planning_dialogs import ItemEditor
from desktop_buddy.ui.timeline import EventBlock


def settle(qapp):
    qapp.processEvents()
    QTest.qWait(25)
    qapp.processEvents()


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_small_window_pages_keep_controls_and_long_categories_accessible(controller, qapp, theme):
    buddy, clock = controller
    planning = buddy.planning
    planning.save_category("아주긴카테고리이름" * 3, "#4e8061")
    buddy.characters.select("hachiware")
    buddy.settings.update(theme=theme)
    for height in (480, 560):
        for index in range(9):
            buddy.manager.open_page(index)
            buddy.manager.resize(720, height)
            settle(qapp)
            assert buddy.manager.size().width() == 720
            assert buddy.manager.size().height() == height
            for area in buddy.manager.findChildren(QScrollArea):
                if area.isVisible():
                    assert area.horizontalScrollBar().maximum() == 0, (index, type(area))
            for widget in buddy.manager.findChildren(QAbstractButton):
                if widget.isVisible():
                    assert widget.width() + 2 >= widget.minimumSizeHint().width(), widget.text()
            for widget in buddy.manager.findChildren(QLabel):
                if widget.isVisible() and widget.wordWrap():
                    assert widget.height() + 3 >= widget.heightForWidth(widget.width()), (
                        widget.text()
                    )
    buddy.manager.open_page(buddy.manager.CHAT_PAGE)
    buddy.manager.resize(720, 480)
    settle(qapp)
    buddy.chat.submit("할 일 추가: 작은 창에서 확인 후 저장")
    settle(qapp)
    page = buddy.manager.chat_page
    area = buddy.manager.pages.currentWidget()
    assert (
        area.viewport()
        .rect()
        .contains(page.input.mapTo(area.viewport(), page.input.rect().bottomRight()))
    )
    assert (
        area.viewport()
        .rect()
        .contains(page.confirm_button.mapTo(area.viewport(), page.confirm_button.rect().center()))
    )
    page.confirm_button.click()
    assert any(
        item.title == "작은 창에서 확인 후 저장" for item in planning.repository.records("task")
    )
    settle(qapp)
    assert (
        area.viewport()
        .rect()
        .contains(page.input.mapTo(area.viewport(), page.input.rect().bottomRight()))
    )


def test_page_navigation_preserves_maximized_window(controller, qapp):
    buddy, clock = controller
    manager = buddy.manager
    manager.showMaximized()
    settle(qapp)
    manager.open_page(manager.FOCUS_PAGE)
    assert manager.isMaximized()
    manager.hide()
    manager.open_page(manager.CHAT_PAGE)
    assert manager.isMaximized()
    manager.showMinimized()
    manager.open_page(0)
    assert not manager.isMinimized()
    assert manager.isMaximized()


@pytest.mark.parametrize("kind", ["task", "event"])
def test_editor_long_category_does_not_push_save_controls_outside_window(controller, qapp, kind):
    buddy, clock = controller
    planning = buddy.planning
    planning.save_category("카테고리" * 7, "#4e8061")
    day = planning.today()
    start = datetime.combine(day, time(9), planning.zone)
    record = (
        Task("저장할 제목", day)
        if kind == "task"
        else CalendarEvent("저장할 제목", start, start + timedelta(hours=1))
    )
    editor = ItemEditor(planning, record, planning.save, buddy.manager)
    editor.show()
    editor.resize(540, 440)
    settle(qapp)
    assert editor.findChild(QScrollArea).horizontalScrollBar().maximum() == 0
    assert editor.rect().contains(
        editor.save_button.mapTo(editor, editor.save_button.rect().center())
    )
    editor.save_button.click()
    assert planning.repository.records(kind)[0].title == "저장할 제목"
    editor.deleteLater()


@pytest.mark.parametrize(
    "page_name,field",
    [("focus_page", "timer_notifications"), ("companion_page", "emotion_enabled")],
)
def test_failed_settings_save_restores_visible_checkbox(controller, monkeypatch, page_name, field):
    buddy, clock = controller
    page = getattr(buddy.manager, page_name)
    widget = page.end_notice if page_name == "focus_page" else page.checks[field]
    previous = getattr(buddy.settings.current, field)

    def fail(_settings):
        raise OSError("disk full")

    monkeypatch.setattr(buddy.store, "save_settings", fail)
    widget.setChecked(not previous)
    assert getattr(buddy.settings.current, field) == previous
    assert widget.isChecked() == previous
    assert "저장하지 못했어요" in buddy.manager.save_status.text()


def test_statistics_period_change_does_not_select_an_unrelated_record(controller):
    buddy, clock = controller
    timer = buddy.focus_timer
    timer.start(minutes=1)
    advance(timer, clock, 5)
    timer.stop()
    clock.advance(7 * 86400)
    timer.start(minutes=1)
    advance(timer, clock, 5)
    timer.stop()
    buddy.manager.open_page(buddy.manager.STATISTICS_PAGE)
    page = buddy.manager.statistics_page
    page.period.setCurrentIndex(page.period.findData("month"))
    page.calendar.setCurrentPage(2026, 10)
    assert page.records.rowCount() == 1
    page.records.selectRow(0)
    selected = page.selected_id()
    page.refresh()
    assert page.selected_id() == selected
    page.calendar.setCurrentPage(2026, 11)
    assert page.records.rowCount() == 1
    assert page.selected_id() is None


def test_dense_week_events_stay_inside_their_lanes(controller, qapp):
    buddy, clock = controller
    planning = buddy.planning
    day = planning.today()
    start = datetime.combine(day, time(9), planning.zone)
    for index in range(30):
        planning.save(CalendarEvent(f"겹치는 일정 {index}", start, start + timedelta(hours=1)))
    buddy.manager.open_page(2)
    buddy.manager.resize(720, 560)
    page = buddy.manager.calendar_page
    page.select_day(day)
    page.mode_combo.setCurrentIndex(page.mode_combo.findData("week"))
    settle(qapp)
    page.timeline.redraw()
    blocks = sorted(
        (item for item in page.timeline.scene.items() if isinstance(item, EventBlock)),
        key=lambda item: item.rect().left(),
    )
    assert len(blocks) == 30
    for first, second in zip(blocks, blocks[1:], strict=False):
        assert first.rect().right() <= second.rect().left()


def test_long_all_day_titles_and_more_entries_fit_the_week_strip(controller, qapp):
    buddy, clock = controller
    planning = buddy.planning
    day = planning.today()
    start = datetime.combine(day, time(), planning.zone)
    for index in range(5):
        planning.save(
            CalendarEvent(
                f"종일 {index} " + "긴 제목 " * 20, start, start + timedelta(days=1), all_day=True
            )
        )
    buddy.manager.open_page(2)
    buddy.manager.resize(720, 560)
    page = buddy.manager.calendar_page
    page.select_day(day)
    page.mode_combo.setCurrentIndex(page.mode_combo.findData("week"))
    settle(qapp)
    area = buddy.manager.pages.currentWidget()
    assert area.horizontalScrollBar().maximum() == 0
    strip = page.timeline.all_day_widget
    for entry in strip.findChildren(QAbstractButton):
        assert strip.rect().contains(entry.mapTo(strip, entry.rect().bottomRight()))
    more = next(
        entry
        for entry in strip.findChildren(QAbstractButton)
        if entry.objectName() == "calendarMore"
    )
    more.click()
    assert page.day == day
    assert page.details.count() == 5


def test_task_tooltip_keeps_literal_markup_and_full_title(controller):
    buddy, clock = controller
    title = '<img src="C:/private.png"> 제목'
    buddy.manager.today_page.go_today()
    buddy.planning.save(Task(title, buddy.planning.today(), description="<b>메모</b>"))
    item = buddy.manager.today_page.table.item(0, 1)
    assert item.toolTip() == escape(title + "\n<b>메모</b>")


def test_rest_period_selection_stays_on_same_id_when_earlier_period_is_added(controller):
    buddy, clock = controller
    day = buddy.planning.today()
    buddy.companion.add_rest_period(day, day + timedelta(days=1))
    page = buddy.manager.companion_page
    page.periods.selectRow(0)
    selected_id = page.rows[0]["id"]
    buddy.companion.add_rest_period(day - timedelta(days=7), day - timedelta(days=6))
    page.refresh_periods()
    assert page.rows[page.periods.currentRow()]["id"] == selected_id


def test_korean_composition_commit_does_not_submit_before_enter(controller, qapp):
    buddy, clock = controller
    buddy.manager.open_page(buddy.manager.CHAT_PAGE)
    page = buddy.manager.chat_page
    page.input.setFocus()
    composition = QInputMethodEvent("공부", [])
    QApplication.sendEvent(page.input, composition)
    assert buddy.chat.pending is None
    commit = QInputMethodEvent()
    commit.setCommitString("할 일 추가: 한글 입력 확인")
    QApplication.sendEvent(page.input, commit)
    assert page.input.text() == "할 일 추가: 한글 입력 확인"
    assert buddy.chat.pending is None
    QTest.keyClick(page.input, Qt.Key.Key_Return)
    assert buddy.chat.pending is not None
    assert not buddy.planning.repository.records("task")
    QTest.keyClick(page.confirm_button, Qt.Key.Key_Space)
    assert [record.title for record in buddy.planning.repository.records("task")] == [
        "한글 입력 확인"
    ]


def test_small_work_area_clamps_the_decorated_window_on_negative_monitor(qapp, monkeypatch):
    window = QWidget()
    window.setMinimumSize(720, 480)
    window.resize(1100, 800)
    window.move(1000, 1000)
    window.show()
    settle(qapp)
    area = QRect(-960, -200, 960, 500)
    monkeypatch.setattr(window, "screen", lambda: SimpleNamespace(availableGeometry=lambda: area))
    fit_window(window)
    assert area.contains(window.frameGeometry())
    assert window.height() < 500
    window.close()
