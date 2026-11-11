import threading
import time
from dataclasses import replace
from datetime import timedelta

import pytest
from PySide6.QtCore import QDate, Qt, QTimer
from PySide6.QtWidgets import QFileDialog, QMainWindow
from test_calendar_transfer import DAY, END, event, ics

from desktop_buddy.database.store import Store
from desktop_buddy.models.planning import Task
from desktop_buddy.services.planning_service import PlanningService
from desktop_buddy.ui.calendar_transfer import CalendarTransferDialog


def settle(qapp, predicate, seconds=5):
    until = time.monotonic() + seconds
    while not predicate() and time.monotonic() < until:
        qapp.processEvents()
        time.sleep(0.005)
    qapp.processEvents()
    assert predicate()


@pytest.fixture
def dialog(qapp, tmp_path):
    store = Store(tmp_path / "buddy.db")
    planning = PlanningService(store)
    owner = QMainWindow()
    view = CalendarTransferDialog(planning, owner)
    view.start.setDate(QDate(DAY))
    view.end.setDate(QDate(END - timedelta(days=1)))
    view.show()
    qapp.processEvents()
    yield view
    job = view._job
    view.reject()
    if job is not None:
        job.thread.join(timeout=2)
    qapp.processEvents()
    owner.close()
    store.close()


def load(view, qapp, tmp_path, data=None):
    path = tmp_path / "import.ics"
    path.write_bytes(data or ics(event()))
    view.file_path = path
    view.path_display.setText(str(path))
    view._load()
    settle(qapp, lambda: view._job is None)


def test_import_preview_no_storage_until_confirmation_and_cancel_is_safe(
    dialog, qapp, tmp_path, monkeypatch
):
    view = dialog
    load(view, qapp, tmp_path)
    assert view.import_table.rowCount() == 1 and view.import_apply_button.isEnabled()
    assert not view.transfer.planning.repository.records("event")
    assert "회의" in view.import_detail.toPlainText()
    monkeypatch.setattr(view, "_confirm", lambda *args: False)
    view.import_apply_button.click()
    assert not view.transfer.planning.repository.records("event")
    monkeypatch.setattr(view, "_confirm", lambda *args: True)
    view.import_apply_button.click()
    assert len(view.transfer.planning.repository.records("event")) == 1
    assert not view.import_apply_button.isEnabled()


def test_update_and_overlap_default_to_unchecked_and_show_current_file_details(
    dialog, qapp, tmp_path, monkeypatch
):
    view = dialog
    load(view, qapp, tmp_path)
    monkeypatch.setattr(view, "_confirm", lambda *args: True)
    view._apply()
    load(
        view, qapp, tmp_path, ics(event(title="원본 변경"), event(uid="another", title="시간 겹침"))
    )
    assert view.import_table.rowCount() == 2 and not view.import_apply_button.isEnabled()
    assert "현재 앱 내용" in view.import_detail.toPlainText()
    assert all(
        view.import_table.item(i, 0).checkState() == Qt.CheckState.Unchecked for i in range(2)
    )
    view.import_table.item(0, 0).setCheckState(Qt.CheckState.Checked)
    view._apply()
    assert view.transfer.planning.repository.records("event")[0].title == "원본 변경"
    assert len(view.transfer.planning.repository.records("event")) == 1


@pytest.mark.parametrize("change", ["source", "start", "end"])
def test_changing_conditions_invalidates_all_previews(dialog, qapp, tmp_path, change):
    load(dialog, qapp, tmp_path)
    assert dialog.import_plan is not None
    if change == "source":
        dialog.source.setText("다른 출처")
    else:
        getattr(dialog, change).setDate(QDate(DAY))
    # start initially equals DAY, so change it to another day explicitly.
    if change == "start":
        dialog.start.setDate(QDate(DAY.year, DAY.month, DAY.day + 1))
    assert dialog.import_plan is None and not dialog.import_apply_button.isEnabled()


def test_gui_remains_responsive_and_late_result_is_ignored_after_cancel(dialog, qapp):
    entered, release = threading.Event(), threading.Event()
    beats = []
    timer = QTimer()
    timer.timeout.connect(lambda: beats.append(True))
    timer.start(5)

    def slow(stop):
        entered.set()
        release.wait(timeout=2)
        raise RuntimeError("do not expose raw path or content")

    dialog._dispatch("import", slow)
    settle(qapp, entered.is_set)
    settle(qapp, lambda: len(beats) > 2)
    assert not dialog.choose_button.isEnabled() and dialog.cancel_job_button.isEnabled()
    dialog._cancel_job()
    release.set()
    settle(qapp, lambda: dialog._job is None)
    timer.stop()
    assert dialog.import_plan is None and "raw path" not in dialog.status.text()


def test_changed_source_during_job_cannot_accept_old_result(dialog, qapp):
    from desktop_buddy.calendar.ics_codec import parse_calendar

    release = threading.Event()
    result = parse_calendar(ics(event()), DAY, END)

    def slow(stop):
        release.wait(timeout=2)
        return result

    dialog._dispatch("import", slow)
    dialog.source.setText("바뀐 출처")
    release.set()
    settle(qapp, lambda: dialog._job is None)
    assert dialog.import_plan is None and not dialog.import_apply_button.isEnabled()


def test_export_preview_and_selected_file_write_are_offline_and_readonly(
    dialog, qapp, tmp_path, monkeypatch
):
    from desktop_buddy.calendar.ics_codec import parse_calendar

    dialog.transfer.planning.save(Task("할 일", DAY, completed=True))
    dialog.export_kind.setCurrentIndex(2)
    before = dialog.transfer.fingerprint()
    dialog._preview_export()
    assert dialog.export_table.rowCount() == 1 and dialog.export_save_button.isEnabled()
    assert dialog.transfer.fingerprint() == before
    target = tmp_path / "output.ics"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args: (str(target), ""))
    monkeypatch.setattr(dialog, "_confirm", lambda *args: True)
    dialog._save()
    settle(qapp, lambda: dialog._job is None)
    assert len(parse_calendar(target.read_bytes(), DAY, END).entries) == 1
    assert dialog.transfer.fingerprint() == before


def test_export_cancel_and_stale_data_leave_target_unchanged(dialog, qapp, tmp_path, monkeypatch):
    dialog.transfer.planning.save(Task("원본", DAY))
    dialog.export_kind.setCurrentIndex(1)
    dialog._preview_export()
    path = tmp_path / "kept.ics"
    path.write_bytes(b"keep this original")
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args: (str(path), ""))
    monkeypatch.setattr(dialog, "_confirm", lambda *args: False)
    dialog._save()
    assert path.read_bytes() == b"keep this original"
    record = dialog.transfer.planning.repository.records("task")[0]
    dialog.transfer.planning.save(replace(record, title="다른 창 변경"))
    monkeypatch.setattr(dialog, "_confirm", lambda *args: True)
    dialog._save()
    assert dialog._job is None and path.read_bytes() == b"keep this original"


def test_bad_file_is_sanitized_and_never_written(dialog, qapp, tmp_path):
    load(dialog, qapp, tmp_path, b"bad file with sensitive path")
    assert dialog.import_plan is None and "sensitive path" not in dialog.status.text()
    assert not dialog.import_apply_button.isEnabled()


def test_window_close_cancels_worker_without_waiting_or_saving(dialog, qapp):
    release = threading.Event()

    def slow(stop):
        release.wait(timeout=2)
        return None

    dialog._dispatch("import", slow)
    job = dialog._job
    before = time.monotonic()
    dialog.reject()
    assert time.monotonic() - before < 0.5 and job.cancelled.is_set()
    release.set()
    job.thread.join(timeout=2)
    qapp.processEvents()
    assert dialog.transfer.import_plan is None
