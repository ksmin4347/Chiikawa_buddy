import re
from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from dateutil.tz import datetime_exists
from PySide6.QtCore import QObject, Signal

from desktop_buddy.calendar.recurrence import (
    end_before,
    remaining_rule,
    starts_between,
    validate_rule,
)
from desktop_buddy.database.planning_repository import PlanningRepository
from desktop_buddy.models.planning import (
    CalendarEvent,
    Category,
    Kind,
    Occurrence,
    Record,
    Reminder,
    Scope,
    Task,
    aware,
    instant,
)


class PlanningService(QObject):
    changed = Signal()
    task_completed = Signal()

    def __init__(self, store, timezone: str = "Asia/Seoul"):
        super().__init__()
        self.store = store
        self.repository = PlanningRepository(store.connection)
        self.zone = ZoneInfo(timezone)

    def today(self) -> date:
        return datetime.now(self.zone).date()

    def categories(self) -> list[Category]:
        return self.repository.categories()

    def save_category(self, name: str, color: str, item_id: int | None = None) -> int:
        name = name.strip()
        if not 1 <= len(name) <= 30 or not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
            raise ValueError("카테고리 이름(1~30자)과 색상을 확인해 주세요.")
        with self.store.connection:
            result = self.repository.save_category(name, color, item_id)
        self.changed.emit()
        return result

    def delete_category(self, item_id: int) -> None:
        with self.store.connection:
            self.repository.delete_category(item_id)
        self.changed.emit()

    def validate(self, record: Record) -> Record:
        title = record.title.strip()
        if not 1 <= len(title) <= 200 or len(record.description) > 4000:
            raise ValueError("제목은 1~200자, 메모는 4,000자 이내로 입력해 주세요.")
        ZoneInfo(record.timezone)
        if not datetime_exists(record.start):
            raise ValueError("이 시간대에서 존재하지 않는 시각이에요. 다른 시간을 선택해 주세요.")
        if record.category_id is not None and record.category_id not in {
            c.id for c in self.categories()
        }:
            raise ValueError("카테고리를 다시 선택해 주세요.")
        if record.reminder_minutes is not None and not 0 <= record.reminder_minutes <= 10080:
            raise ValueError("알림은 0분~7일 전으로 설정해 주세요.")
        if isinstance(record, Task):
            if record.priority not in (0, 1, 2):
                raise ValueError("우선순위를 확인해 주세요.")
            if record.reminder_minutes is not None and record.due_at is None:
                raise ValueError("할 일 알림을 사용하려면 마감 시각을 입력해 주세요.")
        else:
            if not record.start < record.end or record.end - record.start > timedelta(days=366):
                raise ValueError("종료는 시작 이후여야 하고 한 일정의 길이는 366일 이내여야 해요.")
            if record.all_day and (record.start.time() != time() or record.end.time() != time()):
                raise ValueError("종일 일정은 날짜의 시작부터 다음 날짜 시작까지 지정해 주세요.")
        return replace(
            record, title=title, recurrence=validate_rule(record.recurrence, record.start)
        )

    def save(self, record: Record) -> int:
        record = self.validate(record)
        with self.store.connection:
            item_id = self.repository.save(record)
        self.changed.emit()
        return item_id

    def _occurrence(
        self,
        kind: Kind,
        root: Record,
        anchor: datetime,
        override: dict | None,
        completions: dict,
        categories: dict,
    ) -> Occurrence:
        key = anchor.date().isoformat()
        if override:
            payload = dict(override, id=root.id, recurrence=root.recurrence)
            record = (
                Task.from_payload(payload)
                if kind == "task"
                else CalendarEvent.from_payload(payload)
            )
            start = record.start
        elif isinstance(root, Task):
            due = anchor + (aware(root.due_at, root.timezone) - root.start) if root.due_at else None
            record = replace(root, scheduled_date=anchor.date(), due_at=due)
            start = anchor
        else:
            record = replace(root, start_at=anchor, end_at=anchor + (root.end - root.start))
            start = anchor
        end = record.end if isinstance(record, CalendarEvent) else start + timedelta(minutes=30)
        completed = (
            bool(completions.get(key, False))
            if root.recurrence
            else getattr(root, "completed", False)
        )
        return Occurrence(
            kind,
            root.id,
            key,
            record,
            start.astimezone(self.zone),
            end.astimezone(self.zone),
            categories.get(record.category_id),
            completed,
        )

    def _expand(
        self, kind: Kind, root: Record, lower: datetime, upper: datetime
    ) -> list[Occurrence]:
        categories = {value.id: value for value in self.categories()}
        exceptions = self.repository.exceptions(kind, root.id)
        completions = self.repository.completions(root.id) if kind == "task" else {}
        span = root.end - root.start if isinstance(root, CalendarEvent) else timedelta()
        anchors = starts_between(
            root.recurrence, root.start, lower - span - timedelta(days=2), upper + timedelta(days=2)
        )
        generated = set()
        result = []

        def include(occurrence):
            if kind == "task":
                return lower.date() <= occurrence.start.date() < upper.date()
            return occurrence.start < upper and occurrence.end > lower

        for anchor in anchors:
            key = anchor.date().isoformat()
            generated.add(key)
            cancelled, override = exceptions.get(key, (False, None))
            if not cancelled:
                occurrence = self._occurrence(kind, root, anchor, override, completions, categories)
                if include(occurrence):
                    result.append(occurrence)
        # A single edited instance may move into this range from another month.
        for key, (cancelled, override) in exceptions.items():
            if key not in generated and not cancelled and override:
                anchor = datetime.combine(date.fromisoformat(key), root.start.timetz())
                occurrence = self._occurrence(kind, root, anchor, override, completions, categories)
                if include(occurrence):
                    result.append(occurrence)
        return result

    def occurrences(self, start: date, end: date, kind: Kind | None = None) -> list[Occurrence]:
        if not 0 < (end - start).days <= 366:
            raise ValueError("한 번에 조회할 날짜 범위는 1~366일이에요.")
        lower = datetime.combine(start, time(), self.zone)
        upper = datetime.combine(end, time(), self.zone)
        result = []
        for record_kind in ("task", "event") if kind is None else (kind,):
            for record in self.repository.records(record_kind):
                result.extend(self._expand(record_kind, record, lower, upper))
        return sorted(
            result,
            key=lambda o: (
                o.start,
                not o.all_day,
                -(o.record.priority if isinstance(o.record, Task) else 1),
                o.item_id,
            ),
        )

    def overdue_tasks(self, before: date) -> list[Occurrence]:
        records = self.repository.records("task")
        if not records:
            return []
        original_dates = [record.scheduled_date for record in records]
        for record in records:
            for cancelled, override in self.repository.exceptions("task", record.id).values():
                if not cancelled and override:
                    original_dates.append(date.fromisoformat(override["scheduled_date"]))
        earliest = min(original_dates)
        result = []
        cursor = earliest
        while cursor < before:
            end = min(cursor + timedelta(days=366), before)
            result.extend(
                value for value in self.occurrences(cursor, end, "task") if not value.completed
            )
            cursor = end
        return sorted(result, key=lambda o: o.start, reverse=True)

    def set_completed(self, occurrence: Occurrence, completed: bool) -> None:
        root = self.repository.get("task", occurrence.item_id)
        with self.store.connection:
            if root.recurrence:
                self.repository.complete(root.id, occurrence.key, completed)
            else:
                self.repository.save(replace(root, completed=completed))
        self.changed.emit()
        if completed:
            self.task_completed.emit()

    def draft(self, occurrence: Occurrence, scope: Scope) -> Record:
        root = self.repository.get(occurrence.kind, occurrence.item_id)
        if scope == "all":
            return root
        rule = (
            remaining_rule(root.recurrence, root.start, date.fromisoformat(occurrence.key))
            if scope == "following" and root.recurrence
            else None
        )
        return replace(occurrence.record, recurrence=rule)

    def _detach_metadata(
        self, kind: Kind, owner_id: int, source: Record, replacement: Record
    ) -> Record:
        """When repetition stops, preserve explicit overrides and completed days as one-offs."""
        exceptions = self.repository.exceptions(kind, owner_id)
        completions = self.repository.completions(owner_id) if kind == "task" else {}
        categories = {category.id: category for category in self.categories()}
        base_key = replacement.start.date().isoformat()
        for key in exceptions.keys() | completions.keys():
            cancelled, override = exceptions.get(key, (False, None))
            if key == base_key or cancelled or (not override and not completions.get(key)):
                continue
            anchor = datetime.combine(date.fromisoformat(key), source.start.timetz())
            value = self._occurrence(kind, source, anchor, override, completions, categories)
            detached = replace(value.record, id=None, recurrence=None)
            if isinstance(detached, Task):
                detached = replace(detached, completed=value.completed)
            self.repository.save(detached)
        self.repository.remove_future_metadata(kind, owner_id, "0001-01-01")
        if isinstance(replacement, Task):
            replacement = replace(
                replacement, completed=bool(completions.get(base_key, replacement.completed))
            )
        return replacement

    def edit(self, occurrence: Occurrence, record: Record, scope: Scope = "one") -> int:
        root = self.repository.get(occurrence.kind, occurrence.item_id)
        if type(record) is not type(root):
            raise ValueError("할 일과 일정의 종류는 바꿀 수 없어요.")
        record = self.validate(record)
        with self.store.connection:
            if not root.recurrence or scope == "all":
                if root.recurrence and not record.recurrence:
                    record = self._detach_metadata(occurrence.kind, root.id, root, record)
                item_id = self.repository.save(replace(record, id=root.id))
            elif scope == "one":
                self.repository.save_exception(occurrence.kind, root.id, occurrence.key, record)
                item_id = root.id
            elif scope == "following":
                cutoff = date.fromisoformat(occurrence.key)
                if cutoff <= root.start.date():
                    if not record.recurrence:
                        record = self._detach_metadata(occurrence.kind, root.id, root, record)
                    item_id = self.repository.save(replace(record, id=root.id))
                else:
                    rule = end_before(root.recurrence, root.start, cutoff)
                    self.repository.save(replace(root, recurrence=rule))
                    item_id = self.repository.save(replace(record, id=None))
                    self.repository.move_future_metadata(
                        occurrence.kind, root.id, item_id, occurrence.key
                    )
                    self.repository.copy_future_notifications(
                        occurrence.kind, root.id, item_id, occurrence.key
                    )
                    if not record.recurrence:
                        record = self._detach_metadata(occurrence.kind, item_id, root, record)
                        self.repository.save(replace(record, id=item_id))
            else:
                raise ValueError("변경 범위를 확인해 주세요.")
        self.changed.emit()
        return item_id

    def delete(self, occurrence: Occurrence, scope: Scope = "one") -> None:
        root = self.repository.get(occurrence.kind, occurrence.item_id)
        with self.store.connection:
            if (
                not root.recurrence
                or scope == "all"
                or (scope == "following" and occurrence.key <= root.start.date().isoformat())
            ):
                self.repository.delete(occurrence.kind, root.id)
            elif scope == "one":
                self.repository.save_exception(occurrence.kind, root.id, occurrence.key, None)
            elif scope == "following":
                self.repository.save(
                    replace(
                        root,
                        recurrence=end_before(
                            root.recurrence, root.start, date.fromisoformat(occurrence.key)
                        ),
                    )
                )
                self.repository.remove_future_metadata(occurrence.kind, root.id, occurrence.key)
            else:
                raise ValueError("삭제 범위를 확인해 주세요.")
        self.changed.emit()

    def reminders_between(self, lower: datetime, upper: datetime) -> list[Reminder]:
        result = []
        categories = {category.id: category for category in self.categories()}
        for kind in ("task", "event"):
            for root in self.repository.records(kind):
                exceptions = self.repository.exceptions(kind, root.id)
                completions = self.repository.completions(root.id) if kind == "task" else {}
                shift = (
                    aware(root.due_at, root.timezone) - root.start
                    if isinstance(root, Task) and root.due_at
                    else timedelta()
                )
                lead = timedelta(minutes=root.reminder_minutes or 0)
                zone = root.start.tzinfo
                lower_anchor = lower.astimezone(zone) - shift + lead - timedelta(days=2)
                upper_anchor = upper.astimezone(zone) - shift + lead + timedelta(days=2)
                anchors = starts_between(root.recurrence, root.start, lower_anchor, upper_anchor)
                keyed = {anchor.date().isoformat(): anchor for anchor in anchors}
                # Overrides may move a deadline arbitrarily far from its original date.
                for key, (cancelled, override) in exceptions.items():
                    if not cancelled and override:
                        keyed.setdefault(
                            key, datetime.combine(date.fromisoformat(key), root.start.timetz())
                        )
                for key, anchor in keyed.items():
                    cancelled, override = exceptions.get(key, (False, None))
                    if cancelled:
                        continue
                    occurrence = self._occurrence(
                        kind, root, anchor, override, completions, categories
                    )
                    record = occurrence.record
                    if record.reminder_minutes is None or occurrence.completed:
                        continue
                    if isinstance(record, Task):
                        if record.due_at is None:
                            continue
                        target = aware(record.due_at, record.timezone)
                    else:
                        target = occurrence.start
                    trigger = target - timedelta(minutes=record.reminder_minutes)
                    if lower <= trigger <= upper:
                        notification_key = f"{kind}:{root.id}:{key}:{instant(trigger)}"
                        result.append(
                            Reminder(notification_key, occurrence, trigger.astimezone(UTC))
                        )
        return sorted(result, key=lambda item: item.trigger_at)
