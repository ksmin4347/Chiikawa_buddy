import json
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import closing, contextmanager
from datetime import UTC, datetime
from pathlib import Path

from desktop_buddy.core.settings import Settings
from desktop_buddy.database.migrations import SCHEMA_VERSION, migrate


class Store:
    """One GUI-thread connection; never resets an unreadable user database."""

    def __init__(self, path: Path):
        self._depth = 0
        self._rollback_only = False
        self._signals: list[tuple] = []
        self._undo: list[Callable[[], None]] = []
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path, timeout=5)
        try:
            self.connection.execute("PRAGMA foreign_keys = ON")
            self.connection.execute("PRAGMA busy_timeout = 5000")
            version = self.connection.execute("PRAGMA user_version").fetchone()[0]
            if version > SCHEMA_VERSION:
                raise RuntimeError("더 새로운 버전에서 만든 데이터입니다. 앱을 업데이트해 주세요.")
            if version < SCHEMA_VERSION:
                if path.stat().st_size:
                    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
                    with closing(
                        sqlite3.connect(path.with_suffix(f".{stamp}.backup.db"))
                    ) as backup:
                        self.connection.backup(backup)
                with self.connection:
                    # An explicit BEGIN also makes SQLite DDL transactional.
                    self.connection.execute("BEGIN IMMEDIATE")
                    migrate(self.connection, version)
        except Exception:
            self.connection.close()
            raise

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """Nested services share one commit; failures also restore runtime state."""
        outer = self._depth == 0
        if outer:
            self.connection.execute("BEGIN IMMEDIATE")
            self._rollback_only = False
        self._depth += 1
        try:
            yield
            if outer:
                if self._rollback_only:
                    raise RuntimeError("중첩 작업이 실패해 저장을 취소했어요.")
                self.connection.commit()
        except BaseException:
            self._rollback_only = True
            if outer:
                self.connection.rollback()
                for undo in reversed(self._undo):
                    undo()
            raise
        finally:
            self._depth -= 1
            if outer:
                signals = self._signals if not self._rollback_only else []
                self._signals, self._undo = [], []
                for signal, args in signals:
                    signal.emit(*args)

    def emit_after_commit(self, signal, *args) -> None:
        if self._depth:
            self._signals.append((signal, args))
        else:
            signal.emit(*args)

    def on_rollback(self, callback: Callable[[], None]) -> None:
        if not self._depth:
            raise RuntimeError("복구 작업은 트랜잭션 안에서 등록해야 해요.")
        self._undo.append(callback)

    def load_settings(self) -> Settings:
        values = {}
        for key, value in self.connection.execute("SELECT * FROM app_settings"):
            try:
                values[key] = json.loads(value)
            except (ValueError, TypeError):
                continue
        return Settings.from_mapping(values)

    def save_settings(self, settings: Settings) -> None:
        rows = [
            (key, json.dumps(value, ensure_ascii=False))
            for key, value in settings.to_mapping().items()
        ]
        with self.transaction():
            self.connection.executemany(
                "INSERT INTO app_settings VALUES (?, ?) "
                "ON CONFLICT(setting_key) DO UPDATE SET setting_value = excluded.setting_value",
                rows,
            )

    def close(self) -> None:
        self.connection.close()
