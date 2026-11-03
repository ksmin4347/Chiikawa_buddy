from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from desktop_buddy.characters.animation import AssetError, Clip, load_clips
from desktop_buddy.characters.dialogue_profiles import PROFILE_IDS, profile
from desktop_buddy.core.paths import asset_directory


class CharacterCatalog:
    def __init__(self, assets: Path | None = None):
        self.assets = assets or asset_directory()

    def load(self, character_id: str) -> dict[str, Clip]:
        if character_id not in PROFILE_IDS:
            raise AssetError("캐릭터를 다시 선택해 주세요.")
        root = self.assets / (
            "default_character" if character_id == "moru" else f"character_packs/{character_id}"
        )
        return load_clips(root, strict=character_id != "moru", expected_id=character_id)


class CharacterService(QObject):
    changed = Signal(object, object)

    def __init__(self, settings, catalog: CharacterCatalog | None = None):
        super().__init__()
        self.settings = settings
        self.catalog = catalog or CharacterCatalog()
        self.prepare: Callable[[dict[str, Clip]], object] = lambda clips: None
        self.warning = ""
        self._changing = False
        self.active_id = settings.current.character_id
        try:
            self.clips = self.catalog.load(self.active_id)
        except AssetError:
            self.active_id = "moru"
            self.clips = self.catalog.load("moru")
            self.warning = "선택한 캐릭터 자료를 읽지 못해 기본 캐릭터로 복구했어요."
            settings.update(character_id="moru", chat_character_id="moru")

    def _selection(self, character_id: str) -> dict:
        name = self.settings.current.character_name
        if name == profile(self.active_id).name:
            name = profile(character_id).name
        return {
            "character_id": character_id,
            "chat_character_id": character_id,
            "character_selection_done": True,
            "character_name": name,
        }

    def select(self, character_id: str) -> bool:
        if self._changing:
            raise ValueError("캐릭터 전환 중이에요. 잠시 후 다시 선택해 주세요.")
        if character_id == self.active_id:
            return self.settings.update(**self._selection(character_id))
        self._changing = True
        try:
            clips = self.catalog.load(character_id)
            prepared = self.prepare(clips)
            if not self.settings.update(**self._selection(character_id)):
                return False
            self.active_id, self.clips = character_id, clips
            self.changed.emit(clips, prepared)
            return True
        finally:
            self._changing = False
