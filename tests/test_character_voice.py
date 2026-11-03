import re
import sqlite3

import pytest
from test_chat import chat as _chat_fixture
from test_chat_ui import chat_controller as _controller_fixture

from desktop_buddy.characters.dialogue_profiles import PROFILE_IDS
from desktop_buddy.characters.dialogue_voice import PHRASES, DialogueVoice
from desktop_buddy.core.settings import Settings
from desktop_buddy.database.store import Store
from desktop_buddy.services.chat_service import ChatService

voice_chat = _chat_fixture
voice_controller = _controller_fixture
CHARACTERS = ("chiikawa", "hachiware", "usagi")


def assert_usagi(text):
    assert re.match(r"^(?:ウ|우라|야하|이야하|푸루|하아|후웅)", text)
    assert " (" in text and text.endswith(")")
    assert not re.search(r"습니다|드립니다|주세요|했어요", text)


@pytest.mark.parametrize("character", CHARACTERS)
@pytest.mark.parametrize(
    "text",
    [
        "안녕!",
        "오늘 공부하기 싫어.",
        "나 오늘 시험 잘 봤어!",
        "오늘 계획 다 못 지켰어.",
        "나 좀 응원해 줘.",
        "고마워!",
    ],
)
def test_emotional_responses_use_selected_voice_without_actions(voice_chat, character, text):
    service = voice_chat
    service.set_character(character)
    reply = service.submit(text)
    assert reply.character_id == character
    assert not service.store.connection.execute("SELECT * FROM command_operations").fetchall()
    assert not service.planning.repository.records("task") and service.timer.status == "idle"
    if character == "usagi":
        assert_usagi(reply.text)
    else:
        assert not any(call in reply.text for call in ("우라!", "푸루야!", "하아?!"))
    assert not any(word in reply.text for word in ("말투를 적용", "항상 울", "분명 열심히 공부"))


@pytest.mark.parametrize("character", CHARACTERS)
def test_greeting_variety_and_opaque_technical_data(character):
    voice = DialogueVoice(lambda: character)
    assert len({voice.render("greeting") for _ in range(6)}) >= 2
    data = (
        "2026-11-10 08:00 · 25분\nC:\\Users\\a(b)\\공부했어요.py\n"
        + '```python\nx = (1, 2)\n```\n$env:TEST="값" · f(x)=x²'
    )
    for event in PHRASES:
        rendered = voice.render(event, details=data)
        assert data in rendered
        if character == "usagi":
            assert rendered.startswith(("우라", "야하", "이야하", "푸루", "하아", "후웅"))
            assert rendered.endswith(")")
    assert voice.render("greeting") != DialogueVoice(
        lambda: "hachiware" if character != "hachiware" else "chiikawa"
    ).render("greeting")


@pytest.mark.parametrize("character", CHARACTERS)
def test_commands_preserve_facts_and_confirm_then_store_styled_result(voice_chat, character):
    service = voice_chat
    service.set_character(character)
    title = "공부했어요.py (x=1) C:\\work\\a(b).py"
    proposal = service.submit("내일 15:00 " + title + " 일정 추가해줘")
    assert title in proposal.text and "2026-11-04 15:00" in proposal.text
    assert not service.planning.repository.records("event")
    result = service.confirm(proposal.request_id)
    assert title in result.text and service.planning.repository.records("event")[0].title == title
    saved = service.messages()[-1]
    assert saved[2] == result.text
    assert service.message_speakers([saved[0]])[saved[0]] == character
    if character == "usagi":
        assert result.text.startswith(("우라", "푸루", "야하")) and result.text.endswith(")")
    assert "이미" in service.confirm(proposal.request_id).text
    assert len(service.planning.repository.records("event")) == 1
    service.submit("25분 집중 시작")
    assert service.timer.planned == 1500
    preview = service.submit("타이머 중지")
    assert service.timer.status == "running"
    if character == "usagi":
        assert_usagi(preview.text)
    service.confirm(preview.request_id)
    assert service.timer.status == "idle"


def test_switch_invalidates_card_but_preserves_old_speaker_and_active_timer(voice_chat):
    service = voice_chat
    service.set_character("chiikawa")
    first = service.submit("안녕!")
    old_session = service.session_id
    old_rows = service.messages()
    proposal = service.submit("할 일 추가: 오래된 카드")
    service.set_character("usagi")
    assert service.pending is None and service.session_id == old_session
    with pytest.raises(ValueError, match="유효한"):
        service.confirm(proposal.request_id)
    assert service.messages()[1][2] == first.text
    assert service.message_speakers([old_rows[1][0]])[old_rows[1][0]] == "chiikawa"
    service.submit("안녕!")
    assert (
        service.message_speakers([service.messages()[-1][0]])[service.messages()[-1][0]] == "usagi"
    )
    service.submit("25분 집중 시작")
    session_id = service.timer.session_id
    service.set_character("hachiware")
    assert service.timer.status == "running" and service.timer.session_id == session_id
    restarted = ChatService(
        service.store, service.settings, service.planning, service.timer, service.statistics
    )
    assert restarted.character_id == "hachiware"
    assert restarted.messages() == service.messages()


def test_memory_only_speakers_and_profile_save_failure(voice_chat, monkeypatch):
    service = voice_chat
    service.set_history(False)
    service.set_character("chiikawa")
    service.submit("안녕!")
    first_id = service.messages()[-1][0]
    service.set_character("usagi")
    service.submit("안녕!")
    assert service.message_speakers([first_id])[first_id] == "chiikawa"
    assert not service.store.connection.execute("SELECT * FROM chat_messages").fetchall()
    preview = service.submit("할 일 추가: 보존")
    monkeypatch.setattr(
        service.store,
        "save_settings",
        lambda *a: (_ for _ in ()).throw(sqlite3.OperationalError("full")),
    )
    with pytest.raises(OSError):
        service.set_character("hachiware")
    assert service.character_id == "usagi" and service.pending.request_id == preview.request_id


def test_styled_success_rollback_and_retry_keep_db_truth(voice_chat, monkeypatch):
    service = voice_chat
    service.set_character("usagi")
    preview = service.submit("할 일 추가: 실패와 재시도")
    original = service.repository.append

    def fail_assistant(session_id, role, body, **kwargs):
        if role == "assistant":
            raise sqlite3.OperationalError("full")
        return original(session_id, role, body, **kwargs)

    monkeypatch.setattr(service.repository, "append", fail_assistant)
    with pytest.raises(sqlite3.OperationalError):
        service.confirm(preview.request_id)
    assert not service.planning.repository.records("task")
    assert not service.repository.completed(preview.request_id)
    assert service.pending and "저장 끝" not in service.messages()[-1][2]
    monkeypatch.setattr(service.repository, "append", original)
    assert_usagi(service.confirm(preview.request_id).text)
    assert len(service.planning.repository.records("task")) == 1


def test_profile_validation_keeps_old_default():
    for invalid in (None, "unknown", [], 123):
        assert Settings.from_mapping({"chat_character_id": invalid}).chat_character_id == "moru"
    for character in PROFILE_IDS:
        assert (
            Settings.from_mapping({"chat_character_id": character}).chat_character_id == character
        )


def test_schema5_backup_retains_original_dialogue_and_classifies_as_moru(qapp, tmp_path):
    path = tmp_path / "buddy.db"
    store = Store(path)
    with store.connection:
        store.connection.execute("ALTER TABLE chat_messages DROP COLUMN character_id")
        store.connection.execute("ALTER TABLE chat_messages DROP COLUMN profile_version")
        store.connection.execute("INSERT INTO chat_sessions VALUES ('old','2026-11-03','보존')")
        store.connection.execute(
            "INSERT INTO chat_messages(session_id,role,body,created_at) "
            "VALUES ('old','assistant','원래 답변 (C:\\work)','2026-11-03')"
        )
        store.connection.execute("PRAGMA user_version=5")
    store.close()
    migrated = Store(path)
    assert migrated.connection.execute("PRAGMA user_version").fetchone()[0] == 6
    assert migrated.connection.execute(
        "SELECT body,character_id,profile_version FROM chat_messages"
    ).fetchone() == ("원래 답변 (C:\\work)", "moru", 1)
    old = sqlite3.connect(list(tmp_path.glob("*.backup.db"))[0])
    assert old.execute("PRAGMA user_version").fetchone()[0] == 5
    old.close()
    migrated.close()


def test_character_dropdown_history_names_pet_voice_and_technical_errors(voice_controller, qapp):
    buddy, _ = voice_controller
    page = buddy.manager.chat_page
    buddy.manager.open_page(buddy.manager.CHAT_PAGE)
    page.character.setCurrentIndex(page.character.findData("chiikawa"))
    page.input.setText("안녕!")
    page.send_button.click()
    first_text = buddy.chat.messages()[-1][2]
    page.character.setCurrentIndex(page.character.findData("usagi"))
    page.input.setText("나 좀 응원해 줘.")
    page.send_button.click()
    assert (
        "치이카와 ·" in page.transcript.toPlainText()
        and "우사기 ·" in page.transcript.toPlainText()
    )
    assert first_text in page.transcript.toPlainText()
    assert_usagi(buddy.chat.messages()[-1][2])
    buddy.pet.react()
    assert_usagi(buddy.pet.bubble.text())
    page.input.setText("타이머 재개")
    page.send_button.click()
    assert_usagi(page.error.toPlainText())
    assert page.input.text() == "타이머 재개"
    buddy.manager.resize(720, 560)
    qapp.processEvents()
    assert page.input.geometry().bottom() <= page.height()
    page.character.setCurrentIndex(page.character.findData("hachiware"))
    assert not buddy.pet.bubble.isVisible()
    assert buddy.settings.current.chat_character_id == "hachiware"


def test_history_toggle_reply_keeps_current_character(voice_chat):
    voice_chat.set_character("usagi")
    voice_chat.set_history(False)
    assert voice_chat.reply.character_id == "usagi"
    assert_usagi(voice_chat.reply.text)


def test_commit_signal_cannot_relabel_already_composed_reply(voice_chat):
    service = voice_chat
    service.set_history(False)
    service.set_character("usagi")
    preview = service.submit("할 일 추가: 응답 캐릭터 보존")
    service.planning.changed.connect(lambda: service.set_character("hachiware"))
    reply = service.confirm(preview.request_id)
    assert service.character_id == "hachiware"
    assert reply.character_id == "usagi"
    assert_usagi(reply.text)
    last = service.messages()[-1]
    assert service.message_speakers([last[0]])[last[0]] == "usagi"


@pytest.mark.parametrize(
    "text",
    [
        "할 일 추가: " + "긴" * 201,
        "내일 15:00~14:00 회의 일정 추가해줘",
        "내일 회의 일정 추가해줘",
    ],
)
def test_usagi_validation_diagnostics_use_informal_speech(voice_chat, text):
    voice_chat.set_character("usagi")
    with pytest.raises(ValueError) as caught:
        voice_chat.submit(text)
    assert_usagi(voice_chat.voice.error(str(caught.value)))


def test_shutdown_cancels_delayed_welcome(voice_controller, monkeypatch):
    from PySide6.QtTest import QTest

    buddy, _ = voice_controller
    spoken = []
    monkeypatch.setattr(buddy.pet, "speak", lambda *a, **kw: spoken.append(a))
    buddy.shutdown()
    QTest.qWait(800)
    assert spoken == []
