from PySide6.QtTest import QTest

from desktop_buddy.app import BuddyApplication
from desktop_buddy.database.store import Store
from desktop_buddy.services.single_instance import SingleInstance


def test_controller_management_reuse_and_restart(qapp, tmp_path):
    guard = SingleInstance(tmp_path)
    assert guard.acquire()
    store = Store(tmp_path / "buddy.db")
    controller = BuddyApplication(qapp, store, guard, tmp_path)
    try:
        area = qapp.primaryScreen().availableGeometry()
        assert controller.pet.x() >= area.x()
        assert controller.pet.y() > area.height() // 2
        manager = controller.manager
        manager.open_page()
        manager.open_page()
        assert manager is controller.manager
        manager.close()
        assert not manager.isVisible()
        assert controller.pet.isVisible()
        manager.name_edit.setText("토리")
        manager.name_edit.editingFinished.emit()
        manager.size_spin.setValue(208)
        manager.theme_combo.setCurrentIndex(manager.theme_combo.findData("dark"))
        assert controller.pet.width() == 208
        assert "토리" in manager.greeting.text()
        controller.pet.move(200, 240)
        controller.pet.position_changed.emit(200, 240)
    finally:
        controller.shutdown()
    reopened = Store(tmp_path / "buddy.db")
    assert reopened.load_settings().character_name == "토리"
    assert reopened.load_settings().x == 200
    reopened.close()


def test_single_instance_activation(qapp, tmp_path):
    from PySide6.QtTest import QSignalSpy

    first = SingleInstance(tmp_path)
    assert first.acquire()
    activated = QSignalSpy(first.activation_requested)
    try:
        import sys
        from pathlib import Path

        from PySide6.QtCore import QProcess

        code = (
            "import sys; from pathlib import Path; "
            f"sys.path.insert(0, {str(Path(__file__).resolve().parents[1] / 'src')!r}); "
            "from PySide6.QtCore import QCoreApplication; "
            "from desktop_buddy.services.single_instance import SingleInstance; "
            "app=QCoreApplication([]); guard=SingleInstance(Path(sys.argv[1])); "
            "sys.exit(1 if guard.acquire() else 0)"
        )
        process = QProcess()
        process.start(sys.executable, ["-c", code, str(tmp_path)])
        assert process.waitForStarted(3000)
        for _ in range(100):
            QTest.qWait(50)
            if process.state() == QProcess.ProcessState.NotRunning:
                break
        assert process.state() == QProcess.ProcessState.NotRunning
        assert process.exitCode() == 0
        assert activated.count() == 1
    finally:
        first.close()
    third = SingleInstance(tmp_path)
    assert third.acquire()
    third.close()


def test_lock_permission_error_is_reported(qapp, tmp_path):
    from types import SimpleNamespace

    import pytest
    from PySide6.QtCore import QLockFile

    guard = SingleInstance(tmp_path)
    guard.lock = SimpleNamespace(
        tryLock=lambda _timeout: False,
        error=lambda: QLockFile.LockError.PermissionError,
    )
    with pytest.raises(RuntimeError, match="권한"):
        guard.acquire()


def test_quit_from_visible_management_window_ends_child_process(qapp, tmp_path):
    import sys
    from pathlib import Path

    from PySide6.QtCore import QProcess

    source = Path(__file__).resolve().parents[1] / "src"
    code = f"""
import sys
from pathlib import Path
sys.path.insert(0, {str(source)!r})
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from desktop_buddy.app import BuddyApplication
from desktop_buddy.database.store import Store
from desktop_buddy.services.single_instance import SingleInstance
app = QApplication([])
app.setQuitOnLastWindowClosed(False)
path = Path(sys.argv[1])
guard = SingleInstance(path)
assert guard.acquire()
store = Store(path/'buddy.db')
controller = BuddyApplication(app, store, guard, path)
controller.manager.open_page(controller.manager.SETTINGS_PAGE)
QTimer.singleShot(100, controller.manager.quit_requested.emit)
QTimer.singleShot(3000, lambda: app.exit(7))
status = app.exec()
assert controller._closed
assert not controller.notifications.timer.isActive()
sys.exit(status)
"""
    process = QProcess()
    process.start(sys.executable, ["-c", code, str(tmp_path)])
    assert process.waitForStarted(3000)
    finished = process.waitForFinished(6000)
    if not finished:
        process.kill()
        process.waitForFinished(3000)
    assert finished
    assert process.exitCode() == 0, bytes(process.readAllStandardError()).decode(errors="replace")
