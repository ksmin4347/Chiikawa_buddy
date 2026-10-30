import json

import pytest

from desktop_buddy.characters.animation import AnimationState, load_clips
from desktop_buddy.core.paths import asset_directory


def test_original_assets_and_one_shot_return(qapp):
    clips = load_clips(asset_directory() / "default_character")
    assert set(clips) == {"idle", "happy", "focus", "break", "complete", "worried", "sad", "sleep"}
    assert len(clips["idle"].frames) == 8
    for clip in clips.values():
        assert all(frame.hasAlphaChannel() for frame in clip.frames)
    animation = AnimationState(clips)
    animation.play("happy")
    for _ in range(len(clips["happy"].frames)):
        animation.advance()
    assert animation.state == "idle"
    animation.play("missing")
    assert animation.state == "idle"
    for _ in range(10):
        animation.advance()
    assert animation.index == 2


def test_missing_and_broken_manifest_fallback(qapp, tmp_path):
    assert not load_clips(tmp_path)["idle"].frames[0].isNull()
    (tmp_path / "manifest.json").write_text("not json")
    assert len(load_clips(tmp_path)["idle"].frames) == 1


def test_single_frame_and_missing_image(qapp, tmp_path):
    frame = load_clips(tmp_path)["idle"].frames[0]
    frame.save(str(tmp_path / "one.png"))
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {
                "states": {
                    "idle": {
                        "frames": ["missing.png", "one.png"],
                        "fps": 99,
                        "loop": True,
                    }
                }
            }
        )
    )
    clip = load_clips(tmp_path)["idle"]
    assert len(clip.frames) == 1
    assert clip.fps == 30


@pytest.mark.parametrize(
    "manifest", [[], {"states": []}, {"states": None}, {"states": {"idle": None}}]
)
def test_malformed_manifest_types_use_fallback(qapp, tmp_path, manifest):
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    assert not load_clips(tmp_path)["idle"].frames[0].isNull()


def test_manifest_cannot_escape_asset_root(qapp, tmp_path):
    outside = load_clips(tmp_path)["idle"].frames[0]
    outside.save(str(tmp_path / "outside.png"))
    root = tmp_path / "character"
    root.mkdir()
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "states": {
                    "happy": {
                        "frames": ["../outside.png"],
                        "fps": 8,
                        "loop": False,
                    }
                }
            }
        )
    )
    assert "happy" not in load_clips(root)
