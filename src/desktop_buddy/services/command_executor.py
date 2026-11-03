import hashlib
import json
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, time, timedelta

from desktop_buddy.database.chat_repository import ChatRepository
from desktop_buddy.models.chat import Intent
from desktop_buddy.models.planning import CalendarEvent, Occurrence, Record, Task

SCOPE_LABELS = {"one": "이번 항목만", "following": "이번부터 이후", "all": "전체 반복"}
PHASE_LABELS = {"focus": "집중", "short_break": "짧은 휴식", "long_break": "긴 휴식"}


def describe(record: Record) -> str:
    if isinstance(record, Task):
        when = f"{record.scheduled_date} " + (
            record.start_time.strftime("%H:%M") if record.start_time else "시간 없음"
        )
        due = (
            f" · 마감 {record.due_at.astimezone(record.start.tzinfo):%Y-%m-%d %H:%M}"
            if record.due_at
            else ""
        )
        return f"할 일 · {record.title}\n{when} (Asia/Seoul){due}"
    return (
        f"일정 · {record.title}\n{record.start:%Y-%m-%d %H:%M} → "
        f"{record.end:%Y-%m-%d %H:%M} (Asia/Seoul)" + (" · 종일" if record.all_day else "")
    )


class CommandExecutor:
    def __init__(self, store, planning, timer):
        self.store, self.planning, self.timer = store, planning, timer
        self.repository = ChatRepository(store)

    def fingerprint(self, intent: Intent, target: Occurrence | None = None) -> str:
        if intent.kind.startswith("timer_"):
            timer = self.timer
            data = (
                timer.status,
                timer.session_id,
                timer.phase,
                timer.planned,
                timer.completed_rounds,
                timer.next_phase,
            )
        elif target:
            root = self.planning.repository.get(target.kind, target.item_id)
            data = (
                root.payload(),
                self.planning.repository.exceptions(target.kind, target.item_id),
                self.planning.repository.completions(target.item_id)
                if target.kind == "task"
                else {},
                self.planning.categories(),
            )
        elif intent.kind == "add":
            data = self.planning.categories()
        else:
            data = [
                self.store.connection.execute(f"SELECT * FROM {table}").fetchall()
                for table in (
                    "tasks",
                    "calendar_events",
                    "recurrence_exceptions",
                    "task_completions",
                    "categories",
                )
            ]
        return hashlib.sha256(
            json.dumps(data, sort_keys=True, default=str, ensure_ascii=False).encode()
        ).hexdigest()

    def addition(self, intent: Intent) -> Record:
        value = intent.values
        if value["kind"] == "task":
            if value["end"] or value["all_day"]:
                raise ValueError("시간 범위·종일 표시는 일정으로 추가해 주세요.")
            record = Task(value["title"], value["day"], start_time=value["start"])
        else:
            if not value["start"] and not value["all_day"]:
                raise ValueError(
                    "일정은 '내일 15:00 회의 일정 추가해줘' 또는 "
                    "'내일 종일 휴가 일정 추가해줘'처럼 입력해 주세요."
                )
            start = datetime.combine(value["day"], value["start"] or time(), self.planning.zone)
            end = (
                datetime.combine(value["day"], value["end"], self.planning.zone)
                if value["end"]
                else start + timedelta(days=1)
                if value["all_day"]
                else start + timedelta(hours=1)
            )
            record = CalendarEvent(value["title"], start, end, all_day=value["all_day"])
        return self.planning.validate(record)

    def moved(self, intent: Intent, target: Occurrence, scope: str) -> Record:
        record = self.planning.draft(target, scope)
        shift = intent.values["destination"] - target.start.date()
        if isinstance(record, Task):
            # Moving the scheduled day does not silently change an explicit deadline.
            return replace(record, scheduled_date=record.scheduled_date + shift)
        return replace(record, start_at=record.start + shift, end_at=record.end + shift)

    def preview(self, intent: Intent, target: Occurrence | None, scope: str) -> str:
        kind = intent.kind
        if kind == "add":
            record = self.addition(intent)
            extra = ""
            if (
                isinstance(record, CalendarEvent)
                and not intent.values["end"]
                and not record.all_day
            ):
                extra = "\n종료 시각: 시작 1시간 후 (기본값)"
            return f"추가할 내용\n{describe(record)}\n분류 없음 · 반복 없음{extra}"
        if kind in ("timer_stop", "timer_reset"):
            timer = self.timer
            return (
                ("타이머 중지" if kind == "timer_stop" else "타이머 초기화")
                + f"\n현재: {timer.status} · {PHASE_LABELS[timer.phase]}\n"
                "진행한 공부 시간은 보존합니다. "
                "기록 끄기로 시작한 세션은 저장하지 않습니다."
                + (
                    "\n완료 회차를 0으로 되돌립니다. 이전 공부 기록은 지우지 않습니다."
                    if kind == "timer_reset"
                    else ""
                )
            )
        summary = describe(target.record)
        category = target.category.name if target.category else "분류 없음"
        if kind == "move":
            changed = self.moved(intent, target, scope)
            self.planning.validate(changed)
            if target.repeated and scope == "all":
                summary = describe(self.planning.draft(target, "all"))
            return (
                f"변경 전\n{summary}\n변경 후\n{describe(changed)}\n"
                f"{category} · {SCOPE_LABELS[scope]}\n할 일의 기존 마감 시각은 유지합니다."
            )
        action = {"delete": "삭제", "complete": "완료 처리", "uncomplete": "완료 취소"}[kind]
        return f"{action}할 내용\n{summary}\n{category} · {SCOPE_LABELS[scope]}"

    def execute(
        self,
        operation_id: str,
        intent: Intent,
        persist_result: Callable[[str], None],
        target: Occurrence | None = None,
        scope: str = "one",
        fingerprint: str | None = None,
    ) -> str:
        with self.store.transaction():
            if self.repository.completed(operation_id):
                return "이미 처리한 요청이에요. 중복 실행하지 않았어요."
            if fingerprint is not None:
                try:
                    current = self.fingerprint(intent, target)
                except LookupError:
                    current = None
                if fingerprint != current:
                    raise ValueError(
                        "대상 또는 타이머 상태가 바뀌었어요. 명령을 다시 입력하고 확인해 주세요."
                    )
            result = self._apply(intent, target, scope)
            self.repository.complete(operation_id, intent.kind)
            persist_result(result)
        return result

    def _apply(self, intent: Intent, target: Occurrence | None, scope: str) -> str:
        kind, timer = intent.kind, self.timer
        if kind == "add":
            record = self.addition(intent)
            item_id = self.planning.save(record)
            return f"저장했어요. #{item_id}\n{describe(record)}"
        if kind == "move":
            record = self.moved(intent, target, scope)
            self.planning.edit(target, record, scope)
            return "옮겼어요.\n" + describe(record)
        if kind == "delete":
            self.planning.delete(target, scope)
            return f"삭제했어요. {target.title} · {SCOPE_LABELS[scope]}"
        if kind in ("complete", "uncomplete"):
            completed = kind == "complete"
            if target.completed == completed:
                raise ValueError("이미 같은 완료 상태예요. 다시 조회해 주세요.")
            self.planning.set_completed(target, completed)
            return (
                f"{'완료 처리했어요' if completed else '완료를 취소했어요'}. "
                f"{target.title} · {target.start:%Y-%m-%d}"
            )
        if kind == "timer_start":
            timer.start(intent.values["phase"], intent.values["minutes"])
            return f"{intent.values['minutes']}분 {PHASE_LABELS[timer.phase]} 타이머를 시작했어요."
        if kind == "timer_pause":
            if timer.status != "running":
                raise ValueError("실행 중인 타이머가 없어요.")
            timer.pause()
            return (
                "타이머가 완료되어 다음 단계를 기다려요."
                if timer.status == "ready"
                else "타이머를 일시정지했어요."
            )
        if kind == "timer_resume":
            if timer.status != "paused":
                raise ValueError("일시정지한 타이머가 없어요.")
            timer.resume()
            return "타이머를 재개했어요."
        if kind == "timer_stop":
            if timer.status == "idle":
                raise ValueError("중지할 타이머가 없어요.")
            timer.stop()
            return "타이머를 중지했어요."
        if kind == "timer_reset":
            timer.reset()
            return "타이머와 완료 회차를 초기화했어요. 이전 공부 기록은 유지했어요."
        raise ValueError("허용되지 않은 명령이에요.")
