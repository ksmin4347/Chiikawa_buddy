import sqlite3
from dataclasses import replace

import pytest
from PySide6.QtTest import QSignalSpy

from desktop_buddy.core.settings import Settings
from desktop_buddy.database.store import SCHEMA_VERSION, Store
from desktop_buddy.services.settings_service import SettingsService


def test_settings_survive_restart(tmp_path):
    path = tmp_path / "buddy.db"
    store = Store(path)
    expected = replace(Settings(), character_name="새 친구", x=-730, y=90, size=240, theme="dark")
    store.save_settings(expected)
    store.close()
    reopened = Store(path)
    assert reopened.load_settings() == expected
    assert reopened.connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    reopened.close()


def test_invalid_and_unknown_settings_are_safe(tmp_path):
    store = Store(tmp_path / "buddy.db")
    with store.connection:
        store.connection.executemany(
            "INSERT INTO app_settings VALUES (?, ?)",
            [
                ("size", "-80"),
                ("character_name", '"   "'),
                ("x", "true"),
                ("always_on_top", '"false"'),
                ("theme", '"invalid"'),
                ("animation_speed", "{broken"),
                ("future_field", "123"),
            ],
        )
    settings = store.load_settings()
    assert settings.size == 96
    assert settings.character_name == "모루"
    assert settings.x is None
    assert settings.always_on_top is True
    assert settings.theme == "light"
    assert settings.animation_speed == 100
    store.close()


def test_newer_schema_is_never_overwritten(tmp_path):
    path = tmp_path / "buddy.db"
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA user_version = 999")
    connection.close()
    original = path.read_bytes()
    with pytest.raises(RuntimeError, match="새로운 버전"):
        Store(path)
    assert path.read_bytes() == original


def test_corrupt_db_is_preserved(tmp_path):
    path = tmp_path / "buddy.db"
    path.write_bytes(b"this is not sqlite")
    with pytest.raises(sqlite3.DatabaseError):
        Store(path)
    assert path.read_bytes() == b"this is not sqlite"


def test_migration_backs_up_existing_database(tmp_path):
    path = tmp_path / "buddy.db"
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE user_notes (body TEXT)")
    connection.execute("INSERT INTO user_notes VALUES ('preserve me')")
    connection.commit()
    connection.close()
    store = Store(path)
    assert store.connection.execute("SELECT body FROM user_notes").fetchone()[0] == "preserve me"
    backups = list(tmp_path.glob("*.backup.db"))
    assert len(backups) == 1
    backup = sqlite3.connect(backups[0])
    assert backup.execute("SELECT body FROM user_notes").fetchone()[0] == "preserve me"
    backup.close()
    store.close()


def test_failed_save_does_not_change_live_settings(qapp, tmp_path, monkeypatch):
    store = Store(tmp_path / "buddy.db")
    service = SettingsService(store)
    errors = QSignalSpy(service.save_failed)
    changes = QSignalSpy(service.changed)

    def fail(_settings):
        raise sqlite3.OperationalError("disk full")

    monkeypatch.setattr(store, "save_settings", fail)
    assert not service.update(size=240)
    assert service.current.size == 176
    assert changes.count() == 0
    assert errors.count() == 1
    store.close()


@pytest.mark.parametrize(
    "values",
    [
        {"size": True},
        {"animation_speed": "100"},
        {"character_name": None},
        {"theme": []},
        {"theme": {}},
        {"reduce_motion": 1},
    ],
)
def test_untrusted_setting_types_do_not_crash(values):
    assert isinstance(Settings.from_mapping(values), Settings)
