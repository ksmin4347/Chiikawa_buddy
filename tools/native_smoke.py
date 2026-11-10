"""Native Qt lifecycle smoke test using only a dedicated QA database."""

# ruff: noqa: E402 -- Set source path before project imports.
import json
import sys
import time
import uuid
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from desktop_buddy.app import BuddyApplication
from desktop_buddy.database.store import Store
from desktop_buddy.services.completion_audio import WavePlayer
from desktop_buddy.services.single_instance import SingleInstance

app = QApplication([])
app.setQuitOnLastWindowClosed(False)
app.setStyle("Fusion")
directory = ROOT / ".qa" / "native-smoke-characters" / uuid.uuid4().hex
directory.mkdir(parents=True, exist_ok=True)
guard = SingleInstance(directory)
assert guard.acquire()
store = Store(directory / "buddy.db")
controller = BuddyApplication(app, store, guard, directory, show_onboarding=False)
result = {"platform": app.platformName(), "screens": len(app.screens())}


class SilentSound:
    SND_FILENAME, SND_ASYNC, SND_NODEFAULT = 0x20000, 1, 2

    def __init__(self):
        self.calls = []

    def PlaySound(self, sound, flags):
        self.calls.append((sound, flags))


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
        controller.manager.open_page(controller.manager.FOCUS_PAGE)
        focus = controller.manager.focus_page
        focus.kind.setCurrentIndex(0)
        focus.start_button.click()
        result["focus_started_from_ui"] = controller.focus_timer.status == "running"
        result["focus_animation"] = controller.animation.base_state == "focus"
        result["mini_timer_visible"] = controller.mini_timer.isVisible()
        focus.pause_button.click()
        result["focus_paused_from_ui"] = controller.focus_timer.status == "paused"
        focus.resume_button.click()
        result["focus_resumed_from_ui"] = controller.focus_timer.status == "running"
        focus.stop_button.click()
        result["focus_stopped_from_ui"] = controller.focus_timer.status == "idle"
        controller.manager.open_page(controller.manager.STATISTICS_PAGE)
        app.processEvents()
        result["focus_history_visible"] = controller.manager.statistics_page.records.rowCount() > 0
        assert all(
            result[key]
            for key in (
                "focus_started_from_ui",
                "focus_animation",
                "mini_timer_visible",
                "focus_paused_from_ui",
                "focus_resumed_from_ui",
                "focus_stopped_from_ui",
                "focus_history_visible",
            )
        )
        assert controller.manager.grab().save(str(ROOT / ".qa" / "native-statistics.png"))
        controller.manager.open_page(controller.manager.COMPANION_PAGE)
        result["companion_page_visible"] = controller.manager.companion_page.isVisible()
        controller.show_today_briefing()
        result["manual_briefing_visible"] = controller.briefing_card.isVisible()
        controller.briefing_card.open_planning()
        result["briefing_opens_today"] = controller.manager.pages.currentIndex() == 1
        controller.settings.update(focus_appearance="small")
        controller.manager.open_page(controller.manager.FOCUS_PAGE)
        focus.start_button.click()
        result["focus_size_is_temporary"] = (
            controller.pet.width() == 128 and controller.settings.current.size == 208
        )
        focus.stop_button.click()
        result["size_restored_after_focus"] = controller.pet.width() == 208
        assert all(
            result[key]
            for key in (
                "companion_page_visible",
                "manual_briefing_visible",
                "briefing_opens_today",
                "focus_size_is_temporary",
                "size_restored_after_focus",
            )
        )
        controller.manager.open_page(controller.manager.CHAT_PAGE)
        chat = controller.manager.chat_page
        chat.input.setText("할 일 추가: 채팅 네이티브 검증")
        chat.send_button.click()
        result["chat_preview_before_save"] = controller.chat.pending is not None and not any(
            item.title == "채팅 네이티브 검증"
            for item in controller.planning.repository.records("task")
        )
        chat.confirm_button.click()
        result["chat_confirm_saved"] = any(
            item.title == "채팅 네이티브 검증"
            for item in controller.planning.repository.records("task")
        )
        chat.input.setText("1분 집중 시작")
        chat.send_button.click()
        result["chat_timer_started"] = controller.focus_timer.status == "running"
        chat.input.setText("타이머 일시정지")
        chat.send_button.click()
        result["chat_timer_paused"] = controller.focus_timer.status == "paused"
        chat.input.setText("타이머 재개")
        chat.send_button.click()
        result["chat_timer_resumed"] = controller.focus_timer.status == "running"
        assert all(
            result[key]
            for key in (
                "chat_preview_before_save",
                "chat_confirm_saved",
                "chat_timer_started",
                "chat_timer_paused",
                "chat_timer_resumed",
            )
        )
        assert controller.manager.grab().save(str(ROOT / ".qa" / "native-chat.png"))
        for character_id in ("chiikawa", "hachiware", "usagi"):
            chat.character.setCurrentIndex(chat.character.findData(character_id))
            chat.input.setText("나 좀 응원해 줘.")
            chat.send_button.click()
            response = controller.chat.reply
            result[f"voice_{character_id}"] = response.character_id == character_id
            assert result[f"voice_{character_id}"]
        result["usagi_parenthesized"] = " (" in response.text and response.text.endswith(")")
        assert result["usagi_parenthesized"]
        controller.pet.react()
        result["usagi_click_balloon"] = controller.pet.bubble.text().endswith(")")
        assert result["usagi_click_balloon"]
        assert controller.manager.grab().save(str(ROOT / ".qa" / "native-voices.png"))
        session_id = controller.focus_timer.session_id
        result["character_picture_selected"] = controller.characters.active_id == "usagi"
        result["character_labels_match"] = chat.subtitle.text().startswith(
            "그림: 우사기 · 말투: 우사기"
        )
        controller.settings.update(mini_timer_style="ring")
        result["ring_timer_visible"] = (
            controller.mini_timer.isVisible() and controller.mini_timer.width() == 124
        )
        result["selection_kept_running_session"] = controller.focus_timer.session_id == session_id
        controller.manager.open_page(controller.manager.CHARACTER_PAGE)
        app.processEvents()
        assert all(
            result[key]
            for key in (
                "character_picture_selected",
                "character_labels_match",
                "ring_timer_visible",
                "selection_kept_running_session",
            )
        )
        assert controller.manager.grab().save(str(ROOT / ".qa" / "native-characters.png"))
        controller.focus_timer.stop()
        controller.manager.hide()
        controller.find_pet()
        QTest.qWait(850)
        controller.pet.bubble.hide()
        controller.pet.underMouse = lambda: False
        behavior = controller.behavior
        moment = [time.monotonic()]
        behavior.clock = lambda: moment[0]
        behavior.cursor = lambda: QPoint(
            controller.pet.x() - 300,
            round(controller.pet.y() + controller.pet.height() * 0.43),
        )
        behavior._last_tick = moment[0]
        result["behavior_initial_state"] = {
            "state": controller.animation.state,
            "base": controller.animation.base_state,
            "quiet": controller.companion.quiet(),
            "interacting": controller.pet.interacting,
        }
        behavior.poll()
        result["gaze_pose_static"] = (
            controller.animation.state == "look"
            and controller.animation.index == 12
            and not controller.pet.animation_timer.isActive()
        )
        controller.settings.update(roaming_enabled=True)
        behavior._next_walk = moment[0]
        behavior.poll()
        position = controller.pet.pos()
        moment[0] += 0.2
        behavior.poll()
        result["roaming_moves_pet"] = behavior.walk is not None and controller.pet.pos() != position
        controller.focus_timer.start(minutes=1)
        result["focus_stops_roaming"] = (
            behavior.walk is None
            and not behavior.timer.isActive()
            and controller.animation.state == "focus"
        )
        assert all(
            result[key] for key in ("gaze_pose_static", "roaming_moves_pet", "focus_stops_roaming")
        )
        controller.focus_timer.stop()
        sound = SilentSound()
        controller.celebration.audio = WavePlayer(backend=sound)
        controller.settings.update(completion_style="party", completion_sound_enabled=True)
        count_before = store.connection.execute("SELECT COUNT(*) FROM focus_sessions").fetchone()[0]
        controller.manager.focus_page.completion_preview.click()
        result["completion_preview_active"] = (
            controller.celebration.active
            and controller.celebration.audio.playing
            and controller.animation.state == "celebrate"
            and controller.animation.held
        )
        result["completion_preview_no_record"] = (
            store.connection.execute("SELECT COUNT(*) FROM focus_sessions").fetchone()[0]
            == count_before
        )
        controller.manager.open_page(controller.manager.FOCUS_PAGE)
        controller.manager.focus_page.verticalScrollBar().setValue(
            controller.manager.focus_page.verticalScrollBar().maximum()
        )
        app.processEvents()
        assert controller.manager.grab().save(str(ROOT / ".qa" / "native-completion.png"))
        controller.manager.focus_page.completion_stop.click()
        result["completion_stop_button"] = not controller.celebration.active and sound.calls[
            -1
        ] == (None, 0)
        controller.manager.focus_page.completion_preview.click()
        controller.focus_timer.start(minutes=1)
        result["new_timer_stops_completion"] = (
            not controller.celebration.active and not controller.celebration.audio.playing
        )
        assert all(
            result[key]
            for key in (
                "completion_preview_active",
                "completion_preview_no_record",
                "completion_stop_button",
                "new_timer_stops_completion",
            )
        )
        QTimer.singleShot(300, controller.quit)
    except Exception as error:
        result["error"] = repr(error)
        app.exit(1)


QTimer.singleShot(500, verify)
QTimer.singleShot(15000, lambda: app.exit(2))
code = app.exec()
reopened = Store(directory / "buddy.db")
result["unfinished_focus_checkpoint"] = (
    reopened.connection.execute("SELECT payload FROM timer_state").fetchone()[0].find('"paused"')
    >= 0
)
result["focus_timer_stopped"] = not controller.focus_timer.timer.isActive()
result["behavior_timer_stopped"] = not controller.behavior.timer.isActive()
result["completion_timer_stopped"] = not controller.celebration.timer.isActive()
result["persisted_voice"] = reopened.load_settings().chat_character_id == "usagi"
result["persisted_after_exit"] = reopened.load_settings().character_name == "테스트 친구"
reopened.close()
next_guard = SingleInstance(directory)
result["lock_released_after_exit"] = next_guard.acquire()
result["companion_timer_stopped"] = not controller.companion.timer.isActive()
result["briefing_timer_stopped"] = not controller.briefing.timer.isActive()
result["notification_timer_stopped"] = not controller.notifications.timer.isActive()
next_guard.close()
result["failed_checks"] = [key for key, value in result.items() if value is False]
if result["failed_checks"]:
    code = code or 1
result["exit_code"] = code
(ROOT / ".qa" / "native-smoke-characters.json").write_text(
    json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
)
print(json.dumps(result, ensure_ascii=False))
raise SystemExit(code)
