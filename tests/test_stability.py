"""Cross-service durability and bounded local resource regressions."""

import os
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from PySide6.QtNetwork import QLocalSocket
from test_focus import Clock, advance

from desktop_buddy.database.store import Store
from desktop_buddy.models.planning import CalendarEvent
from desktop_buddy.services.focus_timer import FocusTimerService
from desktop_buddy.services.notification_service import NotificationService
from desktop_buddy.services.planning_service import PlanningService
from desktop_buddy.services.settings_service import SettingsService
from desktop_buddy.services.single_instance import SingleInstance

ROOT = Path(__file__).resolve().parents[1]
WORKER = r"""
import os,sys
from datetime import datetime,UTC
from pathlib import Path
sys.path[:0]=[str(Path.cwd()/'src'),str(Path.cwd()/'tests')]
from PySide6.QtCore import QCoreApplication
from test_focus import Clock,advance
from desktop_buddy.database.store import Store
from desktop_buddy.models.planning import Task
from desktop_buddy.services.focus_timer import FocusTimerService
from desktop_buddy.services.planning_service import PlanningService
from desktop_buddy.services.settings_service import SettingsService
app=QCoreApplication([])
store=Store(Path(sys.argv[1]))
planning=PlanningService(store)
clock=Clock(datetime(2026,11,17,1,tzinfo=UTC))
if sys.argv[2]=='transaction':
    planning.save(Task('committed',clock.now().date()))
    with store.transaction():
        planning.save(Task('uncommitted',clock.now().date()))
        os._exit(17)
timer=FocusTimerService(store,SettingsService(store),planning,clock)
timer.start(minutes=60)
advance(timer,clock,7)
if sys.argv[2]=='graceful':
    timer.shutdown()
    store.close()
    raise SystemExit(0)
os._exit(17)
"""


def worker(path, mode):
    return subprocess.run(
        [sys.executable, "-B", "-c", WORKER, str(path), mode],
        cwd=ROOT,
        env=dict(os.environ, QT_QPA_PLATFORM="offscreen"),
        capture_output=True,
        timeout=30,
        check=False,
    )


@pytest.mark.parametrize("mode,seconds,exit_code", [("graceful", 7, 0), ("crash", 5, 17)])
def test_real_process_restart_excludes_downtime_and_preserves_checkpoint(
    qapp, tmp_path, mode, seconds, exit_code
):
    path = tmp_path / "buddy.db"
    result = worker(path, mode)
    assert result.returncode == exit_code, result.stderr.decode(errors="replace")
    for _ in range(2):
        store = Store(path)
        clock = Clock(datetime(2026, 11, 20, 1, tzinfo=ZoneInfo("UTC")))
        timer = FocusTimerService(store, SettingsService(store), PlanningService(store), clock)
        assert timer.status == "paused" and timer.elapsed == seconds
        assert store.connection.execute("PRAGMA quick_check").fetchone() == ("ok",)
        assert not store.connection.execute("PRAGMA foreign_key_check").fetchall()
        store.close()
    store = Store(path)
    clock = Clock(datetime(2026, 11, 21, 1, tzinfo=ZoneInfo("UTC")))
    timer = FocusTimerService(store, SettingsService(store), PlanningService(store), clock)
    timer.resume()
    advance(timer, clock, 3)
    timer.stop()
    assert (
        store.connection.execute("SELECT SUM(active_seconds) FROM focus_sessions").fetchone()[0]
        == seconds + 3
    )
    store.close()


def test_actual_process_crash_rolls_back_uncommitted_planning(qapp, tmp_path):
    path = tmp_path / "buddy.db"
    assert worker(path, "transaction").returncode == 17
    store = Store(path)
    assert [item.title for item in PlanningService(store).repository.records("task")] == [
        "committed"
    ]
    assert store.connection.execute("PRAGMA quick_check").fetchone() == ("ok",)
    store.close()


def reminder_services(path):
    store = Store(path)
    planning, settings = PlanningService(store), SettingsService(store)
    now = datetime(2026, 11, 17, 10, tzinfo=planning.zone)
    return store, planning, settings, now


def test_notification_joins_outer_transaction_and_rolls_back_cursor(qapp, tmp_path):
    store, planning, settings, now = reminder_services(tmp_path / "buddy.db")
    planning.save(CalendarEvent("meeting", now, now + timedelta(hours=1), reminder_minutes=0))
    notifier = NotificationService(planning, settings, lambda: now)
    received = []
    notifier.due.connect(received.append)
    with pytest.raises(RuntimeError, match="abort"):
        with store.transaction():
            notifier.poll()
            assert not received
            raise RuntimeError("abort")
    assert notifier.last_check is None
    assert store.connection.execute("SELECT COUNT(*) FROM notification_log").fetchone()[0] == 0
    notifier.poll()
    assert len(received) == 1
    store.close()


def test_notification_outer_commit_and_real_connection_reopen_never_duplicate(qapp, tmp_path):
    path = tmp_path / "buddy.db"
    store, planning, settings, now = reminder_services(path)
    for i in range(30):
        planning.save(CalendarEvent(str(i), now, now + timedelta(hours=1), reminder_minutes=0))
    notifier = NotificationService(planning, settings, lambda: now)
    received = []
    notifier.due.connect(received.append)
    with store.transaction():
        notifier.poll()
        assert not received
    assert len(received) == 1 and len(received[0]) == 30
    store.close()
    store, planning, settings, now = reminder_services(path)
    notifier = NotificationService(planning, settings, lambda: now)
    notifier.due.connect(received.append)
    notifier.poll()
    assert len(received) == 1
    assert store.connection.execute("SELECT COUNT(*) FROM notification_log").fetchone()[0] == 30
    store.close()


def settle(qapp, condition, seconds=3):
    until = time.monotonic() + seconds
    while not condition() and time.monotonic() < until:
        qapp.processEvents()
        time.sleep(0.005)
    qapp.processEvents()
    assert condition()


@pytest.fixture
def channel(qapp, tmp_path):
    guard = SingleInstance(tmp_path)
    assert guard.acquire()
    yield guard
    guard.close()
    qapp.processEvents()


def connect_client(guard):
    client = QLocalSocket()
    client.connectToServer(guard.name)
    assert client.waitForConnected(1000)
    return client


def test_idle_activation_socket_has_deadline(qapp, channel, monkeypatch):
    monkeypatch.setattr(SingleInstance, "CLIENT_TIMEOUT_MS", 40, raising=False)
    client = connect_client(channel)
    settle(qapp, lambda: bool(channel._clients))
    settle(qapp, lambda: not channel._clients)
    assert not channel._buffers
    client.abort()


def test_activation_channel_caps_silent_clients(qapp, channel, monkeypatch):
    monkeypatch.setattr(SingleInstance, "MAX_CLIENTS", 2, raising=False)
    monkeypatch.setattr(SingleInstance, "CLIENT_TIMEOUT_MS", 10000, raising=False)
    clients = [connect_client(channel) for _ in range(3)]
    try:
        settle(qapp, lambda: len(channel._clients) >= 2)
        for _ in range(5):
            qapp.processEvents()
        assert len(channel._clients) == 2
    finally:
        for client in clients:
            client.abort()


def test_fragmented_valid_activation_acknowledges_once_and_cleans_up(qapp, channel):
    received = []
    channel.activation_requested.connect(lambda: received.append(True))
    client = connect_client(channel)
    client.write(b"sh")
    client.flush()
    settle(qapp, lambda: any(value == b"sh" for value in channel._buffers.values()))
    assert not received
    client.write(b"ow")
    client.flush()
    settle(qapp, lambda: bool(received))
    settle(qapp, lambda: not channel._clients)
    assert received == [True] and not channel._buffers
    assert client.readAll().data() == b"ok"
    client.abort()


@pytest.mark.parametrize("payload", [b"wrong", b"show" + b"x" * 200000])
def test_invalid_activation_is_bounded_and_never_activates(qapp, channel, payload):
    received = []
    channel.activation_requested.connect(lambda: received.append(True))
    client = connect_client(channel)
    client.write(payload)
    client.flush()
    settle(qapp, lambda: client.state() == QLocalSocket.LocalSocketState.UnconnectedState)
    assert not received and not channel._buffers and not channel._deadlines


def test_channel_close_cleans_clients_and_can_be_reacquired(qapp, channel, tmp_path):
    client = connect_client(channel)
    settle(qapp, lambda: bool(channel._clients))
    channel.close()
    channel.close()
    assert not channel._clients and not channel._buffers and not channel._deadlines
    replacement = SingleInstance(tmp_path)
    assert replacement.acquire()
    replacement.close()
    client.abort()


def test_repeated_application_lifecycles_release_owned_objects():
    result = subprocess.run(
        [sys.executable, "-B", "tools/stability_smoke.py", "--cycles", "3"],
        cwd=ROOT,
        env=dict(os.environ, QT_QPA_PLATFORM="offscreen"),
        capture_output=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr.decode(errors="replace")


def test_timer_checkpoint_failure_still_releases_app_lock_and_closes_store(
    qapp, tmp_path, monkeypatch
):
    from test_credentials import MemoryVault

    from desktop_buddy.app import BuddyApplication
    from desktop_buddy.services.api_key_service import ApiKeyService

    guard = SingleInstance(tmp_path)
    assert guard.acquire()
    path = tmp_path / "buddy.db"
    buddy = BuddyApplication(
        qapp,
        Store(path),
        guard,
        tmp_path,
        show_onboarding=False,
        api_keys=ApiKeyService(MemoryVault()),
    )
    clock = Clock()
    buddy.focus_timer.clock = clock
    buddy.focus_timer.timer.stop()
    buddy.focus_timer.start(minutes=60)
    advance(buddy.focus_timer, clock, 7)

    def fail(_):
        raise sqlite3.OperationalError("QA checkpoint failure")

    monkeypatch.setattr(buddy.focus_timer.repository, "save_state", fail)
    buddy.shutdown()
    buddy.shutdown()
    with pytest.raises(sqlite3.ProgrammingError):
        buddy.store.connection.execute("SELECT 1")
    replacement = SingleInstance(tmp_path)
    assert replacement.acquire()
    replacement.close()
    store = Store(path)
    timer = FocusTimerService(store, SettingsService(store), PlanningService(store), clock)
    assert timer.status == "paused" and timer.elapsed == 5
    store.close()
