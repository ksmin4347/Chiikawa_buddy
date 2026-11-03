from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

from PySide6.QtCore import QObject, Signal

from desktop_buddy.chat.parser import HELP, parse, validate_input
from desktop_buddy.database.chat_repository import ChatRepository
from desktop_buddy.models.chat import Choice, Intent, Pending, Reply
from desktop_buddy.services.command_executor import (
    PHASE_LABELS,
    SCOPE_LABELS,
    CommandExecutor,
    describe,
)


class ChatService(QObject):
    changed = Signal()
    navigation_requested = Signal(str)

    def __init__(self, store, settings, planning, timer, statistics, companion=None):
        super().__init__()
        self.store, self.settings, self.planning = store, settings, planning
        self.timer, self.statistics, self.companion = timer, statistics, companion
        self.repository = ChatRepository(store)
        self.executor = CommandExecutor(store, planning, timer)
        self._history_enabled = settings.current.chat_history_enabled
        sessions = self.repository.sessions() if self._history_enabled else []
        self.session_id = sessions[0][0] if sessions else None
        self._memory: list[tuple] = []
        self._memory_id = 0
        self.pending: Pending | None = None
        self.reply = Reply("기본 모드 · 인터넷 없이 동작해요. '도움말'로 지원 명령을 확인하세요.")
        settings.changed.connect(self._settings_changed)

    @property
    def history_enabled(self) -> bool:
        return self._history_enabled

    def _settings_changed(self, settings) -> None:
        if settings.chat_history_enabled == self._history_enabled:
            return
        self._history_enabled = settings.chat_history_enabled
        self.session_id, self.pending = None, None
        self._memory = []
        self.reply = Reply(
            "대화 보관을 켰어요. 지금부터 새 대화에 저장해요."
            if self.history_enabled
            else "대화 보관을 껐어요. 새 메시지는 이번 실행 중에만 표시해요. "
            "이전 대화는 삭제하지 않았어요."
        )
        self.changed.emit()

    def set_history(self, enabled: bool) -> None:
        if not self.settings.update(chat_history_enabled=enabled):
            raise OSError("대화 보관 설정을 저장하지 못했어요.")

    def sessions(self) -> list[tuple]:
        return self.repository.sessions() if self.history_enabled else []

    def messages(self, before_id: int | None = None) -> list[tuple]:
        if not self.history_enabled:
            return (
                self._memory[-50:]
                if before_id is None
                else [r for r in self._memory if r[0] < before_id][-50:]
            )
        return self.repository.messages(self.session_id, before_id) if self.session_id else []

    def new_session(self) -> None:
        self.pending, self.session_id = None, None
        self._memory = []
        self.reply = Reply("새 대화를 시작해요. 이전 확인 카드는 취소했어요.")
        self.changed.emit()

    def select_session(self, session_id: str) -> None:
        if session_id not in {key for key, _ in self.sessions()}:
            raise ValueError("대화를 찾을 수 없어요.")
        self.pending, self.session_id = None, session_id
        self.reply = Reply(
            "이전 대화예요. 기록의 제안은 실행되지 않아요. 명령을 새로 입력해 주세요."
        )
        self.changed.emit()

    def delete_history(self, all_sessions: bool = False) -> None:
        with self.store.transaction():
            if all_sessions:
                self.repository.delete()
            elif self.session_id:
                self.repository.delete(self.session_id)
        self.new_session()
        self.reply = Reply("대화를 삭제했어요. 일정·할 일·공부 기록은 유지했어요.")
        self.changed.emit()

    def _append(self, role: str, text: str) -> None:
        # Called only in the executor's transaction, or our own transaction.
        if self.history_enabled:
            if self.session_id is None:
                previous = self.session_id
                self.store.on_rollback(lambda: setattr(self, "session_id", previous))
                self.session_id = self.repository.create_session()
            self.repository.append(self.session_id, role, text)

    def _remember(self, role: str, text: str) -> None:
        if not self.history_enabled:
            self._memory_id += 1
            self._memory.append((self._memory_id, role, text, self.timer.clock.now().isoformat()))
            self._memory = self._memory[-200:]

    def _respond(self, reply: Reply, already_saved: bool = False) -> Reply:
        if not already_saved:
            with self.store.transaction():
                self._append("assistant", reply.text)
        self._remember("assistant", reply.text)
        self.reply = reply
        self.changed.emit()
        return reply

    def submit(self, text: str) -> Reply:
        self.pending = None
        text = validate_input(text)
        today = self.timer.clock.now().astimezone(self.planning.zone).date()
        intent = parse(text, today)
        with self.store.transaction():
            self._append("user", text)
        self._remember("user", text)
        if intent.kind in ("help", "list", "study", "status", "navigate"):
            result = self._respond(Reply(self._read(intent, today)))
            if intent.kind == "navigate":
                self.navigation_requested.emit(intent.values["page"])
            return result
        if intent.kind in ("timer_start", "timer_pause", "timer_resume"):
            result = self.executor.execute(
                str(uuid4()), intent, lambda body: self._append("assistant", body)
            )
            return self._respond(Reply(result), already_saved=True)
        return self._propose(intent)

    def _read(self, intent: Intent, today) -> str:
        if intent.kind == "help":
            return "안녕하세요! " + HELP
        if intent.kind == "navigate":
            return (
                "설정을 열었어요." if intent.values["page"] == "settings" else "캘린더를 열었어요."
            )
        if intent.kind == "status":
            snapshot = self.timer.snapshot
            state = {
                "idle": "대기",
                "ready": "다음 단계 대기",
                "running": "진행 중",
                "paused": "일시정지",
            }[self.timer.status]
            description = self.companion.snapshot.description if self.companion else ""
            return (
                f"타이머: {state} · {PHASE_LABELS[self.timer.phase]} · "
                f"남은 시간 {int(snapshot.remaining_seconds)}초\n{description}"
            ).strip()
        if intent.kind == "list":
            day = intent.values["day"]
            items = self.planning.occurrences(day, day + timedelta(days=1), intent.values["kind"])
            title = "할 일" if intent.values["kind"] == "task" else "일정"
            lines = [f"{day} {title} · {len(items)}개 (Asia/Seoul)"]
            for item in items[:50]:
                lines.append(
                    ("[완료] " if item.completed else "• ")
                    + describe(item.record).replace("\n", " · ")
                )
            if len(items) > 50:
                lines.append("최근 화면에는 50개까지만 표시해요. 캘린더에서 전체를 확인하세요.")
            return "\n".join(lines)
        period = intent.values["period"]
        if period == "전체":
            seconds = self.statistics.all_total()
            label = "전체 누적"
        else:
            start = (
                today
                if period == "오늘"
                else today
                - timedelta(days=(today.weekday() - self.settings.current.week_start) % 7)
                if period == "이번주"
                else today.replace(day=1)
            )
            end = (
                today + timedelta(days=1)
                if period == "오늘"
                else start + timedelta(days=7)
                if period == "이번주"
                else (start.replace(day=28) + timedelta(days=4)).replace(day=1)
            )
            seconds = self.statistics.totals(start, end)["seconds"]
            label = f"{period} ({start}~{end - timedelta(days=1)})"
        seconds = int(seconds)
        return (
            f"{label} 공부 시간: {seconds // 3600}시간 {(seconds % 3600) // 60}분 "
            f"{seconds % 60}초\n휴식·일시정지·기록 끄기 세션은 제외해요. "
            "진행 중 시간은 최근 체크포인트 기준이에요."
        )

    def _valid_pending(self, request_id: str) -> Pending:
        pending = self.pending
        now = self.timer.clock.now()
        if not pending or pending.request_id != request_id:
            raise ValueError("유효한 확인 카드가 없어요. 명령을 다시 입력해 주세요.")
        if not pending.expires_at - timedelta(minutes=5) <= now < pending.expires_at:
            self.pending = None
            raise ValueError("확인 카드가 만료되었어요. 명령을 다시 입력해 주세요.")
        return pending

    def _choices(
        self, intent: Intent, options: list[tuple[str, tuple]], text: str, target=None
    ) -> Reply:
        choices = {str(uuid4()): (label, value) for label, value in options}
        request_id = str(uuid4())
        reply = Reply(
            text, request_id, tuple(Choice(key, label) for key, (label, _) in choices.items())
        )
        result = self._respond(reply)
        self.pending = Pending(
            request_id,
            intent,
            text,
            self.timer.clock.now() + timedelta(minutes=5),
            self.executor.fingerprint(intent, target),
            target,
            choices,
        )
        self.changed.emit()
        return result

    def _propose(self, intent: Intent, target=None, scope: str | None = None) -> Reply:
        kind = intent.kind
        if kind == "add" and intent.values["kind"] is None:
            return self._choices(
                intent,
                [
                    (label, (replace(intent, values=dict(intent.values, kind=value)), None, None))
                    for label, value in (("할 일", "task"), ("일정", "event"))
                ],
                "할 일과 일정 중 어떤 항목으로 추가할까요?",
            )
        if kind in ("move", "delete", "complete", "uncomplete") and target is None:
            day, title = intent.values["day"], intent.values["title"]
            items = self.planning.occurrences(day, day + timedelta(days=1), intent.values["kind"])
            if kind in ("complete", "uncomplete"):
                items = [item for item in items if item.kind == "task"]
            matches = [item for item in items if item.title == title]
            if not matches and title.endswith(("을", "를")):
                matches = [item for item in items if item.title == title[:-1]]
            if not matches:
                raise ValueError(
                    f"{day}에서 '{title}' 항목을 찾지 못했어요. 날짜와 정확한 제목을 확인해 주세요."
                )
            if len(matches) > 50:
                raise ValueError("같은 제목이 50개를 넘어요. 캘린더에서 대상을 선택해 주세요.")
            if len(matches) > 1:
                return self._choices(
                    intent,
                    [
                        (
                            f"#{item.item_id} · {item.start:%Y-%m-%d %H:%M} · "
                            f"{'할 일' if item.kind == 'task' else '일정'} · {item.title} · "
                            f"{item.category.name if item.category else '분류 없음'}",
                            (intent, item, None),
                        )
                        for item in matches
                    ],
                    "같은 제목이 여러 개예요. 대상을 선택해 주세요.",
                )
            target = matches[0]
        if target and target.repeated and kind in ("move", "delete") and scope is None:
            return self._choices(
                intent,
                [(label, (intent, target, value)) for value, label in SCOPE_LABELS.items()],
                "반복 항목의 변경 범위를 선택해 주세요.",
                target,
            )
        scope = scope or "one"
        intent = replace(intent, values=dict(intent.values, scope=scope))
        summary = self.executor.preview(intent, target, scope)
        request_id = str(uuid4())
        result = self._respond(
            Reply(
                summary + "\n아직 실행하지 않았어요. 확인하면 적용해요. (5분 후 만료)", request_id
            )
        )
        self.pending = Pending(
            request_id,
            intent,
            summary,
            self.timer.clock.now() + timedelta(minutes=5),
            self.executor.fingerprint(intent, target),
            target,
        )
        self.changed.emit()
        return result

    def choose(self, request_id: str, choice_key: str) -> Reply:
        pending = self._valid_pending(request_id)
        if choice_key not in pending.choices:
            raise ValueError("선택 항목을 다시 확인해 주세요.")
        try:
            same = pending.fingerprint == self.executor.fingerprint(pending.intent, pending.target)
        except LookupError:
            same = False
        if not same:
            self.pending = None
            raise ValueError("대상이 바뀌었어요. 명령을 다시 입력해 주세요.")
        _, (intent, target, scope) = pending.choices[choice_key]
        return self._propose(intent, target, scope)

    def confirm(self, request_id: str) -> Reply:
        if self.repository.completed(request_id):
            return Reply("이미 처리한 요청이에요. 중복 실행하지 않았어요.")
        pending = self._valid_pending(request_id)
        if pending.choices:
            raise ValueError("먼저 대상을 선택해 주세요.")
        try:
            result = self.executor.execute(
                request_id,
                pending.intent,
                lambda body: self._append("assistant", body),
                pending.target,
                pending.intent.values.get("scope", "one"),
                pending.fingerprint,
            )
        except ValueError:
            self.pending = None
            raise
        self.pending = None
        return self._respond(Reply(result), already_saved=True)

    def cancel(self) -> Reply:
        self.pending = None
        return self._respond(Reply("제안을 취소했어요. 변경하지 않았어요."))
