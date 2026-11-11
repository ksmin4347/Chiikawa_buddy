"""Preview and commit bounded calendar file snapshots on the GUI connection."""

import hashlib
import json
from dataclasses import replace
from datetime import UTC, date, datetime
from time import monotonic
from uuid import UUID, uuid4

from desktop_buddy.calendar.ics_codec import MAX_ITEMS, clean_text, seoul_snapshot, window
from desktop_buddy.models.calendar_transfer import (
    CalendarEntry,
    CalendarFileError,
    ExportPlan,
    ImportPlan,
    ImportRow,
    ParsedCalendar,
)
from desktop_buddy.models.planning import CalendarEvent, Record, Task


def digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
    ).hexdigest()


def full_hash(record: Record) -> str:
    return digest(record.payload())


def content_hash(record: Record) -> str:
    def stamp(value):
        return value.astimezone(UTC).replace(microsecond=0).isoformat() if value else None

    if isinstance(record, CalendarEvent):
        return digest(
            (
                "event",
                record.title,
                record.description,
                record.all_day,
                record.start.date() if record.all_day else stamp(record.start),
                record.end.date() if record.all_day else stamp(record.end),
            )
        )
    return digest(
        (
            "task",
            record.title,
            record.description,
            record.scheduled_date if record.start_time is None else stamp(record.start),
            stamp(record.due_at),
            record.completed,
            record.priority,
        )
    )


def kind_of(record: Record) -> str:
    return "task" if isinstance(record, Task) else "event"


def owned_identity(uid: str, namespace: UUID):
    address, _, host = uid.partition("@")
    fields = address.split("-", 3)
    if host != "desktopbuddy.local" or len(fields) != 4 or fields[0] != namespace.hex:
        return None
    _, kind, item_id, key = fields
    if (
        kind not in ("task", "event")
        or not item_id.isascii()
        or not item_id.isdecimal()
        or len(item_id) > 19
    ):
        return None
    try:
        if date.fromisoformat(key).isoformat() != key:
            return None
    except ValueError:
        return None
    return kind, int(item_id)


class CalendarTransferService:
    def __init__(self, planning, *, clock=monotonic):
        self.planning, self.store = planning, planning.store
        self.clock = clock
        self.import_plan: ImportPlan | None = None
        self.export_plan: ExportPlan | None = None

    def invalidate(self) -> None:
        self.import_plan = self.export_plan = None

    def fingerprint(self) -> str:
        tables = (
            "tasks",
            "calendar_events",
            "recurrence_exceptions",
            "task_completions",
            "categories",
            "calendar_links",
            "calendar_sources",
            "calendar_identity",
        )
        return digest(
            [
                self.store.connection.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()
                for table in tables
            ]
        )

    def _valid(self, plan) -> None:
        if plan is None or not 0 <= self.clock() - plan.created < 300:
            raise CalendarFileError("미리보기가 없거나 5분이 지났어요. 다시 미리 보기해 주세요.")
        if plan.fingerprint != self.fingerprint():
            raise CalendarFileError(
                "계획이나 파일 출처 정보가 바뀌었어요. 다시 미리 보기해 주세요."
            )

    def preview_import(
        self, parsed: ParsedCalendar, source: str, start: date, end: date
    ) -> ImportPlan:
        self.import_plan = None
        window(start, end)
        source = clean_text(source, 80).strip()
        if not source:
            raise CalendarFileError("다시 가져올 때 식별할 출처 이름을 입력해 주세요.")
        if len(parsed.entries) > MAX_ITEMS:
            raise CalendarFileError("한 번에 1,000개까지 가져올 수 있어요.")
        source_key = digest(source.casefold())
        namespace = UUID(
            self.store.connection.execute("SELECT namespace FROM calendar_identity").fetchone()[0]
        )
        roots = {
            (k, r.id): r for k in ("task", "event") for r in self.planning.repository.records(k)
        }
        links = {
            (uid, key): (kind, task_id or event_id, remote, local)
            for uid, key, kind, task_id, event_id, remote, local in self.store.connection.execute(
                "SELECT uid,occurrence_key,kind,task_id,event_id,remote_hash,local_hash "
                "FROM calendar_links WHERE source_key=?",
                (source_key,),
            )
        }
        occurrences = self.planning.occurrences(start, end)
        exact = {
            content_hash(
                replace(o.record, completed=o.completed) if isinstance(o.record, Task) else o.record
            )
            for o in occurrences
        }
        busy = [o for o in occurrences if o.kind == "event"]
        rows, notes, seen, keys = [], list(parsed.notes), set(), set()
        for entry in parsed.entries:
            identity = (entry.uid, entry.occurrence_key)
            if identity in keys:
                raise CalendarFileError("같은 외부 ID/발생일이 중복된 미리보기예요.")
            keys.add(identity)
            record = self.planning.validate(entry.record)
            entry = replace(entry, record=record)
            if record.id is not None or record.recurrence:
                raise CalendarFileError("개별 항목 스냅샷만 가져올 수 있어요.")
            h = content_hash(record)
            current = None
            action = "add"
            link = links.get(identity)
            own = owned_identity(entry.uid, namespace)
            if link is None and own is not None:
                link = (*own, None, None)
            if h in seen:
                status, action = "파일 내 내용 중복", ""
            elif link:
                kind, item_id, remote_hash, local_hash = link
                current = roots.get((kind, item_id))
                if kind != kind_of(record):
                    status, action = "기존 외부 ID의 항목 종류가 다름", ""
                elif current is None:
                    status = "앱에서 삭제됨 · 다시 추가는 직접 선택"
                elif current.recurrence:
                    status, action = "앱에서 반복으로 변경됨 · 앱에서 직접 편집", ""
                elif (
                    isinstance(current, Task)
                    and current.reminder_minutes is not None
                    and record.due_at is None
                ):
                    status, action = "마감 없는 변경으로 기존 알림을 유지할 수 없음", ""
                elif content_hash(current) == h:
                    status, action = "동일 항목 · 건너뛰기", ""
                elif full_hash(current) != local_hash:
                    status, action = "충돌 · 앱에서 수정됨", "update"
                else:
                    status, action = "원본 변경 · 갱신은 직접 선택", "update"
            elif h in exact:
                status, action = "앱에 같은 내용 있음 · 건너뛰기", ""
            else:
                overlap = isinstance(record, CalendarEvent) and any(
                    record.start < o.end and record.end > o.start for o in busy
                )
                overlap = overlap or (
                    isinstance(record, CalendarEvent)
                    and any(
                        isinstance(r.entry.record, CalendarEvent)
                        and r.action == "add"
                        and record.start < r.entry.record.end
                        and record.end > r.entry.record.start
                        for r in rows
                    )
                )
                status = "시간 겹침 · 추가는 직접 선택" if overlap else "새 항목"
            seen.add(h)
            rows.append(ImportRow(str(uuid4()), entry, status, action, current))
        self.import_plan = ImportPlan(
            str(uuid4()),
            source,
            start,
            end,
            tuple(rows),
            tuple(notes),
            self.fingerprint(),
            self.clock(),
        )
        return self.import_plan

    def apply_import(
        self, plan_id: str, selected: set[str], *, allow_updates: bool = False
    ) -> tuple[int, int]:
        plan = self.import_plan
        if plan is None or plan.id != plan_id:
            raise CalendarFileError("현재 가져오기 미리보기를 다시 확인해 주세요.")
        rows = {row.id: row for row in plan.rows}
        if not selected or not selected <= rows.keys():
            raise CalendarFileError("미리보기에서 가져올 항목을 선택해 주세요.")
        chosen = [row for row in plan.rows if row.id in selected]
        if any(not row.action for row in chosen) or (
            any(row.action == "update" for row in chosen) and not allow_updates
        ):
            raise CalendarFileError("기존 항목 갱신은 내용을 확인하고 별도로 허용해 주세요.")
        added = updated = 0
        with self.store.transaction():
            self._valid(plan)
            stamp = datetime.now(UTC).isoformat()
            source_key = digest(plan.source.casefold())
            self.store.connection.execute(
                "INSERT OR IGNORE INTO calendar_sources VALUES (?,?,?)",
                (source_key, plan.source, stamp),
            )
            for row in chosen:
                record = row.entry.record
                if row.action == "update":
                    record = replace(
                        record,
                        id=row.current.id,
                        category_id=row.current.category_id,
                        reminder_minutes=row.current.reminder_minutes,
                    )
                    updated += 1
                else:
                    added += 1
                # One batch commit produces one refresh, rather than up to 1,000 redraws.
                record = self.planning.validate(record)
                item_id = self.planning.repository.save(record)
                saved = replace(record, id=item_id)
                kind = kind_of(saved)
                self.store.connection.execute(
                    "INSERT INTO calendar_links(source_key,uid,occurrence_key,kind,"
                    "task_id,event_id,remote_hash,local_hash,remote_modified,imported_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(source_key,uid,occurrence_key) DO UPDATE SET kind=excluded.kind,"
                    "task_id=excluded.task_id,event_id=excluded.event_id,remote_hash=excluded.remote_hash,"
                    "local_hash=excluded.local_hash,remote_modified=excluded.remote_modified,"
                    "imported_at=excluded.imported_at",
                    (
                        source_key,
                        row.entry.uid,
                        row.entry.occurrence_key,
                        kind,
                        item_id if kind == "task" else None,
                        item_id if kind == "event" else None,
                        content_hash(row.entry.record),
                        full_hash(saved),
                        row.entry.modified,
                        stamp,
                    ),
                )
        self.import_plan = None
        self.store.emit_after_commit(self.planning.changed)
        return added, updated

    def preview_export(self, start: date, end: date, kind: str | None = None) -> ExportPlan:
        self.export_plan = None
        window(start, end)
        if kind not in (None, "task", "event"):
            raise CalendarFileError("내보낼 항목 종류를 확인해 주세요.")
        occurrences = self.planning.occurrences(start, end, kind)
        if not 0 < len(occurrences) <= MAX_ITEMS:
            raise CalendarFileError("내보낼 항목은 1~1,000개여야 해요. 기간을 확인해 주세요.")
        namespace = UUID(
            self.store.connection.execute("SELECT namespace FROM calendar_identity").fetchone()[0]
        )
        entries, notes = [], []
        for occurrence in occurrences:
            record = replace(occurrence.record, id=None, recurrence=None)
            if isinstance(record, Task):
                record = replace(record, completed=occurrence.completed)
            record = seoul_snapshot(record)
            if (
                isinstance(record, Task)
                and record.due_at is not None
                and record.due_at <= record.start
            ):
                notes.append(
                    f"#{occurrence.item_id} {record.title}: 마감이 시작 이전/동일해서 제외했어요."
                )
                continue
            clean_text(record.title, 200)
            clean_text(record.description, 4000, multiline=True)
            uid = (
                f"{namespace.hex}-{occurrence.kind}-{occurrence.item_id}-"
                f"{occurrence.key}@desktopbuddy.local"
            )
            entries.append(CalendarEntry(uid, "", record))
        self.export_plan = ExportPlan(
            str(uuid4()), start, end, tuple(entries), self.fingerprint(), self.clock(), tuple(notes)
        )
        return self.export_plan

    def export_entries(self, plan_id: str) -> tuple[CalendarEntry, ...]:
        plan = self.export_plan
        if plan is None or plan.id != plan_id:
            raise CalendarFileError("현재 내보내기 미리보기를 다시 확인해 주세요.")
        self._valid(plan)
        return plan.entries
