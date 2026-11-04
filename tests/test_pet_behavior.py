import math
import random
import sqlite3

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QSignalSpy, QTest
from test_focus_ui import controller as _controller_fixture

from desktop_buddy.characters.behavior import look_direction, plan_walk
from desktop_buddy.core.geometry import Rect, keep_visible

controller = _controller_fixture


@pytest.mark.parametrize(
    ("dx", "dy", "index"),
    [
        (0, -1, 0),
        (1, -1, 2),
        (1, 0, 4),
        (1, 1, 6),
        (0, 1, 8),
        (-1, 1, 10),
        (-1, 0, 12),
        (-1, -1, 14),
    ],
)
def test_look_pose_cardinal_and_diagonal_directions(dx, dy, index):
    assert look_direction(dx, dy) == index


def test_gaze_hysteresis_avoids_flicker_at_sector_boundary():
    angle = math.radians(12)
    assert look_direction(math.sin(angle), -math.cos(angle)) == 1
    assert look_direction(math.sin(angle), -math.cos(angle), 0) == 0
    angle = math.radians(17)
    assert look_direction(math.sin(angle), -math.cos(angle), 0) == 1


@pytest.mark.parametrize("x,direction", [(-800, -1), (-700, 1), (-176, 1), (-400, -1)])
def test_walk_stays_in_current_negative_coordinate_work_area(x, direction):
    area = Rect(-800, -100, 800, 600)
    walk = plan_walk(x, 0, 176, area, direction, 100, 2)
    assert walk is not None
    for now in (0, 2, 2.5, 100):
        px, py, _ = walk.position(now)
        assert area.x <= px <= -176 and py == 0
    assert walk.position(100) == (walk.end_x, 0, True)


@pytest.mark.parametrize("area", [Rect(0, 0, 80, 80), Rect(0, 0, 180, 400)])
def test_no_roaming_when_work_area_has_insufficient_room(area):
    assert plan_walk(0, 0, 176, area, 1, 100, 0) is None


@pytest.fixture
def moving_buddy(controller, monkeypatch):
    buddy, clock = controller
    buddy.characters.select("usagi")
    buddy.manager.hide()
    buddy.find_pet()
    buddy.pet.bubble.hide()
    buddy.pet.move(100, 100)
    monkeypatch.setattr(buddy.pet, "underMouse", lambda: False)
    area = Rect(0, 0, 900, 700)
    monkeypatch.setattr(buddy.pet, "work_area", lambda: area)
    monkeypatch.setattr(
        buddy.pet, "safe_position", lambda x, y: keep_visible(x, y, buddy.pet.width(), [area])
    )
    service = buddy.behavior
    service.timer.stop()
    service.clock = clock.monotonic
    service.cursor = lambda: QPoint(700, 100)
    service.rng = random.Random(4)
    service._last_tick = clock.mono
    service._next_walk = 999
    buddy.animation.play("idle", force=True)
    return buddy, clock, service


def start_walk(buddy, service):
    buddy.settings.update(roaming_enabled=True)
    buddy.pet.bubble.hide()
    service._next_walk = service.clock()
    service.poll()
    assert service.walk is not None
    return service.walk


def test_cursor_selects_static_pose_and_preserves_it_across_base_refresh(moving_buddy):
    buddy, _, service = moving_buddy
    service.cursor = lambda: QPoint(500, round(buddy.pet.y() + buddy.pet.height() * 0.43))
    service.poll()
    assert buddy.animation.state == "look" and buddy.animation.index == 4
    assert not buddy.pet.animation_timer.isActive()
    buddy.animation.advance()
    buddy.presentation.refresh()
    assert buddy.animation.state == "look" and buddy.animation.index == 4
    assert service.timer.interval() == 120


def test_direct_reaction_preempts_gaze_and_gaze_resumes_after_reaction(moving_buddy):
    buddy, _, service = moving_buddy
    service.poll()
    buddy.pet.react()
    assert buddy.animation.state == "happy" and not service.timer.isActive()
    assert not buddy.animation.show_ambient("look", 4)
    for _ in range(len(buddy.animation.clip.frames)):
        buddy.animation.advance()
    assert buddy.animation.state == "idle"
    service.poll()
    assert buddy.animation.state == "look"


def test_hover_keeps_gaze_stable_and_prevents_roaming(moving_buddy, monkeypatch):
    buddy, _, service = moving_buddy
    buddy.settings.update(roaming_enabled=True)
    monkeypatch.setattr(buddy.pet, "underMouse", lambda: True)
    service.cursor = lambda: QPoint(
        buddy.pet.x() + buddy.pet.width() // 2 + 50,
        round(buddy.pet.y() + buddy.pet.height() * 0.43),
    )
    service._next_walk = service.clock()
    for _ in range(5):
        service.poll()
        buddy.pet.hover_changed.emit(True)
    assert buddy.animation.state == "look" and buddy.animation.index == 4
    assert service.timer.isActive() and service.walk is None


@pytest.mark.parametrize("policy", ["hidden", "reduce", "quiet", "focus", "paused", "sleep", "sad"])
def test_policies_stop_gaze_and_roaming(moving_buddy, policy):
    buddy, _, service = moving_buddy
    service.poll()
    if policy == "hidden":
        buddy.hide_pet()
    elif policy == "reduce":
        buddy.settings.update(reduce_motion=True)
    elif policy == "quiet":
        buddy.settings.update(notifications_paused=True)
    elif policy in {"focus", "paused"}:
        buddy.focus_timer.start(minutes=25)
        if policy == "paused":
            buddy.focus_timer.pause()
    else:
        buddy.animation.set_base(policy, priority=30)
    service.poll()
    assert not service.timer.isActive() and service.walk is None
    assert buddy.animation.state != "look"


def test_roaming_saves_once_at_end_and_timer_follows_position(moving_buddy):
    buddy, clock, service = moving_buddy
    buddy.settings.update(mini_timer_mode="always")
    walk = start_walk(buddy, service)
    moved = QSignalSpy(buddy.pet.position_changed)
    before_timer = buddy.mini_timer.pos()
    assert service.timer.interval() == 33
    for _ in range(math.ceil(walk.duration / 0.1) + 1):
        clock.advance(0.1)
        service.poll()
    assert service.walk is None
    assert buddy.pet.pos() == QPoint(walk.end_x, walk.y)
    assert moved.count() == 1
    assert buddy.store.load_settings().x == walk.end_x
    assert buddy.mini_timer.pos() != before_timer


def test_long_event_gap_cancels_walk_without_jumping(moving_buddy):
    buddy, clock, service = moving_buddy
    start_walk(buddy, service)
    clock.advance(0.1)
    service.poll()
    position = buddy.pet.pos()
    clock.advance(20)
    service.poll()
    assert service.walk is None and buddy.pet.pos() == position
    assert service._next_walk > clock.mono


def test_focus_start_during_walk_preserves_position_and_focus_session(moving_buddy):
    buddy, clock, service = moving_buddy
    start_walk(buddy, service)
    clock.advance(0.1)
    service.poll()
    position = buddy.pet.pos()
    buddy.focus_timer.start(minutes=25)
    session_id = buddy.focus_timer.session_id
    assert service.walk is None and not service.timer.isActive()
    service.poll()
    assert buddy.pet.pos() == position and buddy.animation.state == "focus"
    assert buddy.focus_timer.session_id == session_id


@pytest.mark.parametrize("interaction", ["press", "menu", "near", "manager"])
def test_interaction_or_near_cursor_cancels_walk(moving_buddy, interaction):
    buddy, clock, service = moving_buddy
    start_walk(buddy, service)
    clock.advance(0.1)
    service.poll()
    position = buddy.pet.pos()
    if interaction == "press":
        QTest.mousePress(buddy.pet, Qt.MouseButton.LeftButton, pos=QPoint(80, 90))
    elif interaction == "menu":
        buddy.pet._menu_open = True
        buddy.pet.interaction_changed.emit()
    elif interaction == "manager":
        buddy.manager.open_page(0)
    else:
        service.cursor = lambda: buddy.pet.geometry().center()
    service.poll()
    assert service.walk is None and buddy.pet.pos() == position
    if interaction == "press":
        QTest.mouseRelease(buddy.pet, Qt.MouseButton.LeftButton, pos=QPoint(80, 90))


def test_manual_relocation_and_pack_change_invalidate_old_walk(moving_buddy):
    buddy, _, service = moving_buddy
    start_walk(buddy, service)
    buddy.pet.move(300, 100)
    assert service.walk is None
    service.poll()
    assert buddy.pet.x() == 300
    start_walk(buddy, service)
    buddy.characters.select("chiikawa")
    assert service.walk is None and buddy.pet.x() == 300


def test_disabled_roaming_does_not_move_pet_and_disabled_features_stop_polling(moving_buddy):
    buddy, clock, service = moving_buddy
    position = buddy.pet.pos()
    assert not buddy.settings.current.roaming_enabled
    for _ in range(400):
        clock.advance(0.1)
        service.poll()
    assert buddy.pet.pos() == position
    buddy.settings.update(cursor_look_enabled=False)
    assert not service.timer.isActive() and buddy.animation.state == "idle"


def test_behavior_settings_ui_persists_and_recovers_from_save_failure(moving_buddy, monkeypatch):
    buddy, _, service = moving_buddy
    page = buddy.manager.character_page
    assert page.look_enabled.isEnabled() and page.look_enabled.isChecked()
    page.roaming_enabled.click()
    assert buddy.store.load_settings().roaming_enabled
    monkeypatch.setattr(
        buddy.store,
        "save_settings",
        lambda *args: (_ for _ in ()).throw(sqlite3.OperationalError()),
    )
    page.look_enabled.click()
    assert page.look_enabled.isChecked() and buddy.settings.current.cursor_look_enabled
    assert "저장하지 못" in page.status.text()
    service.close()


def test_default_character_has_no_unsupported_behavior_and_shutdown_stops_timer(controller):
    buddy, _ = controller
    assert not buddy.behavior.timer.isActive()
    assert not buddy.manager.character_page.look_enabled.isEnabled()
    buddy.characters.select("usagi")
    buddy.find_pet()
    buddy.shutdown()
    buddy.behavior.refresh()
    buddy.behavior.poll()
    assert not buddy.behavior.timer.isActive()
