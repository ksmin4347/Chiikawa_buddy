import socket
import sqlite3
from dataclasses import replace
from datetime import date, datetime, time, timedelta

import pytest
from PySide6.QtTest import QSignalSpy
from test_focus import Clock, advance

from desktop_buddy.chat.parser import SecretInputError, parse
from desktop_buddy.database.focus_repository import FocusRepository
from desktop_buddy.database.migrations import SCHEMA_VERSION
from desktop_buddy.database.store import Store
from desktop_buddy.models.planning import Task
from desktop_buddy.services.chat_service import ChatService
from desktop_buddy.services.focus_timer import FocusTimerService
from desktop_buddy.services.planning_service import PlanningService
from desktop_buddy.services.settings_service import SettingsService
from desktop_buddy.services.study_statistics import StudyStatistics

TODAY = date(2026, 11, 3)


@pytest.fixture
def chat(qapp, tmp_path):
    store = Store(tmp_path / "buddy.db")
    planning = PlanningService(store)
    settings = SettingsService(store)
    clock = Clock(datetime(2026, 11, 3, 12, tzinfo=planning.zone))
    timer = FocusTimerService(store, settings, planning, clock)
    stats = StudyStatistics(store, planning, timer)
    service = ChatService(store, settings, planning, timer, stats)
    yield service
    timer.timer.stop()
    store.close()


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("안녕", "help"),
        ("오늘 할 일 보여줘", "list"),
        ("2026-11-10 일정 보여줘", "list"),
        ("오늘 얼마나 공부했어?", "study"),
        ("이번 주 공부 시간", "study"),
        ("전체 공부 시간", "study"),
        ("1시간 30분 집중 시작", "timer_start"),
        ("5분 짧은 휴식 시작", "timer_start"),
        ("15분 긴 휴식 시작", "timer_start"),
        ("타이머 일시정지", "timer_pause"),
        ("타이머 재개", "timer_resume"),
        ("타이머 중지", "timer_stop"),
        ("타이머 초기화", "timer_reset"),
        ("내 상태 알려줘", "status"),
        ("설정 열어줘", "navigate"),
        ("캘린더 열어줘", "navigate"),
        ("할 일 추가: 자료구조 복습", "add"),
        ("내일 오후 3시에 알고리즘 공부 추가해줘", "add"),
        ("내일 15:00~16:30 회의 일정 추가해줘", "add"),
        ("내일 종일 휴가 일정 추가해줘", "add"),
        ("오늘 자료구조 복습 완료해줘", "complete"),
        ("자료구조 복습 완료 취소해줘", "uncomplete"),
        ("오늘 할 일 자료구조 복습 삭제해줘", "delete"),
        ("오늘 자료구조 복습 내일로 옮겨줘", "move"),
    ],
)
def test_supported_commands(text, kind):
    assert parse(text, TODAY).kind == kind


@pytest.mark.parametrize(
    "text",
    [
        "정지",
        "타이머 정지",
        "0분 집중 시작",
        "1441분 집중 시작",
        "2026-02-30 일정 보여줘",
        "내일 5시 복습 추가해줘",
        "내일 오후 15시 복습 추가해줘",
        "내일 24:00 회의 일정 추가해줘",
        "내일 15:60 회의 일정 추가해줘",
        "내일 15:00~14:00 회의 일정 추가해줘",
        "이 할 일을 내일로 옮겨줘",
        "오늘 할 일 보여줘 그리고 전부 삭제해줘",
        "python 실행해줘",
        "모든 일정 삭제해줘",
        "a" * 2001,
        "안녕\n오늘 할 일 보여줘",
    ],
)
def test_ambiguous_or_invalid_commands_do_not_execute(chat, text):
    with pytest.raises(ValueError):
        chat.submit(text)
    assert not chat.planning.repository.records("task")
    assert chat.timer.status == "idle"
    assert not chat.store.connection.execute("SELECT * FROM command_operations").fetchall()


def test_choice_confirm_duplicate_and_cancel(chat):
    reply = chat.submit("내일 오후 3시에 알고리즘 공부 추가해줘")
    assert reply.choices and not chat.planning.repository.records("task")
    choice = next(value for value in reply.choices if value.label == "할 일")
    reply = chat.choose(reply.request_id, choice.key)
    assert "2026-11-04 15:00" in reply.text
    assert not chat.planning.repository.records("task")
    chat.confirm(reply.request_id)
    assert len(chat.planning.repository.records("task")) == 1
    assert "이미 처리" in chat.confirm(reply.request_id).text
    assert len(chat.planning.repository.records("task")) == 1
    chat.submit("할 일 추가: 취소할 내용")
    chat.cancel()
    assert len(chat.planning.repository.records("task")) == 1


def test_event_default_end_all_day_and_move(chat):
    reply = chat.submit("내일 23:30 회의 일정 추가해줘")
    assert "2026-11-05 00:30" in reply.text and "기본값" in reply.text
    chat.confirm(reply.request_id)
    event = chat.planning.repository.records("event")[0]
    assert event.end - event.start == timedelta(hours=1)
    reply = chat.submit("내일 회의 모레로 옮겨줘")
    chat.confirm(reply.request_id)
    event = chat.planning.repository.records("event")[0]
    assert event.start.date() == TODAY + timedelta(days=2)
    reply = chat.submit("내일 종일 휴가 일정 추가해줘")
    chat.confirm(reply.request_id)
    assert chat.planning.repository.records("event")[1].all_day
    with pytest.raises(ValueError, match="일정은"):
        chat.submit("내일 회의 일정 추가해줘")


def test_same_title_selects_exact_target(chat):
    ids = [chat.planning.save(Task("복습", TODAY)) for _ in range(2)]
    reply = chat.submit("오늘 복습 완료해줘")
    assert len(reply.choices) == 2
    choice = next(choice for choice in reply.choices if choice.label.startswith(f"#{ids[1]} "))
    preview = chat.choose(reply.request_id, choice.key)
    assert not any(task.completed for task in chat.planning.repository.records("task"))
    chat.confirm(preview.request_id)
    assert [task.completed for task in chat.planning.repository.records("task")] == [False, True]


def test_stale_deleted_expired_and_new_message_cards(chat):
    item_id = chat.planning.save(Task("복습", TODAY))
    preview = chat.submit("복습 완료해줘")
    chat.planning.save(replace(chat.planning.repository.get("task", item_id), title="다른 제목"))
    with pytest.raises(ValueError, match="바뀌었어요"):
        chat.confirm(preview.request_id)
    preview = chat.submit("다른 제목 삭제해줘")
    chat.planning.delete(chat.planning.occurrences(TODAY, TODAY + timedelta(days=1))[0])
    with pytest.raises(ValueError, match="바뀌었어요"):
        chat.confirm(preview.request_id)
    preview = chat.submit("할 일 추가: 만료")
    chat.timer.clock.advance(301)
    with pytest.raises(ValueError, match="만료"):
        chat.confirm(preview.request_id)
    preview = chat.submit("할 일 추가: 오래된 제안")
    chat.submit("오늘 할 일 보여줘")
    with pytest.raises(ValueError, match="유효한"):
        chat.confirm(preview.request_id)


@pytest.mark.parametrize("scope", ["one", "following", "all"])
def test_repeat_scope_move_preserves_deadline(chat, scope):
    deadline = datetime.combine(TODAY, time(19), chat.planning.zone)
    chat.planning.save(Task("복습", TODAY, due_at=deadline, recurrence="FREQ=DAILY;COUNT=5"))
    preview = chat.submit("내일 복습 모레로 옮겨줘")
    choice = next(
        value
        for value in preview.choices
        if value.label
        == {"one": "이번 항목만", "following": "이번부터 이후", "all": "전체 반복"}[scope]
    )
    preview = chat.choose(preview.request_id, choice.key)
    assert "마감" in preview.text and scope == chat.pending.intent.values["scope"]
    chat.confirm(preview.request_id)
    items = chat.planning.occurrences(TODAY, TODAY + timedelta(days=8), "task")
    assert len(items) == 5
    assert (
        not any(item.start.date() == TODAY + timedelta(days=1) for item in items)
        if scope != "all"
        else items[0].start.date() == TODAY + timedelta(days=1)
    )


def test_repeat_complete_one_then_delete_following(chat):
    chat.planning.save(Task("복습", TODAY, recurrence="FREQ=DAILY;COUNT=4"))
    preview = chat.submit("내일 복습 완료해줘")
    assert not preview.choices
    chat.confirm(preview.request_id)
    items = chat.planning.occurrences(TODAY, TODAY + timedelta(days=5))
    assert [item.completed for item in items] == [False, True, False, False]
    preview = chat.submit("내일 복습 삭제해줘")
    choice = next(value for value in preview.choices if value.label == "이번부터 이후")
    preview = chat.choose(preview.request_id, choice.key)
    chat.confirm(preview.request_id)
    assert len(chat.planning.occurrences(TODAY, TODAY + timedelta(days=5))) == 1


def test_offline_timers_queries_and_progress_protection(chat, monkeypatch):
    monkeypatch.setattr(socket, "create_connection", lambda *a, **kw: pytest.fail("network used"))
    chat.submit("25분 집중 시작")
    first = chat.timer.session_id
    with pytest.raises(ValueError, match="먼저 중지"):
        chat.submit("5분 짧은 휴식 시작")
    assert chat.timer.session_id == first
    advance(chat.timer, chat.timer.clock, 10)
    chat.submit("타이머 일시정지")
    assert chat.timer.status == "paused"
    chat.submit("타이머 재개")
    preview = chat.submit("타이머 중지")
    assert chat.timer.status == "running"
    advance(chat.timer, chat.timer.clock, 5)  # elapsed time alone must not stale the card.
    chat.confirm(preview.request_id)
    assert chat.timer.status == "idle" and chat.statistics.all_total() == 15
    assert "15초" in chat.submit("오늘 얼마나 공부했어?").text
    assert "대기" in chat.submit("내 상태 알려줘").text
    assert chat.submit("전체 공부 시간").text.startswith("전체 누적")


@pytest.mark.parametrize("stage", ["receipt", "history", "commit"])
@pytest.mark.parametrize("command", ["할 일 추가: 원자 저장", "25분 집중 시작"])
def test_atomic_rollback_database_runtime_signals_and_history(chat, monkeypatch, command, stage):
    changed = QSignalSpy(chat.planning.changed)
    updated = QSignalSpy(chat.timer.updated)
    if command.startswith("할 일"):
        preview = chat.submit(command)

        def run():
            return chat.confirm(preview.request_id)
    else:

        def run():
            return chat.submit(command)

    if stage == "receipt":
        monkeypatch.setattr(
            chat.executor.repository,
            "complete",
            lambda *args: (_ for _ in ()).throw(sqlite3.OperationalError("full")),
        )
    elif stage == "history":
        original = chat.repository.append

        def fail_assistant(session, role, body, **kwargs):
            if role == "assistant":
                raise sqlite3.OperationalError("full")
            return original(session, role, body, **kwargs)

        monkeypatch.setattr(chat.repository, "append", fail_assistant)
    else:
        with chat.store.connection:
            chat.store.connection.execute(
                "CREATE TABLE commit_failure (owner INTEGER REFERENCES tasks(id) "
                "DEFERRABLE INITIALLY DEFERRED)"
            )
        original = chat.executor.repository.complete

        def fail_commit(*args):
            original(*args)
            chat.store.connection.execute("INSERT INTO commit_failure VALUES (999999)")

        monkeypatch.setattr(chat.executor.repository, "complete", fail_commit)
    with pytest.raises(sqlite3.Error):
        run()
    assert not chat.planning.repository.records("task")
    assert chat.timer.status == "idle" and chat.timer.session_id is None
    assert not chat.store.connection.execute("SELECT * FROM focus_sessions").fetchall()
    assert not chat.store.connection.execute("SELECT * FROM command_operations").fetchall()
    assert not any("저장했어요" in row[2] or "시작했어요" in row[2] for row in chat.messages())
    assert changed.count() == 0 and updated.count() == 0


def test_nested_failure_swallowed_rolls_back_and_defers_signal(chat):
    spy = QSignalSpy(chat.planning.changed)
    with pytest.raises(RuntimeError, match="중첩"):
        with chat.store.transaction():
            chat.planning.save(Task("되돌릴 항목", TODAY))
            assert spy.count() == 0
            try:
                with chat.store.transaction():
                    raise ValueError("fail")
            except ValueError:
                pass
    assert not chat.planning.repository.records("task") and spy.count() == 0
    with chat.store.transaction():
        chat.planning.save(Task("성공 항목", TODAY))
        assert spy.count() == 0
    assert spy.count() == 1


def test_history_pages_restart_off_delete_and_no_pending_restore(chat):
    for _ in range(31):
        chat.submit("안녕")
    assert len(chat.messages()) == 50
    assert len(chat.messages(chat.messages()[0][0])) == 12
    preview = chat.submit("할 일 추가: 앱 재시작")
    restarted = ChatService(chat.store, chat.settings, chat.planning, chat.timer, chat.statistics)
    assert restarted.session_id == chat.session_id and restarted.pending is None
    with pytest.raises(ValueError):
        restarted.confirm(preview.request_id)
    stored = chat.store.connection.execute("SELECT COUNT(*) FROM chat_messages").fetchone()[0]
    chat.set_history(False)
    chat.submit("할 일 추가: 메모리 명령")
    chat.confirm(chat.pending.request_id)
    assert (
        chat.store.connection.execute("SELECT COUNT(*) FROM chat_messages").fetchone()[0] == stored
    )
    assert chat.store.connection.execute("SELECT kind FROM command_operations").fetchone() == (
        "add",
    )
    chat.set_history(True)
    assert not chat.messages()  # Memory-only messages are not backfilled.
    chat.submit("안녕")
    chat.delete_history(all_sessions=True)
    assert not chat.repository.sessions()
    assert len(chat.planning.repository.records("task")) == 1
    assert (
        chat.store.connection.execute("SELECT COUNT(*) FROM command_operations").fetchone()[0] == 1
    )


def test_key_canary_not_saved_and_literal_title_not_executed(chat):
    canary = "sk-test_" + "DO_NOT_PERSIST_0123456789"
    with pytest.raises(SecretInputError):
        chat.submit(canary)
    assert not chat.repository.sessions()
    assert canary.encode() not in chat.store.path.read_bytes()
    preview = chat.submit("할 일 추가: <script>DROP TABLE tasks</script>")
    chat.confirm(preview.request_id)
    assert chat.planning.repository.records("task")[0].title == "<script>DROP TABLE tasks</script>"


def test_v4_backup_migration_preserves_plans_and_focus(qapp, tmp_path):
    path = tmp_path / "buddy.db"
    store = Store(path)
    planning = PlanningService(store)
    planning.save(Task("보존", TODAY))
    with store.connection:
        repository = FocusRepository(store.connection)
        start = datetime.combine(TODAY, time(12), planning.zone)
        session_id = repository.create(
            "focus", 60, start, (None, "보존 분류", "#607d8b"), None, None, "공부 보존"
        )
        repository.progress(session_id, 10, 0)
        repository.segment(None, session_id, start, start + timedelta(seconds=10), 10)
        repository.finish(session_id, start + timedelta(seconds=10), False, "stopped")
        for table in (
            "calendar_links",
            "calendar_sources",
            "calendar_identity",
            "chat_messages",
            "chat_sessions",
            "command_operations",
        ):
            store.connection.execute(f"DROP TABLE {table}")
        store.connection.execute("PRAGMA user_version=4")
    store.close()
    migrated = Store(path)
    assert migrated.connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    assert PlanningService(migrated).repository.records("task")[0].title == "보존"
    assert FocusRepository(migrated.connection).all_total() == 10
    assert FocusRepository(migrated.connection).session(session_id)["task_title"] == "공부 보존"
    backup = list(tmp_path.glob("*.backup.db"))[0]
    old = sqlite3.connect(backup)
    assert old.execute("PRAGMA user_version").fetchone()[0] == 4
    assert old.execute("SELECT title FROM tasks").fetchone()[0] == "보존"
    assert old.execute("SELECT active_seconds FROM focus_sessions").fetchone()[0] == 10
    old.close()
    migrated.close()


@pytest.mark.parametrize("command", ["타이머 일시정지", "타이머 중지", "타이머 초기화"])
def test_existing_timer_failure_restores_segments_then_retry_once(chat, monkeypatch, command):
    chat.submit("25분 집중 시작")
    advance(chat.timer, chat.timer.clock, 10)
    session_id = chat.timer.session_id
    original = chat.executor.repository.complete
    if command != "타이머 일시정지":
        preview = chat.submit(command)
    monkeypatch.setattr(
        chat.executor.repository,
        "complete",
        lambda *args: (_ for _ in ()).throw(sqlite3.OperationalError("full")),
    )
    with pytest.raises(sqlite3.OperationalError):
        if command == "타이머 일시정지":
            chat.submit(command)
        else:
            chat.confirm(preview.request_id)
    assert chat.timer.status == "running" and chat.timer.session_id == session_id
    assert chat.timer.elapsed == 10 and chat.statistics.all_total() == 10
    assert chat.timer.repository.session(session_id)["ended_at"] is None
    monkeypatch.setattr(chat.executor.repository, "complete", original)
    advance(chat.timer, chat.timer.clock, 5)
    if command == "타이머 일시정지":
        chat.submit(command)
        assert chat.timer.status == "paused"
        chat.timer.stop()
    else:
        chat.confirm(preview.request_id)
        assert chat.timer.status == "idle"
        assert "이미 처리" in chat.confirm(preview.request_id).text
    assert chat.statistics.all_total() == 15


def test_history_switch_and_choice_staleness_cancel_cards(chat):
    chat.planning.save(Task("복습", TODAY))
    chat.planning.save(Task("복습", TODAY))
    preview = chat.submit("복습 완료해줘")
    chat.planning.save(Task("새 항목", TODAY))
    with pytest.raises(ValueError, match="바뀌었어요"):
        chat.choose(preview.request_id, preview.choices[0].key)
    preview = chat.submit("할 일 추가: 취소")
    chat.set_history(False)
    with pytest.raises(ValueError, match="유효한"):
        chat.confirm(preview.request_id)
    preview = chat.submit("할 일 추가: 새 대화로 취소")
    chat.new_session()
    with pytest.raises(ValueError, match="유효한"):
        chat.confirm(preview.request_id)
