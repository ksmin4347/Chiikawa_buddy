from datetime import UTC, datetime
from uuid import uuid4

from desktop_buddy.characters.dialogue_profiles import PROFILE_VERSION
from desktop_buddy.database.store import Store


class ChatRepository:
    def __init__(self, store: Store):
        self.store = store
        self.connection = store.connection

    def sessions(self) -> list[tuple[str, str]]:
        return self.connection.execute(
            "SELECT id,title FROM chat_sessions ORDER BY created_at DESC,id DESC LIMIT 50"
        ).fetchall()

    def create_session(self) -> str:
        session_id = str(uuid4())
        self.connection.execute(
            "INSERT INTO chat_sessions VALUES (?,?,?)",
            (session_id, datetime.now(UTC).isoformat(), "새 대화"),
        )
        return session_id

    def append(
        self,
        session_id: str,
        role: str,
        body: str,
        character_id: str = "moru",
        mode: str = "offline",
    ) -> int:
        cursor = self.connection.execute(
            "INSERT INTO chat_messages(session_id,role,body,created_at,"
            "character_id,profile_version,mode) "
            "VALUES (?,?,?,?,?,?,?)",
            (
                session_id,
                role,
                body,
                datetime.now(UTC).isoformat(),
                character_id,
                PROFILE_VERSION,
                mode,
            ),
        )
        if role == "user":
            self.connection.execute(
                "UPDATE chat_sessions SET title=? WHERE id=? AND "
                "(SELECT COUNT(*) FROM chat_messages WHERE session_id=? AND role='user')=1",
                (body[:40], session_id, session_id),
            )
        return cursor.lastrowid

    def messages(self, session_id: str, before_id: int | None = None) -> list[tuple]:
        rows = self.connection.execute(
            "SELECT id,role,body,created_at FROM chat_messages "
            "WHERE session_id=? AND id<? ORDER BY id DESC LIMIT 50",
            (session_id, before_id if before_id is not None else 9223372036854775807),
        ).fetchall()
        return list(reversed(rows))

    def speakers(self, session_id: str, message_ids: list[int]) -> dict[int, str]:
        if not message_ids:
            return {}
        return dict(
            self.connection.execute(
                "SELECT id,character_id FROM chat_messages "
                "WHERE session_id=? AND id BETWEEN ? AND ?",
                (session_id, min(message_ids), max(message_ids)),
            )
        )

    def delete(self, session_id: str | None = None) -> None:
        if session_id is None:
            self.connection.execute("DELETE FROM chat_sessions")
        else:
            self.connection.execute("DELETE FROM chat_sessions WHERE id=?", (session_id,))

    def modes(self, session_id: str, message_ids: list[int]) -> dict[int, str]:
        if not message_ids:
            return {}
        return dict(
            self.connection.execute(
                "SELECT id,mode FROM chat_messages WHERE session_id=? AND id BETWEEN ? AND ?",
                (session_id, min(message_ids), max(message_ids)),
            )
        )

    def completed(self, operation_id: str) -> bool:
        return (
            self.connection.execute(
                "SELECT 1 FROM command_operations WHERE operation_id=?", (operation_id,)
            ).fetchone()
            is not None
        )

    def complete(self, operation_id: str, kind: str) -> None:
        # Receipts intentionally contain no command body, item title, or API secret.
        self.connection.execute(
            "INSERT INTO command_operations VALUES (?,?,?)",
            (operation_id, kind, datetime.now(UTC).isoformat()),
        )
