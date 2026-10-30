from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from test_focus import Clock, advance

from desktop_buddy.app import BuddyApplication
from desktop_buddy.characters.animation import AnimationState, Clip, load_clips
from desktop_buddy.core.paths import asset_directory
from desktop_buddy.database.store import Store
from desktop_buddy.services.power_events import PowerEventFilter
from desktop_buddy.services.single_instance import SingleInstance


@pytest.fixture
def controller(qapp, tmp_path):
    guard = SingleInstance(tmp_path)
    assert guard.acquire()
    store = Store(tmp_path / "buddy.db")
    buddy = BuddyApplication(qapp, store, guard, tmp_path)
    clock = Clock()
    buddy.focus_timer.clock = clock
    buddy.companion.clock = clock
    buddy.companion.guard.clock = clock
    buddy.companion.guard.acknowledge()
    buddy.companion.poll()
    buddy.focus_timer.timer.stop()
    yield buddy, clock
    buddy.shutdown()
    buddy.pet.deleteLater()
    buddy.mini_timer.deleteLater()
    buddy.manager.deleteLater()
    qapp.processEvents()


def test_focus_controls_statistics_and_delete_refresh(controller, qapp, monkeypatch):
    buddy, clock = controller
    page = buddy.manager.focus_page
    buddy.manager.open_page(buddy.manager.FOCUS_PAGE)
    page.minutes.setValue(1)
    page.start_button.click()
    assert buddy.focus_timer.status == "running" and not page.start_button.isEnabled()
    assert buddy.animation.base_state == "focus"
    assert buddy.mini_timer.isVisible()
    advance(buddy.focus_timer, clock, 10)
    page.pause_button.click()
    assert buddy.focus_timer.status == "paused"
    assert page.resume_button.isVisible()
    advance(buddy.focus_timer, clock, 30)
    page.resume_button.click()
    advance(buddy.focus_timer, clock, 50)
    assert page.next_button.isVisible() and buddy.focus_timer.status == "ready"
    assert buddy.animation.state == "complete"
    buddy.manager.open_page(buddy.manager.STATISTICS_PAGE)
    stats = buddy.manager.statistics_page
    assert stats.records.rowCount() == 1
    assert stats.records.item(0, 3).text() == "1분"
    stats.records.selectRow(0)
    monkeypatch.setattr("desktop_buddy.ui.statistics_page.confirm_delete", lambda *args: True)
    stats.delete()
    assert stats.records.rowCount() == 0 and buddy.statistics.all_total() == 0


def test_mini_modes_hidden_pet_and_click_through(controller):
    buddy, clock = controller
    buddy.settings.update(mini_timer_mode="always")
    assert buddy.mini_timer.isVisible()
    assert buddy.mini_timer.windowFlags() & Qt.WindowType.WindowTransparentForInput
    buddy.hide_pet()
    assert not buddy.mini_timer.isVisible()
    buddy.find_pet()
    buddy.settings.update(mini_timer_mode="hover")
    assert not buddy.mini_timer.isVisible()
    buddy.pet.hover_changed.emit(True)
    assert buddy.mini_timer.isVisible()
    buddy.pet.hover_changed.emit(False)
    assert not buddy.mini_timer.isVisible()
    buddy.settings.update(mini_timer_mode="never")
    buddy.focus_timer.start()
    assert not buddy.mini_timer.isVisible()


def test_power_broadcast_pauses_once_and_never_resumes(controller):
    buddy, clock = controller
    timer = buddy.focus_timer
    timer.start()
    advance(timer, clock, 5)
    handler = PowerEventFilter(timer)
    handler.handle(0x218, 4)
    assert timer.status == "paused"
    clock.advance(3600)
    handler.handle(0x218, 18)
    assert timer.elapsed == 5 and timer.status == "paused"
    timer.resume()
    advance(timer, clock, 5)
    timer.stop()
    assert buddy.statistics.all_total() == 10


def test_focus_quiet_only_while_running(controller):
    buddy, clock = controller
    buddy.settings.update(quiet_enabled=False, notifications_enabled=True)
    buddy.focus_timer.start()
    assert buddy.notifications.muted(clock.now())
    buddy.focus_timer.pause()
    assert not buddy.notifications.muted(clock.now())
    buddy.focus_timer.resume()
    buddy.settings.update(focus_quiet=False)
    assert not buddy.notifications.muted(clock.now())


def test_base_animation_survives_reactions_and_reduce_motion(controller):
    buddy, clock = controller
    buddy.focus_timer.start()
    buddy.pet.react()
    assert buddy.animation.state == "happy"
    for _ in range(8):
        buddy.animation.advance()
    assert buddy.animation.state == "focus"
    buddy.settings.update(reduce_motion=True)
    assert buddy.animation.state == "focus" and not buddy.pet.animation_timer.isActive()
    buddy.focus_timer.pause()
    assert buddy.animation.state == "idle"


def test_single_frame_nonloop_returns_to_base(qapp):
    clips = load_clips(asset_directory() / "default_character")
    clips["complete"] = Clip([clips["idle"].frames[0]], 3, False)
    animation = AnimationState(clips)
    animation.set_base("focus")
    animation.play("complete")
    animation.set_base("break")
    animation.advance()
    assert animation.state == "break"


def test_bundle_whitelists_original_art():
    source = (Path(__file__).resolve().parents[1] / "DesktopBuddy.spec").read_text()
    assert "default_character" in source and "icons" in source
    assert "(str(root / 'assets'), 'assets')" not in source


@pytest.mark.parametrize("mode,length", [("7", 7), ("30", 30), ("weeks", 8), ("months", 6)])
def test_chart_periods_include_zero_days_and_consistent_totals(controller, mode, length):
    buddy, clock = controller
    buddy.focus_timer.start(minutes=1)
    advance(buddy.focus_timer, clock, 30)
    buddy.focus_timer.stop()
    buddy.manager.open_page(buddy.manager.STATISTICS_PAGE)
    page = buddy.manager.statistics_page
    page.period.setCurrentIndex(page.period.findData(mode))
    assert len(page.chart.values) == length
    assert sum(seconds for _, seconds in page.chart.values) == 30
    assert page.message.text() == ""


def test_timer_completion_respects_global_pause_and_quiet_hours(controller, monkeypatch):
    from desktop_buddy.models.focus import PhaseFinished

    buddy, clock = controller
    spoken = []
    monkeypatch.setattr(buddy.pet, "speak", lambda text, **kwargs: spoken.append(text))
    result = PhaseFinished("focus", 1, 60, "short_break")
    buddy.settings.update(notifications_paused=True)
    buddy._phase_finished(result)
    assert spoken == []
    buddy.settings.update(
        notifications_paused=False, quiet_enabled=True, quiet_start="22:00", quiet_end="08:00"
    )
    buddy._phase_finished(result)
    assert spoken == []
    buddy.settings.update(quiet_enabled=False, notifications_enabled=False)
    buddy._phase_finished(result)
    assert len(spoken) == 1
