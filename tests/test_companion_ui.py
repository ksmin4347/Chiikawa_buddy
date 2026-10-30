from datetime import timedelta

import pytest
from PySide6.QtCore import QDate
from test_companion import seed
from test_focus import Clock, advance

from desktop_buddy.app import BuddyApplication
from desktop_buddy.database.store import Store
from desktop_buddy.services.single_instance import SingleInstance


@pytest.fixture
def buddy(qapp, tmp_path):
    guard = SingleInstance(tmp_path)
    assert guard.acquire()
    store = Store(tmp_path / "buddy.db")
    controller = BuddyApplication(qapp, store, guard, tmp_path)
    clock = Clock()
    controller.focus_timer.timer.stop()
    controller.companion.stop()
    controller.briefing.stop()
    controller.focus_timer.clock = clock
    controller.companion.clock = clock
    controller.companion.guard.clock = clock
    controller.companion.guard.acknowledge()
    controller.companion.poll()
    yield controller, clock
    controller.shutdown()
    for widget in (
        controller.pet,
        controller.mini_timer,
        controller.manager,
        controller.briefing_card,
    ):
        widget.deleteLater()
    qapp.processEvents()


def test_small_focus_restores_preferences_and_manual_hidden_stays_hidden(buddy):
    controller, clock = buddy
    controller.settings.update(size=216, focus_appearance="small")
    controller.focus_timer.start()
    assert controller.pet.width() == 128
    assert controller.settings.current.size == 216
    controller.focus_timer.stop()
    assert controller.pet.width() == 216 and controller.pet.isVisible()
    controller.focus_timer.start()
    controller.hide_pet()
    controller.focus_timer.stop()
    assert not controller.pet.isVisible() and not controller.mini_timer.isVisible()


def test_timer_only_hidden_and_manual_find_override(buddy):
    controller, clock = buddy
    controller.settings.update(focus_appearance="timer_only", mini_timer_mode="never")
    controller.focus_timer.start()
    assert not controller.pet.isVisible() and controller.mini_timer.isVisible()
    controller.focus_timer.pause()
    assert controller.pet.isVisible() and not controller.mini_timer.isVisible()
    controller.settings.update(focus_appearance="hidden")
    controller.focus_timer.resume()
    assert not controller.pet.isVisible() and not controller.mini_timer.isVisible()
    controller.find_pet()
    assert controller.pet.isVisible()
    controller.focus_timer.stop()
    assert controller.pet.isVisible()


def test_fullscreen_restore_respects_user_hide(buddy):
    controller, clock = buddy
    controller.companion.attention.fullscreen = lambda: True
    controller.settings.update(fullscreen_hide=True)
    assert not controller.pet.isVisible()
    controller.companion.attention.fullscreen = lambda: False
    controller.companion.poll()
    assert controller.pet.isVisible()
    controller.companion.attention.fullscreen = lambda: True
    controller.companion.poll()
    controller.hide_pet()
    controller.companion.attention.fullscreen = lambda: False
    controller.companion.poll()
    assert not controller.pet.isVisible()


def test_priority_sleep_gap_focus_and_manual_reaction(buddy):
    controller, clock = buddy
    controller.settings.update(rest_weekdays=())
    day = clock.now().astimezone(controller.planning.zone).date()
    seed(controller.companion, day - timedelta(days=3))
    assert controller.animation.base_state == "sad"
    controller.focus_timer.start()
    assert controller.animation.base_state == "focus"
    controller.pet.react()
    controller.animation.play("complete", priority=80)
    assert controller.animation.state == "happy"
    for _ in range(8):
        controller.animation.advance()
    assert controller.animation.state == "focus"
    controller.focus_timer.stop()
    assert controller.animation.base_state == "sad"
    controller.settings.update(sleep_enabled=True, sleep_start="22:00", sleep_end="08:00")
    assert controller.animation.base_state == "sleep"


def test_speech_guard_and_essential_timer_option(buddy):
    controller, clock = buddy
    controller.settings.update(notifications_paused=True)
    controller.pet.speak("자동 안부")
    assert not controller.pet.bubble.isVisible()
    controller.pet.react()
    assert controller.pet.bubble.isVisible()
    controller.pet.bubble.hide()
    controller.settings.update(timer_alert_during_quiet=True)
    controller.pet.speak("타이머 완료", essential=True)
    assert controller.pet.bubble.isVisible()
    controller.presentation.refresh()
    assert controller.pet.bubble.isVisible()


def test_companion_page_rest_periods_settings_and_clock_confirm(buddy, monkeypatch):
    controller, clock = buddy
    controller.manager.open_page(controller.manager.COMPANION_PAGE)
    page = controller.manager.companion_page
    page.checks["emotion_enabled"].setChecked(False)
    assert not controller.settings.current.emotion_enabled
    day = clock.now().date()
    page.rest_start.setDate(QDate(day))
    page.rest_end.setDate(QDate(day + timedelta(days=7)))
    page.add_rest()
    assert page.periods.rowCount() == 1
    page.periods.selectRow(0)
    monkeypatch.setattr("desktop_buddy.ui.companion_page.confirm_delete", lambda *args: True)
    page.delete_rest()
    assert page.periods.rowCount() == 0
    clock.advance(1, wall=3600)
    controller.companion.poll()
    assert page.clock_button.isVisible()
    page.clock_button.click()
    assert not page.clock_button.isVisible()


def test_briefing_card_manual_navigation_and_auto_quiet_hide(buddy):
    controller, clock = buddy
    controller.show_today_briefing()
    assert controller.briefing_card.isVisible()
    controller.briefing_card.open_planning()
    assert controller.manager.pages.currentIndex() == 1
    assert not controller.briefing_card.isVisible()
    report = controller.briefing.build()
    controller._show_briefing(report)
    controller.focus_timer.start()
    assert not controller.briefing_card.isVisible()
    controller.show_today_briefing()
    assert controller.briefing_card.isVisible()


def test_record_checkbox_applies_to_new_session_and_preserves_existing(buddy):
    controller, clock = buddy
    controller.focus_timer.start(minutes=1)
    advance(controller.focus_timer, clock, 5)
    controller.settings.update(record_focus=False)
    advance(controller.focus_timer, clock, 5)
    controller.focus_timer.stop()
    assert controller.statistics.all_total() == 10
    controller.focus_timer.start(minutes=1)
    advance(controller.focus_timer, clock, 5)
    controller.focus_timer.stop()
    assert controller.statistics.all_total() == 10
