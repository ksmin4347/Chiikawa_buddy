from collections import defaultdict
from datetime import UTC, date, datetime, time, timedelta

from PySide6.QtCore import QObject, Signal

from desktop_buddy.database.focus_repository import FocusRepository
from desktop_buddy.database.store import Store
from desktop_buddy.services.focus_timer import FocusTimerService
from desktop_buddy.services.planning_service import PlanningService


def split_segment(start: datetime, end: datetime, seconds: float, zone) -> dict[date, float]:
    """Allocate monotonic seconds proportionally across actual local midnight boundaries."""
    start, end = start.astimezone(UTC), end.astimezone(UTC)
    if end <= start or seconds <= 0:
        return {}
    span = (end - start).total_seconds()
    result = {}
    cursor = start
    while cursor < end:
        day = cursor.astimezone(zone).date()
        midnight = datetime.combine(day + timedelta(days=1), time(), zone).astimezone(UTC)
        boundary = min(end, midnight)
        if boundary <= cursor:
            break
        result[day] = result.get(day, 0) + seconds * (boundary - cursor).total_seconds() / span
        cursor = boundary
    return result


class StudyStatistics(QObject):
    changed = Signal()

    def __init__(self, store: Store, planning: PlanningService, timer: FocusTimerService) -> None:
        super().__init__()
        self.store, self.planning, self.timer = store, planning, timer
        self.repository = FocusRepository(store.connection)
        self.zone = planning.zone
        timer.records_changed.connect(self.changed)

    def totals(self, start: date, end: date) -> dict:
        lower = datetime.combine(start, time(), self.zone)
        upper = datetime.combine(end, time(), self.zone)
        daily = defaultdict(float)
        categories = defaultdict(float)
        tasks = defaultdict(float)
        category_colors = {}
        current_categories = {value.id: value for value in self.planning.categories()}
        for segment in self.repository.segments_between(lower, upper):
            allocations = split_segment(
                datetime.fromisoformat(segment["started_at"]),
                datetime.fromisoformat(segment["ended_at"]),
                segment["elapsed_seconds"],
                self.zone,
            )
            seconds = sum(value for day, value in allocations.items() if start <= day < end)
            for day, value in allocations.items():
                if start <= day < end:
                    daily[day] += value
            category = current_categories.get(segment["category_id"])
            category_name = category.name if category else segment["category_name"]
            category_colors[category_name] = (
                category.color if category else segment["category_color"]
            )
            categories[category_name] += seconds
            tasks[segment["task_title"] or "연결 없는 집중"] += seconds
        count = self.repository.completed_count(lower, upper)
        recent = self.repository.recent(lower, upper)
        return {
            "seconds": sum(daily.values()),
            "daily": dict(daily),
            "categories": dict(categories),
            "colors": category_colors,
            "tasks": dict(tasks),
            "completed": count,
            "average": self.repository.completed_average(lower, upper),
            "records": recent,
        }

    def all_total(self) -> float:
        return self.repository.all_total()

    def last_focus_date(self) -> date | None:
        row = self.store.connection.execute(
            "SELECT MAX(g.ended_at) FROM focus_segments g "
            "JOIN focus_sessions s ON s.id=g.session_id "
            "WHERE s.kind='focus' AND g.elapsed_seconds>0"
        ).fetchone()[0]
        return datetime.fromisoformat(row).astimezone(self.zone).date() if row else None

    def delete_record(self, item_id: int) -> None:
        row = self.repository.session(item_id)
        if row["ended_at"] is None or item_id == self.timer.session_id:
            raise ValueError("진행 중인 기록은 먼저 타이머를 중지한 뒤 삭제해 주세요.")
        with self.store.connection:
            self.repository.delete(item_id)
        self.changed.emit()

    def change_category(self, item_id: int, category_id: int | None) -> None:
        row = self.repository.session(item_id)
        if row["ended_at"] is None:
            raise ValueError("진행 중인 기록은 타이머를 중지한 뒤 변경해 주세요.")
        category = next(
            (value for value in self.planning.categories() if value.id == category_id), None
        )
        if category_id is not None and category is None:
            raise ValueError("분류를 다시 선택해 주세요.")
        values = (
            (category.id, category.name, category.color)
            if category
            else (None, "분류 없음", "#607d8b")
        )
        with self.store.connection:
            self.repository.change_category(item_id, values)
        self.changed.emit()
