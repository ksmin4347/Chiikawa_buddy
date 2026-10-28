"""Native Qt lifecycle smoke test using only a dedicated QA database."""

# ruff: noqa: E402 -- Set source path before project imports.
import json
import sys
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from PySide6.QtCore import QCoreApplication, QEvent, Qt, QTimer
from PySide6.QtWidgets import QApplication

from desktop_buddy.app import BuddyApplication
from desktop_buddy.database.store import Store
from desktop_buddy.services.single_instance import SingleInstance

app = QApplication([])
app.setQuitOnLastWindowClosed(False)
app.setStyle("Fusion")
directory = ROOT / ".qa" / "native-smoke-phase2"
directory.mkdir(parents=True, exist_ok=True)
guard = SingleInstance(directory)
assert guard.acquire()
store = Store(directory / "buddy.db")
controller = BuddyApplication(app, store, guard, directory)
result = {"platform": app.platformName(), "screens": len(app.screens())}


def verify():
    try:
        result["first_screen_is_only_pet"] = (
            controller.pet.isVisible() and not controller.manager.isVisible()
        )
        result["native_tray_visible"] = controller.tray.isVisible()
        assert result["first_screen_is_only_pet"]
        controller.manager.open_page()
        app.processEvents()
        assert controller.manager.isVisible()
        assert controller.manager.grab().save(str(ROOT / ".qa" / "native-home.png"))
        controller.manager.close()
        result["closing_manager_keeps_pet"] = (
            controller.pet.isVisible() and not controller.manager.isVisible()
        )
        assert result["closing_manager_keeps_pet"]
        controller.settings.update(character_name="테스트 친구", size=208)
        result["live_size_update"] = controller.pet.width() == 208
        assert result["live_size_update"]
        controller.hide_pet()
        result["hidden_animation_stopped"] = not controller.pet.animation_timer.isActive()
        assert result["hidden_animation_stopped"]
        controller.find_pet()
        result["restored_animation_running"] = controller.pet.animation_timer.isActive()
        assert result["restored_animation_running"]
        page = controller.manager.today_page
        controller.manager.open_page(1)
        page.go_today()
        page.quick_title.setText("네이티브 실행 검증")
        page.quick_add()
        items = controller.planning.occurrences(page.day, page.day + timedelta(days=1), "task")
        result["task_created_from_ui"] = any(item.title == "네이티브 실행 검증" for item in items)
        assert result["task_created_from_ui"]
        page.table.item(page.table.rowCount() - 1, 0).setCheckState(Qt.CheckState.Checked)
        app.processEvents()
        result["task_completed_from_ui"] = any(
            item.completed
            for item in controller.planning.occurrences(
                page.day, page.day + timedelta(days=1), "task"
            )
        )
        assert result["task_completed_from_ui"]
        controller.manager.open_page(2)
        calendar = controller.manager.calendar_page
        calendar.go_today()
        app.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        assert controller.manager.grab().save(str(ROOT / ".qa" / "native-calendar.png"))
        calendar.mode_combo.setCurrentIndex(calendar.mode_combo.findData("week"))
        result["weekly_view"] = len(calendar.timeline.days) == 7
        calendar.mode_combo.setCurrentIndex(calendar.mode_combo.findData("day"))
        result["daily_view"] = len(calendar.timeline.days) == 1
        assert result["weekly_view"] and result["daily_view"]
        QTimer.singleShot(300, controller.quit)
    except Exception as error:
        result["error"] = repr(error)
        app.exit(1)


QTimer.singleShot(500, verify)
QTimer.singleShot(10000, lambda: app.exit(2))
code = app.exec()
reopened = Store(directory / "buddy.db")
result["persisted_after_exit"] = reopened.load_settings().character_name == "테스트 친구"
reopened.close()
next_guard = SingleInstance(directory)
result["lock_released_after_exit"] = next_guard.acquire()
result["notification_timer_stopped"] = not controller.notifications.timer.isActive()
next_guard.close()
(ROOT / ".qa" / "native-smoke-phase2.json").write_text(
    json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
)
print(json.dumps(result, ensure_ascii=False))
raise SystemExit(code)
