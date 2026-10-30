import sqlite3
from datetime import date, datetime

from desktop_buddy.models.focus import stamp


class CompanionRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def periods(self) -> list[dict]:
        return [
            {
                "id": row[0],
                "start_date": date.fromisoformat(row[1]),
                "end_date": date.fromisoformat(row[2]),
            }
            for row in self.connection.execute(
                "SELECT id,start_date,end_date FROM rest_periods ORDER BY start_date,id"
            )
        ]

    def add_period(self, start: date, end: date) -> int:
        return self.connection.execute(
            "INSERT INTO rest_periods(start_date,end_date) VALUES (?,?)",
            (start.isoformat(), end.isoformat()),
        ).lastrowid

    def delete_period(self, item_id: int) -> None:
        self.connection.execute("DELETE FROM rest_periods WHERE id=?", (item_id,))

    def last_valid(self, seconds: float) -> datetime | None:
        row = self.connection.execute(
            "SELECT MAX(ended_at) FROM focus_sessions WHERE kind='focus' AND recorded=1 "
            "AND completed=1 AND active_seconds>=?",
            (seconds,),
        ).fetchone()[0]
        return datetime.fromisoformat(row) if row else None

    def clock_state(self) -> tuple[datetime | None, bool]:
        row = self.connection.execute(
            "SELECT last_seen_at,clock_warning FROM companion_state"
        ).fetchone()
        if row is None:
            return None, False
        try:
            value = datetime.fromisoformat(row[0])
            return (value, bool(row[1])) if value.tzinfo else (None, True)
        except ValueError:
            return None, True

    def save_clock(self, now: datetime, warning: bool) -> None:
        self.connection.execute(
            "INSERT INTO companion_state VALUES (1,?,?) ON CONFLICT(singleton) "
            "DO UPDATE SET last_seen_at=excluded.last_seen_at,"
            "clock_warning=excluded.clock_warning",
            (stamp(now), warning),
        )

    def last_message(self, kind: str) -> date | None:
        row = self.connection.execute(
            "SELECT MAX(local_date) FROM companion_messages WHERE kind=?", (kind,)
        ).fetchone()[0]
        return date.fromisoformat(row) if row else None

    def claim_message(self, kind: str, day: date) -> bool:
        return (
            self.connection.execute(
                "INSERT OR IGNORE INTO companion_messages VALUES (?,?)", (kind, day.isoformat())
            ).rowcount
            == 1
        )
