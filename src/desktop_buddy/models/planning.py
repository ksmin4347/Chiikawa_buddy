from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

Kind = Literal["task", "event"]
Scope = Literal["one", "following", "all"]


def aware(value: datetime, timezone: str) -> datetime:
    zone = ZoneInfo(timezone)
    return value.replace(tzinfo=zone) if value.tzinfo is None else value.astimezone(zone)


def instant(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="seconds")


@dataclass(frozen=True)
class Category:
    id: int
    name: str
    color: str


@dataclass(frozen=True)
class Task:
    title: str
    scheduled_date: date
    id: int | None = None
    description: str = ""
    start_time: time | None = None
    due_at: datetime | None = None
    priority: int = 1
    category_id: int | None = None
    completed: bool = False
    recurrence: str | None = None
    reminder_minutes: int | None = None
    timezone: str = "Asia/Seoul"

    @property
    def start(self) -> datetime:
        return datetime.combine(
            self.scheduled_date, self.start_time or time(), ZoneInfo(self.timezone)
        )

    def payload(self) -> dict:
        values = asdict(self)
        values["scheduled_date"] = self.scheduled_date.isoformat()
        values["start_time"] = self.start_time.isoformat() if self.start_time else None
        values["due_at"] = instant(aware(self.due_at, self.timezone)) if self.due_at else None
        return values

    @classmethod
    def from_payload(cls, values: dict) -> "Task":
        data = dict(values)
        data["scheduled_date"] = date.fromisoformat(data["scheduled_date"])
        data["start_time"] = time.fromisoformat(data["start_time"]) if data["start_time"] else None
        data["due_at"] = datetime.fromisoformat(data["due_at"]) if data["due_at"] else None
        return cls(**data)


@dataclass(frozen=True)
class CalendarEvent:
    title: str
    start_at: datetime
    end_at: datetime
    id: int | None = None
    description: str = ""
    all_day: bool = False
    category_id: int | None = None
    recurrence: str | None = None
    reminder_minutes: int | None = None
    timezone: str = "Asia/Seoul"

    @property
    def start(self) -> datetime:
        return aware(self.start_at, self.timezone)

    @property
    def end(self) -> datetime:
        return aware(self.end_at, self.timezone)

    def payload(self) -> dict:
        values = asdict(self)
        values["start_at"] = instant(self.start)
        values["end_at"] = instant(self.end)
        return values

    @classmethod
    def from_payload(cls, values: dict) -> "CalendarEvent":
        data = dict(values)
        data["start_at"] = datetime.fromisoformat(data["start_at"])
        data["end_at"] = datetime.fromisoformat(data["end_at"])
        return cls(**data)


Record = Task | CalendarEvent


@dataclass(frozen=True)
class Occurrence:
    kind: Kind
    item_id: int
    key: str  # Original local recurrence date; stable when an instance is moved.
    record: Record
    start: datetime
    end: datetime
    category: Category | None
    completed: bool = False

    @property
    def title(self) -> str:
        return self.record.title

    @property
    def all_day(self) -> bool:
        return (
            self.record.all_day
            if isinstance(self.record, CalendarEvent)
            else self.record.start_time is None
        )

    @property
    def color(self) -> str:
        return self.category.color if self.category else "#607d8b"

    @property
    def repeated(self) -> bool:
        return bool(self.record.recurrence)

    def appears_on(self, day: date) -> bool:
        if self.kind == "task":
            return self.start.date() == day
        return self.start.date() <= day <= (self.end - timedelta(microseconds=1)).date()


@dataclass(frozen=True)
class Reminder:
    key: str
    occurrence: Occurrence
    trigger_at: datetime
