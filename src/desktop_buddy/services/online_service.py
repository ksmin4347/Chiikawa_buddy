from collections import defaultdict
from uuid import uuid4

from PySide6.QtCore import QObject, Qt, Signal, Slot

from desktop_buddy.ai.client import ResponsesClient, token_count
from desktop_buddy.ai.config import MAX_REPLY_CHARACTERS, REQUEST_SECONDS, validate_model
from desktop_buddy.ai.job import JobSignals, OnlineJob
from desktop_buddy.characters.ai_persona import format_reply
from desktop_buddy.chat.parser import looks_secret, validate_input
from desktop_buddy.models.online import OnlineRequest, OnlineResult

ERRORS = {
    "key_missing": "저장된 키가 없어요. API 키 관리에서 먼저 보관해 주세요.",
    "key_store": "Windows 키 저장소를 읽지 못했어요. 저장 상태를 확인해 주세요.",
    "auth": "키 인증에 실패했어요. 저장한 키를 확인해 주세요.",
    "permission": "이 키로 요청할 권한이 없어요. 프로젝트·모델 권한을 확인해 주세요.",
    "model": "선택한 모델을 사용할 수 없어요. 모델 ID와 계정 권한을 확인해 주세요.",
    "rate_limit": "요청 한도나 사용 가능 잔액을 확인해 주세요. 자동 재시도하지 않았어요.",
    "timeout": "응답 제한 시간을 넘었어요. 자동 재요청하지 않았어요.",
    "network": "연결하지 못했어요. 네트워크 상태를 확인해 주세요.",
    "server": "OpenAI 응답에 문제가 있어요. 잠시 뒤 직접 다시 시도해 주세요.",
    "request": "요청 또는 모델 설정을 확인해 주세요. 자동 재요청하지 않았어요.",
    "incomplete": "답변을 끝까지 받지 못했어요. 질문을 줄이거나 모델을 확인해 주세요.",
    "refused": "이 요청의 답변을 제공하지 못했어요. 질문을 바꿔 주세요.",
    "response": "지원하는 텍스트 응답을 받지 못했어요. 앱 작업은 실행하지 않았어요.",
    "proposal": "AI 제안을 확인하지 못했어요. 날짜·제목·타이머 상태를 확인해 다시 요청해 주세요.",
    "date_changed": "기준 날짜가 바뀌었어요. 현재 날짜를 확인하고 다시 요청해 주세요.",
    "sensitive": "비밀 값으로 보이는 내용을 감지했어요. 해당 내용은 대화에 표시·저장하지 않았어요.",
    "cancelled": "요청을 취소했어요. 이미 전송된 요청의 처리·요금은 취소되지 않을 수 있어요.",
    "setup": "온라인 구성 요소가 없어요. 소스 실행은 setup_windows.bat으로 준비해 주세요.",
    "storage": "대화 내용을 저장하지 못했어요. 자동으로 다시 요청하지 않았어요.",
    "unknown": "AI 요청을 마치지 못했어요. 오프라인 기능은 계속 사용할 수 있어요.",
}


class OnlineService(QObject):
    changed = Signal()
    completed = Signal(str, bool)

    def __init__(self, keys, settings, chat, *, client=None, deadline=REQUEST_SECONDS):
        super().__init__()
        self.keys, self.settings, self.chat = keys, settings, chat
        self.client = client if client is not None else ResponsesClient()
        self.deadline = deadline
        self.enabled = self.ready = self._closed = False
        self.actions_allowed = False
        self.status = "기본은 오프라인이에요. 연결 테스트 후 직접 AI 대화를 켤 수 있어요."
        self.usage = None
        self.last_error = ""
        self._model = settings.current.ai_model
        self._job = self._active = None
        self._turns = defaultdict(int)
        self.signals = JobSignals(self)
        self.signals.prepared.connect(self._prepare, Qt.ConnectionType.QueuedConnection)
        self.signals.finished.connect(self._finished, Qt.ConnectionType.QueuedConnection)
        keys.changed.connect(self.reset)
        chat.context_changed.connect(self.cancel)
        settings.changed.connect(self._settings_changed)

    @property
    def busy(self) -> bool:
        return self._job is not None

    @property
    def kind(self) -> str:
        return self._active.kind if self._active else ""

    def _settings_changed(self, settings):
        if settings.ai_model != self._model:
            self._model = settings.ai_model
            self.reset()

    def set_model(self, value: str) -> None:
        value = validate_model(value)
        if not self.settings.update(ai_model=value):
            raise ValueError("모델 설정을 저장하지 못했어요.")

    def set_enabled(self, enabled: bool) -> None:
        if enabled and (not self.ready or self._closed):
            raise ValueError("API 키·모델의 연결 테스트를 먼저 완료해 주세요.")
        was_active = self._active is not None
        self.enabled = bool(enabled)
        self.chat.invalidate_pending()
        if not enabled:
            self.actions_allowed = False
            self.cancel()
        if self._active is None and not (was_active and not enabled):
            self.status = (
                "온라인 AI 대화예요. 현재 문장만 OpenAI에 보내요."
                if enabled
                else "오프라인 명령 모드예요. 네트워크 요청을 보내지 않아요."
            )
        self.changed.emit()

    def set_actions_allowed(self, allowed: bool) -> None:
        if allowed and not self.enabled:
            raise ValueError("온라인 AI 대화를 먼저 켜 주세요.")
        if bool(allowed) != self.actions_allowed:
            self.cancel()
            self.chat.invalidate_pending()
            self.actions_allowed = bool(allowed)
            self.status = (
                "AI 작업 제안을 허용했어요. 변경은 확인 후 적용하며 조회 결과는 AI에 보내지 않아요."
                if allowed
                else "AI 작업 제안을 껐어요. 텍스트 대화만 가능해요."
            )
            self.changed.emit()

    def test_connection(self) -> str:
        return self._start("test", "Connection test. Reply with OK only.")

    def send(self, text: str) -> str:
        if not self.enabled:
            raise ValueError("온라인 AI 대화를 먼저 켜 주세요.")
        if self.busy or self._closed:
            raise ValueError("이전 요청이 끝난 뒤 다시 보내 주세요.")
        validate_input(text)
        self.chat.invalidate_pending()
        return self._start("chat", text)

    @Slot(str)
    def _prepare(self, request_id: str) -> None:
        job = self._job
        active = self._active
        if job is None or job.request.id != request_id:
            return
        if self._closed or active is None or active.id != request_id:
            job.approve(False)
            return
        try:
            if active.kind == "chat":
                self.chat.begin_online(active.text, notify_context=False)
        except Exception:
            job.approve(False)
            return
        job.approve(self._active is active and not self._closed)

    def _start(self, kind: str, text: str) -> str:
        if self.busy or self._closed:
            raise ValueError("이전 요청이 끝난 뒤 다시 시도해 주세요.")
        request = OnlineRequest(
            str(uuid4()),
            kind,
            self._model,
            text,
            self.chat.character_id,
            allow_actions=kind == "chat" and self.actions_allowed,
            local_date=self.chat.timer.clock.now()
            .astimezone(self.chat.planning.zone)
            .date()
            .isoformat(),
        )
        self._active = request
        self._job = OnlineJob(request, self.keys.vault, self.client, self.signals, self.deadline)
        self.usage = None
        self.last_error = ""
        self.status = "연결 테스트 중이에요." if kind == "test" else "AI 답변을 기다리고 있어요."
        self.changed.emit()
        try:
            self._job.start()
        except Exception:
            self._finished(request.id, OnlineResult(error="unknown"))
            raise ValueError(ERRORS["unknown"]) from None
        return request.id

    def cancel(self) -> None:
        pending_ai = self.chat.pending is not None and self.chat.pending.source == "ai"
        if pending_ai:
            self.chat.invalidate_pending()
        active, self._active = self._active, None
        if self._job is not None:
            self._job.cancel()
        if active is not None:
            self.last_error = "cancelled"
            self.status = ERRORS["cancelled"]
            self.usage = None
            if active.kind == "chat":
                self.completed.emit(active.id, False)
            self.changed.emit()
        elif pending_ai:
            self.status = "AI 작업 제안을 취소했어요. 앱 작업은 실행하지 않았어요."
            self.changed.emit()

    def reset(self) -> None:
        self.cancel()
        self.ready = self.enabled = False
        self.actions_allowed = False
        self.last_error = ""
        self.status = "키·모델이 바뀌었어요. 연결 테스트를 다시 해 주세요."
        self.usage = None
        self.changed.emit()

    @Slot(str, object)
    def _finished(self, request_id: str, result) -> None:
        if self._job is None or self._job.request.id != request_id:
            return
        self._job = None
        active, self._active = self._active, None
        if self._closed:
            return
        if active is None or active.id != request_id:
            self.changed.emit()
            return
        if not isinstance(result, OnlineResult):
            result = OnlineResult(error="response")
        error = result.error
        self.last_error = error
        if not error and (
            not isinstance(result.text, str)
            or (not result.text.strip() and result.proposal is None)
            or len(result.text) > MAX_REPLY_CHARACTERS
            or looks_secret(result.text, assignments=False)
        ):
            error = "response"
        success = not error
        if success and result.proposal is not None:
            today = (
                self.chat.timer.clock.now().astimezone(self.chat.planning.zone).date().isoformat()
            )
            if not active.allow_actions or not self.actions_allowed or active.kind != "chat":
                success, error = False, "proposal"
            elif active.local_date != today:
                success, error = False, "date_changed"
        self.usage = (token_count(result.input_tokens), token_count(result.output_tokens))
        if success and active.kind == "chat":
            turn = self._turns[active.character_id]
            try:
                if result.proposal is not None:
                    self.chat.accept_proposal(result.proposal)
                else:
                    self.chat.accept_online(format_reply(result.text, active.character_id, turn))
                self._turns[active.character_id] += 1
            except ValueError:
                success, error = False, "proposal"
            except Exception:
                success, error = False, "storage"
        self.last_error = error
        if success:
            self.ready = True
            self.status = (
                "선택한 모델의 연결을 확인했어요. AI 대화는 직접 켜 주세요."
                if active.kind == "test"
                else "AI 작업 제안이에요. 내용을 확인한 뒤에만 적용돼요."
                if result.proposal is not None and self.chat.pending is not None
                else "앱이 기기 안에서 조회했어요. 결과를 AI에 보내지 않았어요."
                if result.proposal is not None
                else "AI 답변이에요. 계획·타이머 작업은 실행하지 않았어요."
            )
        else:
            self.status = ERRORS.get(error, ERRORS["unknown"])
            if error in ("auth", "permission", "model", "key_missing", "key_store"):
                self.ready = self.enabled = False
                self.actions_allowed = False
        if active.kind == "chat":
            self.completed.emit(request_id, success)
        self.changed.emit()

    def close(self) -> None:
        self._closed = True
        self.cancel()
        self.ready = self.enabled = False
        self.actions_allowed = False
