from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

from PySide6.QtCore import QObject, Signal

from desktop_buddy.ai.proposals import decode
from desktop_buddy.characters.dialogue_profiles import PROFILE_IDS
from desktop_buddy.characters.dialogue_voice import DialogueVoice
from desktop_buddy.chat.parser import HELP, parse, validate_input
from desktop_buddy.database.chat_repository import ChatRepository
from desktop_buddy.models.chat import ChatInputError, Choice, Intent, Pending, Reply
from desktop_buddy.models.online import ToolProposal
from desktop_buddy.services.command_executor import (
    PHASE_LABELS,
    SCOPE_LABELS,
    CommandExecutor,
    describe,
)


class ChatService(QObject):
    changed = Signal()
    context_changed = Signal()
    navigation_requested = Signal(str)

    def __init__(
        self, store, settings, planning, timer, statistics, companion=None, characters=None
    ):
        super().__init__()
        self.store, self.settings, self.planning = store, settings, planning
        self.timer, self.statistics, self.companion = timer, statistics, companion
        self.characters = characters
        self.repository = ChatRepository(store)
        self.executor = CommandExecutor(store, planning, timer)
        self.voice = DialogueVoice(lambda: self.character_id)
        self._character_id = settings.current.chat_character_id
        self._memory_speakers: dict[int, str] = {}
        self._memory_modes: dict[int, str] = {}
        self._history_enabled = settings.current.chat_history_enabled
        sessions = self.repository.sessions() if self._history_enabled else []
        self.session_id = sessions[0][0] if sessions else None
        self._memory: list[tuple] = []
        self._memory_id = 0
        self.pending: Pending | None = None
        self.reply = Reply(
            self._say(
                "greeting", "기본 모드 · 인터넷 없이 동작해요. '도움말'로 지원 명령을 확인하세요."
            ),
            character_id=self.character_id,
        )
        settings.changed.connect(self._settings_changed)

    @property
    def character_id(self) -> str:
        return self.settings.current.chat_character_id

    def set_character(self, character_id: str) -> None:
        if character_id not in PROFILE_IDS:
            raise ValueError("대화 캐릭터를 다시 선택해 주세요.")
        saved = (
            self.characters.select(character_id)
            if self.characters is not None
            else self.settings.update(chat_character_id=character_id)
        )
        if not saved:
            raise OSError("대화 캐릭터를 저장하지 못했어요.")

    def message_speakers(self, message_ids: list[int]) -> dict[int, str]:
        if not self.history_enabled:
            return {key: self._memory_speakers.get(key, "moru") for key in message_ids}
        return self.repository.speakers(self.session_id, message_ids) if self.session_id else {}

    def _say(self, event: str, canonical: str, details: str = "") -> str:
        return self.voice.render(event, details=details, moru_text=canonical)

    @property
    def history_enabled(self) -> bool:
        return self._history_enabled

    def _settings_changed(self, settings) -> None:
        if settings.chat_character_id != self._character_id:
            self.context_changed.emit()
            self._character_id = settings.chat_character_id
            self.pending = None
            self.reply = Reply(self._say("greeting", "안녕하세요!"), character_id=self.character_id)
            self.changed.emit()
        if settings.chat_history_enabled == self._history_enabled:
            return
        self.context_changed.emit()
        self._history_enabled = settings.chat_history_enabled
        self.session_id, self.pending = None, None
        self._memory = []
        self._memory_speakers = {}
        self._memory_modes = {}
        self.reply = Reply(
            self._say(
                "history_on" if self.history_enabled else "history_off",
                "대화 보관을 켰어요. 지금부터 새 대화에 저장해요."
                if self.history_enabled
                else "대화 보관을 껐어요. 새 메시지는 이번 실행 중에만 표시해요. "
                "이전 대화는 삭제하지 않았어요.",
            ),
            character_id=self.character_id,
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
        self.context_changed.emit()
        self.pending, self.session_id = None, None
        self._memory = []
        self._memory_speakers = {}
        self._memory_modes = {}
        self.reply = Reply(
            self._say("new_session", "새 대화를 시작해요. 이전 확인 카드는 취소했어요."),
            character_id=self.character_id,
        )
        self.changed.emit()

    def select_session(self, session_id: str) -> None:
        if session_id not in {key for key, _ in self.sessions()}:
            raise ValueError("대화를 찾을 수 없어요.")
        self.context_changed.emit()
        self.pending, self.session_id = None, session_id
        self.reply = Reply(
            self._say(
                "history_selected",
                "이전 대화예요. 기록의 제안은 실행되지 않아요. 명령을 새로 입력해 주세요.",
            ),
            character_id=self.character_id,
        )
        self.changed.emit()

    def delete_history(self, all_sessions: bool = False) -> None:
        with self.store.transaction():
            if all_sessions:
                self.repository.delete()
            elif self.session_id:
                self.repository.delete(self.session_id)
        self.new_session()
        self.reply = Reply(
            self._say("history_deleted", "대화를 삭제했어요. 일정·할 일·공부 기록은 유지했어요."),
            character_id=self.character_id,
        )
        self.changed.emit()

    def _append(self, role: str, text: str, mode: str = "offline") -> None:
        # Called only in the executor's transaction, or our own transaction.
        if self.history_enabled:
            if self.session_id is None:
                previous = self.session_id
                self.store.on_rollback(lambda: setattr(self, "session_id", previous))
                self.session_id = self.repository.create_session()
            self.repository.append(
                self.session_id, role, text, character_id=self.character_id, mode=mode
            )

    def _remember(
        self, role: str, text: str, character_id: str | None = None, mode: str = "offline"
    ) -> None:
        if not self.history_enabled:
            self._memory_id += 1
            self._memory.append((self._memory_id, role, text, self.timer.clock.now().isoformat()))
            self._memory_speakers[self._memory_id] = character_id or self.character_id
            self._memory_modes[self._memory_id] = mode
            self._memory = self._memory[-200:]
            self._memory_speakers = {row[0]: self._memory_speakers[row[0]] for row in self._memory}
            self._memory_modes = {row[0]: self._memory_modes[row[0]] for row in self._memory}

    def message_modes(self, message_ids: list[int]) -> dict[int, str]:
        if not self.history_enabled:
            return {key: self._memory_modes.get(key, "offline") for key in message_ids}
        return self.repository.modes(self.session_id, message_ids) if self.session_id else {}

    def begin_online(self, text: str, *, notify_context: bool = True) -> None:
        validate_input(text)
        if notify_context:
            self.context_changed.emit()
        self.pending = None
        with self.store.transaction():
            self._append("user", text, "ai")
        self._remember("user", text, mode="ai")
        self.changed.emit()

    def accept_online(self, text: str) -> None:
        with self.store.transaction():
            self._append("assistant", text, "ai")
        self._remember("assistant", text, mode="ai")
        self.reply = Reply(text, character_id=self.character_id)
        self.changed.emit()

    def accept_proposal(self, proposal: ToolProposal) -> Reply:
        intent = decode(proposal)
        if intent.kind in ("list", "study", "status"):
            today = self.timer.clock.now().astimezone(self.planning.zone).date()
            # Local data is rendered by the app, never sent back to the model.
            return self._respond(Reply(self._read(intent, today)))
        return self._propose(intent, source="ai")

    def _respond(self, reply: Reply, already_saved: bool = False) -> Reply:
        if not already_saved:
            reply = replace(reply, character_id=self.character_id)
            with self.store.transaction():
                self._append("assistant", reply.text)
        self._remember("assistant", reply.text, reply.character_id)
        self.reply = reply
        self.changed.emit()
        return reply

    def submit(self, text: str) -> Reply:
        self.context_changed.emit()
        self.pending = None
        text = validate_input(text)
        today = self.timer.clock.now().astimezone(self.planning.zone).date()
        intent = parse(text, today)
        with self.store.transaction():
            self._append("user", text)
        self._remember("user", text)
        if intent.kind in ("help", "list", "study", "status", "navigate", "smalltalk"):
            if (
                intent.kind == "help"
                and text not in ("도움말", "명령어")
                and self.character_id != "moru"
            ):
                result = self._respond(Reply(self._say("greeting", "안녕하세요!")))
            else:
                result = self._respond(Reply(self._read(intent, today)))
            if intent.kind == "navigate":
                self.navigation_requested.emit(intent.values["page"])
            return result
        if intent.kind in ("timer_start", "timer_pause", "timer_resume"):
            reply = self._execute(str(uuid4()), intent)
            return self._respond(reply, already_saved=True)
        return self._propose(intent)

    def _execute(
        self, request_id: str, intent: Intent, target=None, scope="one", fingerprint=None
    ) -> Reply:
        prepared: list[Reply] = []

        def persist(body: str) -> None:
            reply = self._action_reply(intent, body)
            self._append("assistant", reply.text)
            prepared.append(reply)

        self.executor.execute(request_id, intent, persist, target, scope, fingerprint)
        return (
            prepared[0]
            if prepared
            else Reply(
                self._say("duplicate", "이미 처리한 요청이에요. 중복 실행하지 않았어요."),
                character_id=self.character_id,
            )
        )

    def _action_reply(self, intent: Intent, body: str) -> Reply:
        details = ""
        if intent.kind == "timer_start":
            details = f"{PHASE_LABELS[intent.values['phase']]} · {intent.values['minutes']}분"
        elif intent.kind in ("add", "move"):
            first, _, rest = body.partition("\n")
            details = ("#" + first.partition("#")[2] + "\n" if "#" in first else "") + rest
        elif intent.kind in ("complete", "uncomplete", "delete"):
            details = body.partition(". ")[2]
        event = "success_" + intent.kind
        if intent.kind == "timer_pause" and self.timer.status == "ready":
            event = "focus_done" if self.timer.phase == "focus" else "break_done"
        return Reply(self._say(event, body, details), character_id=self.character_id)

    def _read(self, intent: Intent, today) -> str:
        if intent.kind == "smalltalk":
            event = intent.values["event"]
            default = {
                "reluctant": "공부하기 싫은 날도 있죠. 작은 것 하나부터 해볼까요?",
                "celebrate": "시험 잘 봤다니 기쁘겠어요. 축하해요!",
                "unfinished": "계획을 다 못 지켜도 괜찮아요. 남은 것을 다시 정해봐요.",
                "encourage": "네 속도로 조금씩 해봐요. 응원할게요!",
                "thanks": "도움이 됐다니 기뻐요!",
            }[event]
            return self._say(event, default)
        if intent.kind == "help":
            return self._say(
                "help",
                "안녕하세요! " + HELP,
                "\n".join(HELP.splitlines()[1:-1]) + "\n한 번에 한 명령. 변경은 확인 후 적용.",
            )
        if intent.kind == "navigate":
            canonical = (
                "설정을 열었어요." if intent.values["page"] == "settings" else "캘린더를 열었어요."
            )
            return self._say(
                "info",
                canonical,
                "열린 화면: " + ("설정" if intent.values["page"] == "settings" else "캘린더"),
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
            canonical = (
                f"타이머: {state} · {PHASE_LABELS[self.timer.phase]} · "
                f"남은 시간 {int(snapshot.remaining_seconds)}초\n{description}"
            ).strip()
            details = canonical.partition("\n")[0]
            if self.companion:
                companion = self.companion.snapshot
                state_label = {
                    "idle": "평소",
                    "happy": "기쁨",
                    "focus": "집중",
                    "break": "휴식",
                    "complete": "완료",
                    "worried": "걱정",
                    "sad": "시무룩",
                    "sleep": "수면",
                }.get(companion.state, "확인 중")
                details += (
                    f"\n생활 상태: {state_label} · "
                    f"쉬는 날: {'예' if companion.resting else '아니오'} · "
                    f"날짜 확인 필요: {'예' if companion.clock_warning else '아니오'}"
                )
            return self._say("info", canonical, details)

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
            return self._say(
                "info",
                "\n".join(lines),
                "\n".join(lines[:51])
                + ("\n전체 목록: 캘린더 (채팅 최대 50개)" if len(items) > 50 else ""),
            )
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
        canonical = (
            f"{label} 공부 시간: {seconds // 3600}시간 {(seconds % 3600) // 60}분 "
            f"{seconds % 60}초\n휴식·일시정지·기록 끄기 세션은 제외해요. "
            "진행 중 시간은 최근 체크포인트 기준이에요."
        )

        return self._say(
            "info",
            canonical,
            canonical.partition("\n")[0]
            + "\n휴식·일시정지·미기록 세션 제외. 진행 중은 최근 체크포인트 기준.",
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
        self,
        intent: Intent,
        options: list[tuple[str, tuple]],
        text: str,
        target=None,
        *,
        source: str = "offline",
    ) -> Reply:
        choices = {str(uuid4()): (label, value) for label, value in options}
        request_id = str(uuid4())
        details = {
            "할 일과 일정 중 어떤 항목으로 추가할까요?": "추가할 종류: 할 일 / 일정",
            "같은 제목이 여러 개예요. 대상을 선택해 주세요.": (
                "같은 제목이 여러 개. 날짜·종류·분류로 대상 선택."
            ),
            "반복 항목의 변경 범위를 선택해 주세요.": "반복 범위: 이번만 / 이번부터 이후 / 전체",
        }[text]
        reply = Reply(
            self._say("choose", text, details),
            request_id,
            tuple(Choice(key, label) for key, (label, _) in choices.items()),
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
            source=source,
        )
        self.changed.emit()
        return result

    def _propose(
        self, intent: Intent, target=None, scope: str | None = None, *, source: str = "offline"
    ) -> Reply:
        kind = intent.kind
        if kind == "add" and intent.values["kind"] is None:
            return self._choices(
                intent,
                [
                    (label, (replace(intent, values=dict(intent.values, kind=value)), None, None))
                    for label, value in (("할 일", "task"), ("일정", "event"))
                ],
                "할 일과 일정 중 어떤 항목으로 추가할까요?",
                source=source,
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
                raise ChatInputError(
                    f"{day}에서 '{title}' 항목을 찾지 못했어요. "
                    "날짜와 정확한 제목을 확인해 주세요.",
                    f"조회 날짜: {day}\n입력한 제목: {title}\n"
                    "해당 항목을 찾지 못했어. 날짜와 정확한 제목을 확인해줘.",
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
                    source=source,
                )
            target = matches[0]
        if target and target.repeated and kind in ("move", "delete") and scope is None:
            return self._choices(
                intent,
                [(label, (intent, target, value)) for value, label in SCOPE_LABELS.items()],
                "반복 항목의 변경 범위를 선택해 주세요.",
                target,
                source=source,
            )
        scope = scope or "one"
        intent = replace(intent, values=dict(intent.values, scope=scope))
        summary = self.executor.preview(intent, target, scope, informal=self.character_id != "moru")
        request_id = str(uuid4())
        result = self._respond(
            Reply(
                self._say(
                    "preview",
                    summary + "\n아직 실행하지 않았어요. 확인하면 적용해요. (5분 후 만료)",
                    summary + "\n확인 후 적용 · 5분 후 만료",
                ),
                request_id,
            )
        )
        self.pending = Pending(
            request_id,
            intent,
            summary,
            self.timer.clock.now() + timedelta(minutes=5),
            self.executor.fingerprint(intent, target),
            target,
            source=source,
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
        return self._propose(intent, target, scope, source=pending.source)

    def confirm(self, request_id: str) -> Reply:
        if self.repository.completed(request_id):
            return Reply(
                self._say("duplicate", "이미 처리한 요청이에요. 중복 실행하지 않았어요."),
                character_id=self.character_id,
            )
        pending = self._valid_pending(request_id)
        if pending.choices:
            raise ValueError("먼저 대상을 선택해 주세요.")
        try:
            reply = self._execute(
                request_id,
                pending.intent,
                pending.target,
                pending.intent.values.get("scope", "one"),
                pending.fingerprint,
            )
        except ValueError:
            self.pending = None
            raise
        self.pending = None
        return self._respond(reply, already_saved=True)

    def invalidate_pending(self) -> None:
        if self.pending is not None:
            self.pending = None
            self.changed.emit()

    def cancel(self) -> Reply:
        self.pending = None
        return self._respond(Reply(self._say("cancel", "제안을 취소했어요. 변경하지 않았어요.")))
