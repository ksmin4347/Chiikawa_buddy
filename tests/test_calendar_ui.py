from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import QDialog, QMainWindow

from desktop_buddy.calendar.layout import arrange_intervals
from desktop_buddy.database.store import Store
from desktop_buddy.models.planning import CalendarEvent, Task
from desktop_buddy.services.planning_service import PlanningService
from desktop_buddy.services.settings_service import SettingsService
from desktop_buddy.ui.calendar_page import CalendarPage
from desktop_buddy.ui.planning_actions import PlanningActions
from desktop_buddy.ui.planning_dialogs import ItemEditor
from desktop_buddy.ui.timeline import EventBlock
from desktop_buddy.ui.today_page import TodayPage

DAY = date(2026, 10, 28)
ZONE = ZoneInfo("Asia/Seoul")


@pytest.fixture
def context(qapp, tmp_path):
    store = Store(tmp_path / "buddy.db")
    planning = PlanningService(store)
    settings = SettingsService(store)
    owner = QMainWindow()
    actions = PlanningActions(planning, owner)
    yield planning, settings, actions, owner
    owner.hide()
    owner.deleteLater()
    qapp.processEvents()
    store.close()


def test_quick_add_and_checkbox_keep_calendar_in_sync(qapp, context):
    planning, settings, actions, owner = context
    today = TodayPage(planning, actions)
    calendar = CalendarPage(planning, settings, actions)
    owner.setCentralWidget(today)
    today.date_edit.setDate(QDate(2026, 10, 28))
    calendar.select_day(DAY)
    today.quick_title.setText("자료구조 복습")
    today.quick_add()
    assert today.table.rowCount() == 1
    assert calendar.details.count() == 1
    assert "자료구조 복습" in calendar.details.item(0).text()
    today.table.item(0, 0).setCheckState(Qt.CheckState.Checked)
    qapp.processEvents()
    assert planning.occurrences(DAY, DAY + timedelta(days=1), "task")[0].completed
    assert "완료" in calendar.details.item(0).text()
    today.filter_combo.setCurrentIndex(today.filter_combo.findData("incomplete"))
    assert today.table.rowCount() == 0
    calendar.deleteLater()
    qapp.processEvents()


def test_previous_incomplete_remains_visible(context):
    planning, settings, actions, owner = context
    planning.save(Task("어제 미완료", DAY - timedelta(days=1)))
    page = TodayPage(planning, actions)
    owner.setCentralWidget(page)
    page.date_edit.setDate(QDate(2026, 10, 28))
    page.filter_combo.setCurrentIndex(page.filter_combo.findData("overdue"))
    assert page.table.rowCount() == 1
    assert "어제 미완료" in page.table.item(0, 1).text()


def test_real_month_grid_navigation_and_week_start(context):
    planning, settings, actions, owner = context
    page = CalendarPage(planning, settings, actions)
    owner.setCentralWidget(page)
    page.select_day(DAY)
    assert page.month_table.columnCount() == 7
    assert page.month_table.rowCount() == 6
    assert page.month_table.horizontalHeaderItem(0).text() == "일"
    settings.update(week_start=0)
    assert page.month_table.horizontalHeaderItem(0).text() == "월"
    page.navigate(1)
    assert page.day == date(2026, 11, 28)
    page.navigate(-1)
    assert page.day == DAY
    assert not page.edit_button.isEnabled()


def test_week_day_timeline_draws_overlapping_events(context, qapp):
    planning, settings, actions, owner = context
    start = datetime(2026, 10, 28, 14, tzinfo=ZONE)
    planning.save(CalendarEvent("첫 일정", start, start + timedelta(hours=2)))
    planning.save(
        CalendarEvent("겹치는 일정", start + timedelta(minutes=30), start + timedelta(hours=1))
    )
    page = CalendarPage(planning, settings, actions)
    owner.setCentralWidget(page)
    page.select_day(DAY)
    page.mode_combo.setCurrentIndex(page.mode_combo.findData("week"))
    assert len(page.timeline.days) == 7
    blocks = [item for item in page.timeline.scene.items() if isinstance(item, EventBlock)]
    assert len(blocks) == 2
    assert blocks[0].rect().x() != blocks[1].rect().x()
    page.mode_combo.setCurrentIndex(page.mode_combo.findData("day"))
    assert page.timeline.days == [DAY]
    assert len([item for item in page.timeline.scene.items() if isinstance(item, EventBlock)]) == 2


def test_editor_validates_without_losing_text_then_saves(context):
    planning, settings, actions, owner = context
    editor = ItemEditor(planning, Task("", DAY), planning.save, owner)
    editor._submit()
    assert editor.error_label.text()
    assert not planning.repository.records("task")
    editor.title_edit.setText("새 할 일")
    editor._submit()
    assert editor.result() == QDialog.DialogCode.Accepted
    assert planning.repository.records("task")[0].title == "새 할 일"
    editor.deleteLater()


def test_all_day_editor_uses_inclusive_ui_end_exclusive_storage(context):
    planning, settings, actions, owner = context
    start = datetime(2026, 10, 28, 14, tzinfo=ZONE)
    editor = ItemEditor(
        planning, CalendarEvent("", start, start + timedelta(hours=1)), planning.save, owner
    )
    editor.title_edit.setText("종일 일정")
    editor.all_day.setChecked(True)
    editor._submit()
    record = planning.repository.records("event")[0]
    assert record.start.hour == 0
    assert record.end.date() == DAY + timedelta(days=1)
    assert not planning.occurrences(DAY + timedelta(days=1), DAY + timedelta(days=2))
    editor.deleteLater()


def test_delete_cancel_preserves_data(context, monkeypatch):
    import desktop_buddy.ui.planning_actions as module

    planning, settings, actions, owner = context
    planning.save(Task("남겨야 할 일", DAY))
    occurrence = planning.occurrences(DAY, DAY + timedelta(days=1))[0]
    monkeypatch.setattr(module, "confirm_delete", lambda *_args: False)
    actions.delete(occurrence)
    assert len(planning.repository.records("task")) == 1


def test_editor_storage_failure_preserves_input(context, monkeypatch):
    planning, settings, actions, owner = context

    def fail(_record):
        raise OSError("disk full")

    editor = ItemEditor(planning, Task("입력한 내용", DAY), fail, owner)
    editor._submit()
    assert editor.title_edit.text() == "입력한 내용"
    assert "저장하지 못했어요" in editor.error_label.text()
    assert editor.result() != QDialog.DialogCode.Accepted
    editor.deleteLater()


def test_overlap_partition_handles_touching_and_connected_groups():
    positions = arrange_intervals([(60, 120), (90, 150), (120, 180), (200, 240), (240, 280)])
    by_index = {value.index: value for value in positions}
    assert by_index[0].lanes == 2
    assert by_index[0].lane == by_index[2].lane
    assert by_index[3].lanes == by_index[4].lanes == 1
    for first in positions:
        for second in positions:
            if (
                first.index != second.index
                and first.start < second.end
                and second.start < first.end
            ):
                assert first.lane != second.lane


def test_short_adjacent_events_do_not_paint_over_each_other(context):
    planning, settings, actions, owner = context
    start = datetime(2026, 10, 28, 14, tzinfo=ZONE)
    planning.save(CalendarEvent("짧은 일정 1", start, start + timedelta(minutes=15)))
    planning.save(
        CalendarEvent("짧은 일정 2", start + timedelta(minutes=15), start + timedelta(minutes=30))
    )
    page = CalendarPage(planning, settings, actions)
    owner.setCentralWidget(page)
    page.select_day(DAY)
    page.mode_combo.setCurrentIndex(page.mode_combo.findData("day"))
    blocks = sorted(
        [item for item in page.timeline.scene.items() if isinstance(item, EventBlock)],
        key=lambda item: item.rect().top(),
    )
    assert blocks[0].rect().bottom() <= blocks[1].rect().top()
    assert blocks[0].rect().x() == blocks[1].rect().x()
