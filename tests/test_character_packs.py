import json
import sqlite3

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage
from test_focus_ui import controller as _controller_fixture

from desktop_buddy.app import BuddyApplication
from desktop_buddy.characters.animation import AssetError, load_clips
from desktop_buddy.core.settings import Settings
from desktop_buddy.database.store import Store
from desktop_buddy.services.character_service import CharacterCatalog, CharacterService
from desktop_buddy.services.settings_service import SettingsService
from desktop_buddy.services.single_instance import SingleInstance

pack_controller = _controller_fixture


@pytest.mark.parametrize("key", ["chiikawa", "hachiware", "usagi"])
def test_bundled_packs_frames_holds_transparency_and_local_fallbacks(qapp, key):
    clips = CharacterCatalog().load(key)
    assert set(clips) == {
        "idle",
        "happy",
        "focus",
        "break",
        "complete",
        "sad",
        "worried",
        "sleep",
        "run_right",
        "run_left",
        "look",
    }
    assert clips["worried"] is clips["idle"] and clips["sleep"] is clips["idle"]
    assert clips["idle"].durations_ms == (280, 110, 110, 140, 140, 320)
    assert not clips["complete"].loop and len(clips["focus"].frames) == 3
    assert clips["look"].manual and len(clips["look"].frames) == 16
    assert sum(len(clip.frames) for clip in {id(c): c for c in clips.values()}.values()) == 64
    for clip in clips.values():
        assert all(
            image.width() == 256 and image.height() == 256 and image.hasAlphaChannel()
            for image in clip.frames
        )


@pytest.fixture
def small_pack(tmp_path, qapp):
    root = tmp_path / "pack"
    root.mkdir()
    image = QImage(32, 32, QImage.Format.Format_RGBA8888)
    image.fill(Qt.GlobalColor.green)
    image.save(str(root / "one.png"))
    manifest = {"id": "test", "states": {"idle": {"frames": ["one.png"], "loop": True, "fps": 4}}}
    (root / "manifest.json").write_text(json.dumps(manifest), "utf-8")
    return root, manifest


@pytest.mark.parametrize(
    "attack", ["../outside.png", "/outside.png", "one.jpg", "missing.png", 123]
)
def test_rejects_bad_frame_paths_and_formats(small_pack, attack):
    root, manifest = small_pack
    manifest["states"]["idle"]["frames"] = [attack]
    (root / "manifest.json").write_text(json.dumps(manifest), "utf-8")
    with pytest.raises(AssetError):
        load_clips(root, strict=True)


@pytest.mark.parametrize(
    "problem",
    [
        "too_many",
        "wrong_holds",
        "negative_hold",
        "loop_alias",
        "wrong_id",
        "oversize_json",
        "huge_png",
        "blank",
        "broken",
        "memory",
        "outside_atlas",
        "extreme_coordinate",
        "deep_json",
        "extreme_fps",
    ],
)
def test_rejects_invalid_or_excessive_packs(small_pack, problem):
    root, manifest = small_pack
    if problem == "too_many":
        manifest["states"]["idle"]["frames"] = ["one.png"] * 65
    elif problem == "wrong_holds":
        manifest["states"]["idle"]["durations_ms"] = [100, 200]
    elif problem == "negative_hold":
        manifest["states"]["idle"]["durations_ms"] = [-1]
    elif problem == "loop_alias":
        manifest["aliases"] = {"other": "missing"}
    elif problem == "wrong_id":
        manifest["id"] = "other"
    elif problem == "oversize_json":
        (root / "manifest.json").write_text(" " * 65537, "utf-8")
    elif problem == "huge_png":
        image = QImage(1100, 1100, QImage.Format.Format_RGBA8888)
        image.fill(Qt.GlobalColor.red)
        image.save(str(root / "one.png"))
    elif problem == "blank":
        image = QImage(32, 32, QImage.Format.Format_RGBA8888)
        image.fill(Qt.GlobalColor.transparent)
        image.save(str(root / "one.png"))
    elif problem == "broken":
        (root / "one.png").write_bytes(b"not a png")
    elif problem == "memory":
        image = QImage(1024, 1024, QImage.Format.Format_RGBA8888)
        image.fill(Qt.GlobalColor.red)
        image.save(str(root / "one.png"))
        payload = (root / "one.png").read_bytes()
        frames = [f"frame_{index}.png" for index in range(14)]
        for name in frames:
            (root / name).write_bytes(payload)
        manifest["states"]["idle"]["frames"] = frames
    elif problem == "outside_atlas":
        manifest["atlas"] = {"path": "one.png", "cell_width": 16, "cell_height": 16}
        manifest["states"]["idle"]["frames"] = [{"row": 99, "column": 0}]
    elif problem == "extreme_coordinate":
        manifest["atlas"] = {"path": "one.png", "cell_width": 16, "cell_height": 16}
        manifest["states"]["idle"]["frames"] = [{"row": 10**100, "column": 0}]
    elif problem == "deep_json":
        (root / "manifest.json").write_text("[" * 2000 + "0" + "]" * 2000, "utf-8")
    elif problem == "extreme_fps":
        manifest["states"]["idle"]["fps"] = 10**1000
    if problem not in {"oversize_json", "deep_json"}:
        (root / "manifest.json").write_text(json.dumps(manifest), "utf-8")
    with pytest.raises(AssetError):
        load_clips(root, strict=True, expected_id="test")


def test_legacy_preferences_preserve_choice_without_new_onboarding():
    assert Settings.from_mapping({"character_name": "기존 친구"}).character_selection_done
    old_voice = Settings.from_mapping({"chat_character_id": "usagi"})
    assert old_voice.character_id == "usagi" and old_voice.character_selection_done
    assert not Settings.from_mapping({}).character_selection_done


def test_hot_swap_preserves_focus_state_position_and_restarts_cache(pack_controller):
    buddy, clock = pack_controller
    buddy.settings.update(focus_appearance="small")
    buddy.focus_timer.start(minutes=25)
    session_id = buddy.focus_timer.session_id
    position = buddy.pet.pos()
    buddy.chat.set_character("usagi")
    assert buddy.characters.active_id == "usagi"
    assert buddy.manager.chat_page.subtitle.text().startswith("그림: 우사기 · 말투: 우사기")
    assert (
        buddy.settings.current.character_id == buddy.settings.current.chat_character_id == "usagi"
    )
    assert buddy.focus_timer.session_id == session_id and buddy.focus_timer.status == "running"
    assert buddy.pet.pos() == position and buddy.pet.width() == 128
    assert buddy.animation.state == "focus" and len(buddy.animation.clip.frames) == 3
    assert buddy.pet._frames["focus"][0].width() <= 128
    buddy.focus_timer.stop()
    assert buddy.pet.width() == buddy.settings.current.size
    buddy.hide_pet()
    buddy.chat.set_character("hachiware")
    assert not buddy.pet.isVisible() and not buddy.pet.animation_timer.isActive()
    assert buddy.manager.chat_page.subtitle.text().startswith("그림: 하치와레 · 말투: 하치와레")


@pytest.mark.parametrize("custom_name", [None, "내 공부 친구"])
def test_selection_updates_default_name_and_preserves_custom_name(pack_controller, custom_name):
    buddy, _ = pack_controller
    if custom_name is not None:
        buddy.settings.update(character_name=custom_name)
    buddy.characters.select("chiikawa")
    assert buddy.settings.current.character_name == (custom_name or "치이카와")
    buddy.characters.select("usagi")
    restored = buddy.store.load_settings()
    assert restored.character_name == (custom_name or "우사기")
    assert restored.character_id == restored.chat_character_id == "usagi"


def test_frame_delays_and_pack_replacement_use_active_frame(pack_controller):
    buddy, _ = pack_controller
    buddy.characters.select("chiikawa")
    buddy.animation.play("idle", force=True)
    assert buddy.animation.frame_delay_ms == 280
    buddy.pet._advance()
    assert buddy.animation.frame_delay_ms == 110
    assert buddy.pet.animation_timer.interval() == 110
    buddy.settings.update(animation_speed=150)
    assert buddy.pet.animation_timer.interval() == 73


def test_failed_selection_and_preparation_keep_previous_pack(pack_controller, monkeypatch):
    buddy, _ = pack_controller
    before = buddy.animation.clips
    original = buddy.characters.catalog.load

    def reject(key):
        if key == "usagi":
            raise AssetError("손상된 이미지")
        return original(key)

    monkeypatch.setattr(buddy.characters.catalog, "load", reject)
    with pytest.raises(AssetError):
        buddy.characters.select("usagi")
    assert buddy.animation.clips is before and buddy.characters.active_id == "moru"
    monkeypatch.setattr(buddy.characters.catalog, "load", original)
    monkeypatch.setattr(
        buddy.store,
        "save_settings",
        lambda *args: (_ for _ in ()).throw(sqlite3.OperationalError("full")),
    )
    assert not buddy.characters.select("usagi")
    assert buddy.animation.clips is before and buddy.characters.active_id == "moru"


def test_first_picker_selects_three_and_persists(pack_controller, qapp):
    buddy, _ = pack_controller
    buddy.settings.update(character_selection_done=False)
    buddy._show_character_picker()
    qapp.processEvents()
    assert buddy.picker.isVisible() and set(buddy.picker.page.buttons) == {
        "chiikawa",
        "hachiware",
        "usagi",
    }
    buddy.picker.page.buttons["hachiware"].click()
    qapp.processEvents()
    assert not buddy.picker.isVisible() and buddy.settings.current.character_selection_done
    assert buddy.characters.active_id == "hachiware"


def test_new_install_automatically_offers_selection_and_restores_on_restart(qapp, tmp_path):
    for first_run in (True, False):
        guard = SingleInstance(tmp_path)
        assert guard.acquire()
        buddy = BuddyApplication(qapp, Store(tmp_path / "buddy.db"), guard, tmp_path)
        try:
            qapp.processEvents()
            if first_run:
                assert buddy.picker is not None and buddy.picker.isVisible()
                buddy.picker.page.buttons["chiikawa"].click()
            else:
                assert buddy.picker is None
                assert buddy.characters.active_id == "chiikawa"
                assert buddy.settings.current.chat_character_id == "chiikawa"
        finally:
            buddy.shutdown()
            buddy.pet.deleteLater()
            buddy.mini_timer.deleteLater()
            buddy.manager.deleteLater()
            qapp.processEvents()


def test_picker_can_cancel_without_initializing_data(pack_controller, qapp):
    buddy, _ = pack_controller
    buddy.settings.update(character_selection_done=False)
    buddy._show_character_picker()
    buddy.picker.reject()
    assert not buddy.settings.current.character_selection_done
    assert buddy.characters.active_id == "moru"


def test_missing_saved_pack_recovers_to_moru(qapp, tmp_path):
    store = Store(tmp_path / "buddy.db")
    settings = SettingsService(store)
    settings.update(character_id="usagi", chat_character_id="usagi")

    class MissingCatalog(CharacterCatalog):
        def load(self, key):
            if key == "usagi":
                raise AssetError("missing")
            return super().load(key)

    service = CharacterService(settings, MissingCatalog())
    assert service.active_id == "moru" and service.warning
    assert settings.current.character_id == "moru"
    store.close()


def test_presets_ring_and_quick_menu_share_timer_service(pack_controller, qapp):
    buddy, clock = pack_controller
    page = buddy.manager.focus_page
    page.presets[2].click()
    assert page.minutes.value() == 30 and buddy.focus_timer.status == "idle"
    buddy.settings.update(mini_timer_style="ring", mini_timer_mode="always")
    buddy.find_pet()
    qapp.processEvents()
    assert buddy.mini_timer.width() == 124 and buddy.mini_timer.isVisible()
    menu = buddy.pet.create_context_menu()
    quick = next(action.menu() for action in menu.actions() if action.text() == "집중 바로 시작")
    quick.actions()[0].trigger()
    assert buddy.focus_timer.planned == 15 * 60 and buddy.focus_timer.status == "running"
    assert not page.presets[0].isEnabled()
    second = buddy.pet.create_context_menu()
    quick = next(action.menu() for action in second.actions() if action.text() == "집중 바로 시작")
    assert all(not action.isEnabled() for action in quick.actions())
    next(action for action in second.actions() if action.text() == "일시정지").trigger()
    assert buddy.focus_timer.status == "paused"
    buddy.settings.update(mini_timer_style="pill")
    assert buddy.mini_timer.width() != 124
    menu.deleteLater()
    second.deleteLater()
