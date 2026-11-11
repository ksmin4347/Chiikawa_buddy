from dataclasses import dataclass
from datetime import date

from desktop_buddy.models.planning import Record


@dataclass(frozen=True, repr=False)
class CalendarEntry:
    uid: str
    occurrence_key: str
    record: Record
    modified: str | None = None


@dataclass(frozen=True, repr=False)
class ParsedCalendar:
    entries: tuple[CalendarEntry, ...]
    notes: tuple[str, ...]


@dataclass(frozen=True, repr=False)
class ImportRow:
    id: str
    entry: CalendarEntry
    status: str
    action: str
    current: Record | None = None


@dataclass(frozen=True, repr=False)
class ImportPlan:
    id: str
    source: str
    start: date
    end: date  # Exclusive.
    rows: tuple[ImportRow, ...]
    notes: tuple[str, ...]
    fingerprint: str
    created: float


@dataclass(frozen=True, repr=False)
class ExportPlan:
    id: str
    start: date
    end: date
    entries: tuple[CalendarEntry, ...]
    fingerprint: str
    created: float
    notes: tuple[str, ...] = ()


class CalendarFileError(ValueError):
    pass
