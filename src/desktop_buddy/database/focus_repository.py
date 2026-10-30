import json
from datetime import datetime

from desktop_buddy.models.focus import stamp


class FocusRepository:
    def __init__(self, connection):
        self.connection = connection

    @staticmethod
    def _dict(cursor, row):
        return dict(zip([column[0] for column in cursor.description], row, strict=True))

    def session(self, item_id: int) -> dict:
        cursor = self.connection.execute("SELECT * FROM focus_sessions WHERE id=?", (item_id,))
        row = cursor.fetchone()
        if row is None:
            raise LookupError("집중 기록을 찾을 수 없어요.")
        return self._dict(cursor, row)

    def create(self, kind, seconds, now, category, task_id, task_key, task_title) -> int:
        category_id, name, color = category
        cursor = self.connection.execute(
            "INSERT INTO focus_sessions(kind,planned_seconds,started_at,category_id,category_name,"
            "category_color,task_id,task_key,task_title) VALUES (?,?,?,?,?,?,?,?,?)",
            (kind, seconds, stamp(now), category_id, name, color, task_id, task_key, task_title),
        )
        return cursor.lastrowid

    def progress(self, item_id: int, active: float, paused: float) -> None:
        self.connection.execute(
            "UPDATE focus_sessions SET active_seconds=?,paused_seconds=? WHERE id=?",
            (active, paused, item_id),
        )

    def finish(self, item_id, now, completed, reason):
        self.connection.execute(
            "UPDATE focus_sessions SET ended_at=?,completed=?,interrupted=?,exit_reason=? "
            "WHERE id=?",
            (stamp(now), completed, not completed, reason, item_id),
        )

    def segment(self, segment_id, session_id, start, end, seconds) -> int:
        if segment_id is None:
            return self.connection.execute(
                "INSERT INTO focus_segments(session_id,started_at,ended_at,elapsed_seconds) "
                "VALUES (?,?,?,?)",
                (session_id, stamp(start), stamp(end), seconds),
            ).lastrowid
        self.connection.execute(
            "UPDATE focus_segments SET ended_at=?,elapsed_seconds=? WHERE id=?",
            (stamp(end), seconds, segment_id),
        )
        return segment_id

    def load_state(self) -> dict:
        row = self.connection.execute(
            "SELECT payload FROM timer_state WHERE singleton=1"
        ).fetchone()
        if row is None:
            return {}
        try:
            value = json.loads(row[0])
            return value if isinstance(value, dict) else {}
        except (ValueError, TypeError):
            return {}

    def save_state(self, state: dict):
        self.connection.execute(
            "INSERT INTO timer_state VALUES (1,?) "
            "ON CONFLICT(singleton) DO UPDATE SET payload=excluded.payload",
            (json.dumps(state, ensure_ascii=False),),
        )

    def open_sessions(self):
        cursor = self.connection.execute(
            "SELECT * FROM focus_sessions WHERE ended_at IS NULL ORDER BY id"
        )
        return [self._dict(cursor, row) for row in cursor]

    def segments_between(self, lower: datetime, upper: datetime):
        cursor = self.connection.execute(
            "SELECT g.*,s.category_id,s.category_name,s.category_color,"
            "s.task_id,s.task_key,s.task_title "
            "FROM focus_segments g JOIN focus_sessions s ON s.id=g.session_id "
            "WHERE s.kind='focus' AND g.ended_at>? AND g.started_at<? ORDER BY g.started_at,g.id",
            (stamp(lower), stamp(upper)),
        )
        return [self._dict(cursor, row) for row in cursor]

    def recent(self, lower: datetime, upper: datetime, limit: int = 100):
        cursor = self.connection.execute(
            "SELECT * FROM focus_sessions WHERE kind='focus' AND started_at<? "
            "AND (ended_at IS NULL OR ended_at>=?) ORDER BY started_at DESC,id DESC LIMIT ?",
            (stamp(upper), stamp(lower), limit),
        )
        return [self._dict(cursor, row) for row in cursor]

    def completed_count(self, lower: datetime, upper: datetime):
        return self.connection.execute(
            "SELECT COUNT(*) FROM focus_sessions WHERE kind='focus' "
            "AND completed=1 AND ended_at>=? AND ended_at<?",
            (stamp(lower), stamp(upper)),
        ).fetchone()[0]

    def completed_average(self, lower: datetime, upper: datetime) -> float:
        return self.connection.execute(
            "SELECT COALESCE(AVG(active_seconds),0) FROM focus_sessions WHERE kind='focus' "
            "AND completed=1 AND ended_at>=? AND ended_at<?",
            (stamp(lower), stamp(upper)),
        ).fetchone()[0]

    def all_total(self):
        return self.connection.execute(
            "SELECT COALESCE(SUM(g.elapsed_seconds),0) FROM focus_segments g "
            "JOIN focus_sessions s ON s.id=g.session_id WHERE s.kind='focus'"
        ).fetchone()[0]

    def delete(self, item_id):
        self.connection.execute("DELETE FROM focus_sessions WHERE id=?", (item_id,))

    def change_category(self, item_id, category):
        self.connection.execute(
            "UPDATE focus_sessions SET category_id=?,category_name=?,category_color=? WHERE id=?",
            (*category, item_id),
        )
