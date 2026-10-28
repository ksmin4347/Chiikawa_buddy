import json
import sqlite3
from datetime import UTC, datetime

from desktop_buddy.models.planning import CalendarEvent, Category, Kind, Record, Task

TABLES = {"task": "tasks", "event": "calendar_events"}
OWNERS = {"task": "task_id", "event": "event_id"}


class PlanningRepository:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def categories(self) -> list[Category]:
        return [
            Category(*row)
            for row in self.connection.execute("SELECT id,name,color FROM categories ORDER BY id")
        ]

    def save_category(self, name: str, color: str, item_id: int | None = None) -> int:
        if item_id is None:
            return self.connection.execute(
                "INSERT INTO categories(name,color) VALUES (?,?)", (name, color)
            ).lastrowid
        cursor = self.connection.execute(
            "UPDATE categories SET name=?,color=? WHERE id=?", (name, color, item_id)
        )
        if not cursor.rowcount:
            raise LookupError("카테고리를 찾을 수 없어요.")
        return item_id

    def delete_category(self, item_id: int) -> None:
        self.connection.execute("DELETE FROM categories WHERE id=?", (item_id,))

    def records(self, kind: Kind) -> list[Record]:
        cursor = self.connection.execute(f"SELECT * FROM {TABLES[kind]} ORDER BY id")
        columns = [column[0] for column in cursor.description]
        result = []
        for row in cursor:
            data = dict(zip(columns, row, strict=True))
            data.pop("created_at")
            data.pop("updated_at")
            if kind == "task":
                data["completed"] = bool(data["completed"])
                result.append(Task.from_payload(data))
            else:
                data["all_day"] = bool(data["all_day"])
                result.append(CalendarEvent.from_payload(data))
        return result

    def get(self, kind: Kind, item_id: int) -> Record:
        for record in self.records(kind):
            if record.id == item_id:
                return record
        raise LookupError("항목을 찾을 수 없어요. 목록을 새로 열어 주세요.")

    def save(self, record: Record) -> int:
        table = TABLES["task" if isinstance(record, Task) else "event"]
        data = record.payload()
        item_id = data.pop("id")
        stamp = datetime.now(UTC).isoformat()
        data["updated_at"] = stamp
        if item_id is None:
            data["created_at"] = stamp
            keys = ",".join(data)
            placeholders = ",".join("?" for _ in data)
            return self.connection.execute(
                f"INSERT INTO {table}({keys}) VALUES ({placeholders})", tuple(data.values())
            ).lastrowid
        assignments = ",".join(f"{key}=?" for key in data)
        cursor = self.connection.execute(
            f"UPDATE {table} SET {assignments} WHERE id=?", (*data.values(), item_id)
        )
        if not cursor.rowcount:
            raise LookupError("항목을 찾을 수 없어요.")
        return item_id

    def delete(self, kind: Kind, item_id: int) -> None:
        self.connection.execute(f"DELETE FROM {TABLES[kind]} WHERE id=?", (item_id,))

    def exceptions(self, kind: Kind, item_id: int) -> dict[str, tuple[bool, dict | None]]:
        rows = self.connection.execute(
            "SELECT original_key,cancelled,overrides FROM recurrence_exceptions "
            f"WHERE {OWNERS[kind]}=?",
            (item_id,),
        )
        return {
            key: (bool(cancelled), json.loads(payload) if payload else None)
            for key, cancelled, payload in rows
        }

    def save_exception(self, kind: Kind, item_id: int, key: str, record: Record | None) -> None:
        owner = OWNERS[kind]
        payload = json.dumps(record.payload(), ensure_ascii=False) if record else None
        self.connection.execute(
            f"INSERT INTO recurrence_exceptions({owner},original_key,cancelled,overrides) "
            "VALUES (?,?,?,?) "
            f"ON CONFLICT({owner},original_key) DO UPDATE SET "
            "cancelled=excluded.cancelled,overrides=excluded.overrides",
            (item_id, key, record is None, payload),
        )

    def completions(self, item_id: int) -> dict[str, bool]:
        return dict(
            self.connection.execute(
                "SELECT original_key,completed FROM task_completions WHERE task_id=?", (item_id,)
            )
        )

    def complete(self, item_id: int, key: str, completed: bool) -> None:
        self.connection.execute(
            "INSERT INTO task_completions VALUES (?,?,?) "
            "ON CONFLICT(task_id,original_key) DO UPDATE SET completed=excluded.completed",
            (item_id, key, completed),
        )

    def move_future_metadata(self, kind: Kind, old_id: int, new_id: int, cutoff: str) -> None:
        owner = OWNERS[kind]
        self.connection.execute(
            f"UPDATE recurrence_exceptions SET {owner}=? WHERE {owner}=? AND original_key>=?",
            (new_id, old_id, cutoff),
        )
        if kind == "task":
            self.connection.execute(
                "UPDATE task_completions SET task_id=? WHERE task_id=? AND original_key>=?",
                (new_id, old_id, cutoff),
            )

    def copy_future_notifications(self, kind: Kind, old_id: int, new_id: int, cutoff: str) -> None:
        prefix = f"{kind}:{old_id}:"
        rows = self.connection.execute(
            "SELECT notification_key,handled_at,status FROM notification_log "
            "WHERE notification_key LIKE ?",
            (prefix + "%",),
        ).fetchall()
        for key, handled_at, status in rows:
            _, _, original_day, trigger = key.split(":", 3)
            if original_day >= cutoff:
                self.connection.execute(
                    "INSERT OR IGNORE INTO notification_log VALUES (?,?,?)",
                    (f"{kind}:{new_id}:{original_day}:{trigger}", handled_at, status),
                )

    def remove_future_metadata(self, kind: Kind, item_id: int, cutoff: str) -> None:
        self.connection.execute(
            f"DELETE FROM recurrence_exceptions WHERE {OWNERS[kind]}=? AND original_key>=?",
            (item_id, cutoff),
        )
        if kind == "task":
            self.connection.execute(
                "DELETE FROM task_completions WHERE task_id=? AND original_key>=?",
                (item_id, cutoff),
            )

    def claim_notification(self, key: str, stamp: str, status: str) -> bool:
        return (
            self.connection.execute(
                "INSERT OR IGNORE INTO notification_log VALUES (?,?,?)", (key, stamp, status)
            ).rowcount
            == 1
        )
