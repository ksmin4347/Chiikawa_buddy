import sqlite3
import wave
from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QSignalSpy, QTest
from test_focus import advance
from test_focus_ui import controller as _controller_fixture

from desktop_buddy.models.focus import PhaseFinished
from desktop_buddy.services.completion_audio import SONG_SECONDS, WavePlayer

controller = _controller_fixture


class FakeSound:
    SND_FILENAME = 0x20000
    SND_ASYNC = 1
    SND_NODEFAULT = 2

    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    def PlaySound(self, sound, flags):
        self.calls.append((sound, flags))
        if sound is not None and self.fail:
            raise RuntimeError("audio unavailable")


@pytest.mark.parametrize("character", list(SONG_SECONDS))
def test_bundled_wave_format_async_flags_and_stop(character):
    backend = FakeSound()
    player = WavePlayer(backend=backend)
    player.play(character)
    path, flags = backend.calls[0]
    with wave.open(path, "rb") as audio:
        assert audio.getnframes() / audio.getframerate() == SONG_SECONDS[character]
    assert flags == backend.SND_FILENAME | backend.SND_ASYNC | backend.SND_NODEFAULT
    assert player.playing
    player.stop()
    player.stop()
    assert backend.calls[-1] == (None, 0) and len(backend.calls) == 2


@pytest.mark.parametrize("character", ["../usagi", "C:/outside", "moru", "unknown"])
def test_audio_accepts_only_fixed_character_ids(character):
    backend = FakeSound()
    with pytest.raises(ValueError):
        WavePlayer(backend=backend).play(character)
    assert backend.calls == []


@pytest.mark.parametrize(
    "problem", ["missing", "broken", "short", "channels", "bits", "rate", "huge", "truncated"]
)
def test_bad_audio_fails_before_device_playback(tmp_path, problem):
    path = tmp_path / "usagi.wav"
    if problem not in {"missing", "huge", "broken"}:
        with wave.open(str(path), "wb") as output:
            output.setnchannels(1 if problem == "channels" else 2)
            output.setsampwidth(1 if problem == "bits" else 2)
            output.setframerate(8000 if problem == "rate" else 48000)
            output.writeframes(b"\0" * 192000 * (1 if problem == "short" else 16))
        if problem == "truncated":
            path.write_bytes(path.read_bytes()[:100])
    elif problem == "huge":
        path.write_bytes(b"\0" * (12 * 1024 * 1024 + 1))
    elif problem == "broken":
        path.write_bytes(b"not a wave")
    backend = FakeSound()
    with pytest.raises((ValueError, OSError, wave.Error, EOFError)):
        WavePlayer(tmp_path, backend).play("usagi")
    assert backend.calls == []


@pytest.fixture
def celebration(controller):
    buddy, clock = controller
    buddy.characters.select("usagi")
    buddy.find_pet()
    buddy.pet.bubble.hide()
    service = buddy.celebration
    service.clock = clock.monotonic
    backend = FakeSound()
    service.audio = WavePlayer(backend=backend)
    return buddy, clock, service, backend


def complete(buddy, clock, *, kind="focus"):
    buddy.focus_timer.start(kind=kind, minutes=1)
    item_id = buddy.focus_timer.session_id
    advance(buddy.focus_timer, clock, 60)
    return PhaseFinished(kind, item_id, 60, "short_break" if kind == "focus" else "focus")


def test_default_simple_completion_remains_silent_and_returns_to_base(celebration):
    buddy, clock, service, backend = celebration
    complete(buddy, clock)
    assert buddy.animation.state == "complete" and not buddy.animation.held
    assert backend.calls == [] and service.active
    for _ in range(len(buddy.animation.clip.frames)):
        buddy.animation.advance()
    assert not service.active and buddy.animation.state == buddy.animation.base_state


def test_party_without_music_holds_across_settings_and_stops_at_six_seconds(celebration):
    buddy, clock, service, backend = celebration
    buddy.settings.update(completion_style="party")
    complete(buddy, clock)
    assert buddy.animation.state == "celebrate" and buddy.animation.held
    buddy.settings.update(theme="dark")
    buddy.presentation.refresh()
    assert service.active and buddy.animation.state == "celebrate"
    for _ in range(12):
        clock.advance(0.5)
        service.tick()
    assert not service.active and not buddy.animation.held and backend.calls == []


@pytest.mark.parametrize("character", list(SONG_SECONDS))
def test_preview_uses_selected_music_and_never_creates_focus_records(celebration, character):
    buddy, clock, service, backend = celebration
    buddy.characters.select(character)
    buddy.settings.update(completion_style="party", completion_sound_enabled=True)
    service.preview()
    assert service.active and service.previewing and service.audio.playing
    assert Path(backend.calls[0][0]).name == f"{character}.wav"
    assert service._duration == SONG_SECONDS[character]
    for _ in range(SONG_SECONDS[character] * 2):
        clock.advance(0.5)
        service.tick()
    assert not service.active and backend.calls[-1] == (None, 0)
    assert buddy.statistics.all_total() == 0
    assert buddy.store.connection.execute("SELECT COUNT(*) FROM focus_sessions").fetchone()[0] == 0


def test_duplicate_completion_does_not_restart_music(celebration):
    buddy, clock, service, backend = celebration
    buddy.settings.update(completion_style="party", completion_sound_enabled=True)
    result = complete(buddy, clock)
    started = service._started
    service.handle(result)
    assert service._started == started and len(backend.calls) == 1
    assert buddy.focus_timer.completed_today() == 1


def test_stopped_focus_does_not_reward_and_break_has_no_music(celebration):
    buddy, clock, service, backend = celebration
    buddy.settings.update(completion_style="party", completion_sound_enabled=True)
    buddy.focus_timer.start(minutes=1)
    advance(buddy.focus_timer, clock, 20)
    buddy.focus_timer.stop()
    assert not service.active and backend.calls == []
    complete(buddy, clock, kind="short_break")
    assert backend.calls == [] and buddy.animation.state == "complete"


def test_auto_next_keeps_timer_running_without_long_show_or_music(celebration):
    buddy, clock, service, backend = celebration
    buddy.settings.update(
        completion_style="party", completion_sound_enabled=True, auto_next_phase=True
    )
    complete(buddy, clock)
    assert buddy.focus_timer.status == "running" and buddy.focus_timer.phase == "short_break"
    assert not service.active and not buddy.animation.held and backend.calls == []


@pytest.mark.parametrize("policy", ["hidden", "quiet", "sleep", "notices_off"])
def test_completion_obeys_automatic_notification_policies(celebration, policy):
    buddy, clock, service, backend = celebration
    buddy.settings.update(completion_style="party", completion_sound_enabled=True)
    if policy == "hidden":
        buddy.hide_pet()
    elif policy == "quiet":
        buddy.settings.update(notifications_paused=True)
    elif policy == "sleep":
        buddy.settings.update(sleep_enabled=True, sleep_start="22:00", sleep_end="08:00")
    else:
        buddy.settings.update(timer_notifications=False)
    complete(buddy, clock)
    assert not service.active and backend.calls == []


def test_reduce_motion_allows_explicit_music_without_animation(celebration):
    buddy, clock, service, backend = celebration
    buddy.settings.update(
        completion_style="party", completion_sound_enabled=True, reduce_motion=True
    )
    complete(buddy, clock)
    assert service.audio.playing and len(backend.calls) == 1
    assert buddy.animation.state != "celebrate" and not buddy.animation.held
    buddy.pet.react()
    assert not service.active and not service.audio.playing


@pytest.mark.parametrize(
    "action",
    [
        "hide",
        "quiet",
        "sound_off",
        "style",
        "character",
        "press",
        "reaction",
        "start",
        "reset",
        "power",
        "close",
    ],
)
def test_active_show_is_cancelled_and_audio_stopped(celebration, action):
    buddy, _, service, backend = celebration
    buddy.settings.update(completion_style="party", completion_sound_enabled=True)
    service.preview()
    if action == "hide":
        buddy.hide_pet()
    elif action == "quiet":
        buddy.settings.update(notifications_paused=True)
    elif action == "sound_off":
        buddy.settings.update(completion_sound_enabled=False)
    elif action == "style":
        buddy.settings.update(completion_style="simple")
    elif action == "character":
        buddy.characters.select("chiikawa")
    elif action == "press":
        QTest.mousePress(buddy.pet, Qt.MouseButton.LeftButton, pos=QPoint(80, 90))
    elif action == "reaction":
        buddy.pet.react()
    elif action == "start":
        buddy.focus_timer.start(minutes=1)
    elif action == "reset":
        buddy.focus_timer.reset()
    elif action == "power":
        buddy.power_filter.handle(0x0218, 4)
    else:
        buddy.shutdown()
    assert not service.active and not service.timer.isActive()
    assert not service.audio.playing and backend.calls[-1] == (None, 0)
    if action == "reaction":
        assert buddy.animation.state == "happy"
    elif action == "press":
        QTest.mouseRelease(buddy.pet, Qt.MouseButton.LeftButton, pos=QPoint(80, 90))


def test_long_gap_stops_without_replaying(celebration):
    buddy, clock, service, backend = celebration
    buddy.settings.update(completion_style="party", completion_sound_enabled=True)
    service.preview()
    clock.advance(20)
    service.tick()
    service.tick()
    assert not service.active and len(backend.calls) == 2


def test_audio_failure_keeps_completed_data_and_shortens_silent_party(celebration):
    buddy, clock, service, backend = celebration
    backend.fail = True
    errors = QSignalSpy(service.failed)
    buddy.settings.update(completion_style="party", completion_sound_enabled=True)
    complete(buddy, clock)
    assert service.active and not service.audio.playing and service._duration == 6
    assert errors.count() == 1 and buddy.focus_timer.completed_today() == 1
    assert buddy.statistics.all_total() == 60


def test_failed_commit_never_starts_a_completion_show(celebration, monkeypatch):
    buddy, clock, service, backend = celebration
    buddy.settings.update(completion_style="party", completion_sound_enabled=True)
    monkeypatch.setattr(
        buddy.focus_timer.repository,
        "finish",
        lambda *args: (_ for _ in ()).throw(sqlite3.OperationalError("full")),
    )
    complete(buddy, clock)
    assert buddy.focus_timer.status == "paused"
    assert not service.active and backend.calls == []
    assert buddy.focus_timer.completed_today() == 0


def test_music_only_preview_failure_leaves_no_active_state(celebration):
    buddy, _, service, backend = celebration
    backend.fail = True
    buddy.settings.update(completion_style="off", completion_sound_enabled=True)
    with pytest.raises(ValueError, match="재생하지 못"):
        service.preview()
    assert not service.active and not service.previewing and not service.timer.isActive()


def test_completion_controls_and_save_failure(celebration, monkeypatch):
    buddy, _, service, _ = celebration
    page = buddy.manager.focus_page
    assert page.completion_preview.isEnabled() and not page.completion_stop.isEnabled()
    page.completion_style.setCurrentIndex(page.completion_style.findData("party"))
    page.completion_sound.click()
    page.completion_preview.click()
    assert service.active and page.completion_stop.isEnabled()
    page.completion_stop.click()
    assert not service.active
    monkeypatch.setattr(
        buddy.store,
        "save_settings",
        lambda *args: (_ for _ in ()).throw(sqlite3.OperationalError()),
    )
    page.completion_style.setCurrentIndex(page.completion_style.findData("off"))
    assert page.completion_style.currentData() == "party"
    assert "저장하지 못" in page.error_label.text()
    assert "저장하지 못" in page.completion_error.text()


def test_preview_is_blocked_while_running_and_moru_has_no_music(controller):
    buddy, _ = controller
    assert not buddy.manager.focus_page.completion_sound.isEnabled()
    buddy.focus_timer.start(minutes=1)
    with pytest.raises(ValueError):
        buddy.celebration.preview()
    assert not buddy.manager.focus_page.completion_preview.isEnabled()
    buddy.manager.focus_page.preview_completion()
    assert "타이머를 멈춘 뒤" in buddy.manager.focus_page.completion_error.text()
    assert buddy.focus_timer.status == "running"
