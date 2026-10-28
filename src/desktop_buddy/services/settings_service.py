from dataclasses import replace

from PySide6.QtCore import QObject, Signal

from desktop_buddy.core.settings import Settings
from desktop_buddy.database.store import Store


class SettingsService(QObject):
    changed = Signal(object)
    save_failed = Signal(str)

    def __init__(self, store: Store):
        super().__init__()
        self.store = store
        self.current = store.load_settings()

    def update(self, **changes) -> bool:
        candidate = Settings.from_mapping(replace(self.current, **changes).to_mapping())
        if candidate == self.current:
            return True
        try:
            self.store.save_settings(candidate)
        except Exception:
            # Do not include database content or possible future secrets in messages.
            self.save_failed.emit(
                "설정을 저장하지 못했어요. 저장 공간과 폴더 쓰기 권한을 확인해 주세요."
            )
            return False
        self.current = candidate
        self.changed.emit(candidate)
        return True
