from datetime import datetime

from PySide6.QtCore import QSignalBlocker, Qt, QTimer
from PySide6.QtGui import QAction, QKeySequence, QTextCursor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QMessageBox,
    QPlainTextEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from desktop_buddy.characters.dialogue_profiles import PROFILES, profile
from desktop_buddy.chat.parser import SecretInputError
from desktop_buddy.ui.accessibility import CommandInput, announce
from desktop_buddy.ui.common import WrappedStatus, button, card, label


class ChatTranscript(QPlainTextEdit):
    def resizeEvent(self, event):
        scroll = self.verticalScrollBar()
        at_bottom = scroll.value() >= scroll.maximum()
        super().resizeEvent(event)
        if at_bottom:
            scroll.setValue(scroll.maximum())


class ChatPage(QWidget):
    def __init__(self, service, online=None, open_connection=None):
        super().__init__()
        self.service = service
        self.online = online
        self._sent_id = self._sent_text = None
        self._rows: list[tuple] = []
        self._request_id = None
        self._view_generation = 0
        body = QVBoxLayout(self)
        body.setContentsMargins(24, 20, 24, 20)
        body.setSpacing(10)
        heading = QHBoxLayout()
        self.heading = label("모루와 채팅", "title")
        heading.addWidget(self.heading, 1)
        self.character = QComboBox()
        self.character.setAccessibleName("대화 캐릭터")
        self.character.setToolTip("캐릭터 그림과 대화 말투를 함께 선택해요.")
        for item in PROFILES:
            self.character.addItem(item.name, item.id)
            self.character.setItemData(self.character.count() - 1, item.description, 3)
        self.character.currentIndexChanged.connect(
            lambda: self._run(lambda: self.service.set_character(self.character.currentData()))
        )
        heading.addWidget(self.character)
        body.addLayout(heading)
        self.subtitle = label("오프라인 대화 · 선택한 친구와 함께해요.", "muted")
        body.addWidget(self.subtitle)
        row = QHBoxLayout()
        self.sessions = QComboBox()
        self.sessions.setAccessibleName("보관한 대화 선택")
        self.sessions.setMinimumContentsLength(12)
        self.sessions.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.sessions.activated.connect(self._select_session)
        row.addWidget(self.sessions, 1)
        row.addWidget(button("새 대화", lambda: self._run(self.service.new_session)))
        row.addWidget(button("대화 삭제", self._delete))
        body.addLayout(row)
        row = QHBoxLayout()
        self.history = QCheckBox("대화 보관")
        self.history.toggled.connect(
            lambda enabled: self._run(lambda: self.service.set_history(enabled))
        )
        row.addWidget(self.history)
        row.addWidget(label("끄면 새 메시지는 실행 중에만 표시해요.", "muted"), 1)
        body.addLayout(row)
        row = QHBoxLayout()
        self.examples = QComboBox()
        self.examples.setAccessibleName("지원 명령 예시")
        self.examples.addItems(
            [
                "오늘 할 일 보여줘",
                "오늘 얼마나 공부했어?",
                "25분 집중 시작",
                "타이머 일시정지",
                "할 일 추가: 자료구조 복습",
                "내일 오후 3시에 알고리즘 공부 추가해줘",
                "오늘 자료구조 복습 완료해줘",
                "캘린더 열어줘",
                "도움말",
            ]
        )
        self.examples.setMinimumContentsLength(14)
        self.examples.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        row.addWidget(self.examples, 1)
        row.addWidget(button("예시 넣기", self._example))
        self.older = button("이전 50개", self._load_more)
        row.addWidget(self.older)
        body.addLayout(row)
        self.transcript = ChatTranscript()
        self.transcript.setReadOnly(True)
        self.transcript.setMinimumHeight(100)
        self.transcript.setAccessibleName("대화 내용")
        self.transcript.setPlaceholderText(
            "오프라인 명령이나 예시를 사용해 보세요. AI 대화는 연결 테스트 후 직접 켤 수 있어요."
        )
        body.addWidget(self.transcript, 1)
        self.proposal, content = card("실행 전 확인 · 5분 후 만료")
        self.proposal.setAccessibleName("실행 전 확인 카드")
        self.proposal_source = label("AI 작업 제안 · 날짜·대상·범위를 확인한 뒤 적용하세요.")
        content.addWidget(self.proposal_source)
        self.proposal_summary = QPlainTextEdit()
        self.proposal_summary.setReadOnly(True)
        self.proposal_summary.setMinimumHeight(72)
        self.proposal_summary.setMaximumHeight(112)
        self.proposal_summary.setAccessibleName("AI 작업 제안 상세")
        content.addWidget(self.proposal_summary)
        self.choices = QComboBox()
        self.choices.setAccessibleName("대상 또는 변경 범위 선택")
        self.choices.setMinimumContentsLength(12)
        self.choices.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        content.addWidget(self.choices)
        row = QHBoxLayout()
        self.confirm_button = button("확인하고 적용", self._confirm, True)
        self.confirm_button.setToolTip("Ctrl+Enter로 현재 확인 카드를 적용해요.")
        row.addWidget(self.confirm_button)
        self.cancel_button = button("취소", lambda: self._run(self.service.cancel))
        row.addWidget(self.cancel_button)
        content.addLayout(row)
        body.addWidget(self.proposal)
        self.error = QPlainTextEdit()
        self.error.setReadOnly(True)
        self.error.setAccessibleName("명령 처리 오류")
        self.error.setMaximumHeight(82)
        self.error.hide()
        body.addWidget(self.error)
        if online is not None:
            row = QHBoxLayout()
            self.ai_enabled = QCheckBox("온라인 AI 대화")
            self.ai_enabled.toggled.connect(self._set_online)
            row.addWidget(self.ai_enabled)
            self.connection_button = button("키·연결 설정", open_connection)
            row.addWidget(self.connection_button)
            self.ai_cancel = button("요청 취소", online.cancel)
            row.addWidget(self.ai_cancel)
            body.addLayout(row)
            self.ai_actions = QCheckBox("AI 작업 제안 허용 · 변경은 확인 후 적용")
            self.ai_actions.toggled.connect(
                lambda allowed: self._run(lambda: online.set_actions_allowed(allowed))
            )
            body.addWidget(self.ai_actions)
            body.addWidget(
                label(
                    "AI는 현재 문장·캐릭터 설명을 보내며 API 비용이 발생할 수 있어요. "
                    "작업 제안 시 기준 날짜도 보내요. "
                    "이전 대화·일정·공부 기록·조회 결과는 보내지 않아요.",
                    "muted",
                )
            )
            self.ai_status = WrappedStatus()
            self.ai_status.setAccessibleName("온라인 대화 상태")
            body.addWidget(self.ai_status)
            online.changed.connect(self.refresh_online)
            online.completed.connect(self._online_finished)
        row = QHBoxLayout()
        self.input = CommandInput()
        self.input.setMaxLength(2000)
        self.input.setPlaceholderText("한 번에 한 명령을 입력하세요")
        self.input.setAccessibleName("채팅 명령 입력")
        self.input.returnPressed.connect(self._submit)
        row.addWidget(self.input, 1)
        self.send_button = button("보내기", self._submit, True)
        row.addWidget(self.send_button)
        body.addLayout(row)
        if online is not None:
            QWidget.setTabOrder(self.cancel_button, self.input)
            QWidget.setTabOrder(self.input, self.send_button)
        for title, keys, callback in (
            ("채팅 확인 카드 적용", ("Ctrl+Return", "Ctrl+Enter"), self.confirm_from_keyboard),
            ("채팅 확인 카드 취소", ("Escape",), self.cancel_from_keyboard),
        ):
            action = QAction(title, self)
            action.setAutoRepeat(False)
            action.setShortcuts([QKeySequence(key) for key in keys])
            action.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            action.triggered.connect(callback)
            self.addAction(action)
        service.changed.connect(self.refresh)
        if service.characters is not None:
            service.characters.changed.connect(self.refresh)
        self.refresh()
        if online is not None:
            self.refresh_online()

    def _run(self, callback):
        self.error.hide()
        try:
            callback()
            return True
        except SecretInputError as error:
            self.input.clear()
            self.error.setPlainText(
                self.service.voice.error(str(error), getattr(error, "dialogue_detail", None))
            )
        except ValueError as error:
            self.error.setPlainText(
                self.service.voice.error(str(error), getattr(error, "dialogue_detail", None))
            )
        except Exception:
            self.error.setPlainText(
                self.service.voice.error(
                    "저장 또는 조회하지 못했어요. 저장 공간을 확인하고 다시 시도해 주세요."
                )
            )
        finally:
            self.refresh()
        self.error.show()
        announce(self.error, "명령을 처리하지 못했어요. 오류 내용을 확인해 주세요.", urgent=True)
        return False

    def _submit(self):
        if self.input.composing:
            return
        if self.online is not None and self.online.enabled:
            text = self.input.text()

            def send():
                self._sent_id = self.online.send(text)
                self._sent_text = text

            self._run(send)
            self.input.setFocus()
            return
        self.send_button.setEnabled(False)
        try:
            if self._run(lambda: self.service.submit(self.input.text())):
                self.input.clear()
        finally:
            self.send_button.setEnabled(True)
            self.input.setFocus()

    def _confirm(self):
        if self.input.composing:
            return
        request_id = self._request_id
        choice = self.choices.currentData()
        choosing = bool(self.service.pending and self.service.pending.choices)
        self.confirm_button.setEnabled(False)
        try:
            self._run(
                lambda: (
                    self.service.choose(request_id, choice)
                    if choosing
                    else self.service.confirm(request_id)
                )
            )
        finally:
            self.confirm_button.setEnabled(True)

    def confirm_from_keyboard(self) -> None:
        if self.service.pending is not None and not self.input.composing:
            self.confirm_button.click()

    def cancel_from_keyboard(self) -> None:
        if self.service.pending is not None and not self.input.composing:
            self._run(self.service.cancel)
            self.input.setFocus()
        elif self.online is not None and self.online.kind == "chat" and not self.input.composing:
            self.online.cancel()

    def _select_session(self):
        key = self.sessions.currentData()
        if key:
            self._run(lambda: self.service.select_session(key))

    def _example(self):
        self.input.setText(self.examples.currentText())
        self.input.setFocus()

    def _delete(self):
        dialog = QMessageBox(self)
        dialog.setWindowTitle("대화 삭제")
        dialog.setText("대화 기록을 삭제할까요? 일정·할 일·공부 기록은 유지해요.")
        current = dialog.addButton("이 대화 삭제", QMessageBox.ButtonRole.DestructiveRole)
        all_button = dialog.addButton("모든 대화 삭제", QMessageBox.ButtonRole.DestructiveRole)
        cancel = dialog.addButton(QMessageBox.StandardButton.Cancel)
        dialog.setDefaultButton(cancel)
        dialog.exec()
        if dialog.clickedButton() in (current, all_button):
            self._run(lambda: self.service.delete_history(dialog.clickedButton() == all_button))

    def _timestamp(self, stamp: str) -> str:
        return (
            datetime.fromisoformat(stamp)
            .astimezone(self.service.planning.zone)
            .strftime("%m-%d %H:%M")
        )

    def _render(self, bottom: bool):
        self._view_generation += 1
        generation = self._view_generation
        old = self.transcript.verticalScrollBar().value()
        speakers = self.service.message_speakers([row[0] for row in self._rows])
        modes = self.service.message_modes([row[0] for row in self._rows])
        annotations = {
            row[0]: "AI · 계획/타이머 실행 없음 · "
            if row[1] == "assistant" and modes.get(row[0]) == "ai"
            else ""
            for row in self._rows
        }
        self.transcript.setPlainText(
            "\n\n".join(
                f"{'나' if role == 'user' else profile(speakers.get(message_id, 'moru')).name} · "
                f"{annotations[message_id]}"
                f"{self._timestamp(stamp)} KST\n{text}"
                for message_id, role, text, stamp in self._rows
            )
        )
        scroll = self.transcript.verticalScrollBar()
        scroll.setValue(scroll.maximum() if bottom else old)
        if bottom:
            # The confirmation card changes viewport height after this layout pass.
            QTimer.singleShot(
                0,
                self,
                lambda: self._scroll_end() if generation == self._view_generation else None,
            )
        self.older.setEnabled(bool(self._rows and self.service.messages(self._rows[0][0])))

    def _scroll_end(self):
        cursor = self.transcript.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.transcript.setTextCursor(cursor)
        self.transcript.ensureCursorVisible()
        # The outer scroll area needs another layout pass after the card appears.
        QTimer.singleShot(0, self, self._reveal_input)

    def _reveal_input(self):
        parent = self.parentWidget()
        while parent is not None:
            if isinstance(parent, QScrollArea):
                if self.service.pending is not None and self.service.pending.source == "ai":
                    parent.ensureWidgetVisible(self.proposal_source, 8, 8)
                    corner = self.confirm_button.mapTo(
                        parent.widget(), self.confirm_button.rect().bottomRight()
                    )
                    parent.ensureVisible(corner.x(), corner.y(), 8, 8)
                    return
                parent.ensureWidgetVisible(self.input, 8, 8)
                corner = self.input.mapTo(parent.widget(), self.input.rect().bottomRight())
                parent.ensureVisible(corner.x(), corner.y(), 8, 12)
            parent = parent.parentWidget()

    def _load_more(self):
        if not self._rows:
            return
        self._rows = self.service.messages(self._rows[0][0]) + self._rows
        self._render(False)

    def refresh(self):
        with QSignalBlocker(self.character):
            self.character.setCurrentIndex(self.character.findData(self.service.character_id))
        self.heading.setText(f"{self.service.voice.name}와 채팅")
        if self.service.characters is not None:
            active_name = profile(self.service.characters.active_id).name
            self.subtitle.setText(
                f"그림: {active_name} · 말투: {self.service.voice.name} · 오프라인 대화"
            )
        with QSignalBlocker(self.history), QSignalBlocker(self.sessions):
            self.history.setChecked(self.service.history_enabled)
            self.sessions.clear()
            self.sessions.addItem("새 대화", None)
            for key, title in self.service.sessions():
                self.sessions.addItem(title, key)
            index = self.sessions.findData(self.service.session_id)
            self.sessions.setCurrentIndex(max(0, index))
            self.sessions.setEnabled(self.service.history_enabled)
        self._rows = self.service.messages()
        self._render(True)
        pending = self.service.pending
        previous_request = self._request_id
        self._request_id = pending.request_id if pending else None
        self.proposal.setVisible(pending is not None)
        self.proposal_source.setVisible(pending is not None and pending.source == "ai")
        self.proposal_summary.setVisible(pending is not None and pending.source == "ai")
        self.proposal_summary.setPlainText(pending.summary if pending else "")
        self.choices.clear()
        if pending:
            for key, (title, _) in pending.choices.items():
                self.choices.addItem(title, key)
        self.choices.setVisible(bool(pending and pending.choices))
        self.confirm_button.setText(
            "선택한 내용으로 계속" if pending and pending.choices else "확인하고 적용"
        )
        if pending is not None and pending.request_id != previous_request:
            QTimer.singleShot(
                0,
                self,
                lambda: (
                    announce(
                        self.proposal,
                        "실행 전 확인할 내용이 있어요. "
                        "Ctrl+Enter로 적용하거나 Escape로 취소하세요.",
                    )
                    if self.service.pending is not None
                    else None
                ),
            )
        if self.online is not None:
            self.refresh_online()

    def _set_online(self, enabled: bool) -> None:
        self._run(lambda: self.online.set_enabled(enabled))
        self.refresh_online()

    def refresh_online(self) -> None:
        online = self.online
        with QSignalBlocker(self.ai_enabled):
            self.ai_enabled.setChecked(online.enabled)
        with QSignalBlocker(self.ai_actions):
            self.ai_actions.setChecked(online.actions_allowed)
        self.ai_actions.setEnabled(online.enabled)
        self.ai_cancel.setVisible(online.busy)
        self.send_button.setText("AI로 보내기" if online.enabled else "보내기")
        self.send_button.setEnabled(not (online.enabled and online.busy))
        self.input.setPlaceholderText(
            "AI에게 보낼 질문을 입력하세요" if online.enabled else "한 번에 한 명령을 입력하세요"
        )
        self.input.setAccessibleName("AI 질문 입력" if online.enabled else "채팅 명령 입력")
        text = online.status
        if online.usage is not None:
            values = [str(value) if value is not None else "확인 불가" for value in online.usage]
            text += f"\n입력 {values[0]} · 출력 {values[1]} 토큰 (계정 청구액 아님)"
        self.ai_status.setText(text)
        mode = "온라인 AI" if online.enabled else "오프라인 대화"
        if self.service.characters is not None:
            name = profile(self.service.characters.active_id).name
            self.subtitle.setText(f"그림: {name} · 말투: {self.service.voice.name} · {mode}")

    def _online_finished(self, request_id: str, success: bool) -> None:
        if request_id == self._sent_id:
            if (
                success or getattr(self.online, "last_error", "") == "sensitive"
            ) and self.input.text() == self._sent_text:
                self.input.setText("")
            self._sent_id = self._sent_text = None

    def hideEvent(self, event) -> None:
        if self.online is not None and (
            self.online.kind == "chat"
            or (self.service.pending is not None and self.service.pending.source == "ai")
        ):
            self.online.cancel()
        super().hideEvent(event)
