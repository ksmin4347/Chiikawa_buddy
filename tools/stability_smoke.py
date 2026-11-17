"""Repeat source-app lifecycle checks in a fresh QA folder, without real keys or HTTP."""

# ruff: noqa: E402 -- Configure Qt and source imports before constructing widgets.
import argparse
import ctypes
import gc
import json
import os
import sys
import threading
import time
import uuid
import weakref
from datetime import UTC, datetime, timedelta
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from PySide6.QtCore import QCoreApplication, QEvent, QTimer
from PySide6.QtWidgets import QApplication

from desktop_buddy.app import BuddyApplication
from desktop_buddy.database.store import Store
from desktop_buddy.models.planning import Task
from desktop_buddy.services.api_key_service import ApiKeyService
from desktop_buddy.services.settings_service import SettingsService
from desktop_buddy.services.single_instance import SingleInstance


class NoCredentials:
    def exists(self) -> bool:
        return False

    def read(self) -> str:
        raise AssertionError("This QA run must not read credentials")

    def write(self, _value) -> None:
        raise AssertionError("This QA run must not write credentials")

    def delete(self) -> None:
        raise AssertionError("This QA run must not delete credentials")


class NoNetwork:
    def __init__(self):
        self.calls = 0

    async def run(self, *_args, **_kwargs):
        self.calls += 1
        raise AssertionError("This QA run must not request HTTP")


class ManualClock:
    def __init__(self):
        self.wall = datetime.now(UTC)
        self.mono = 0.0

    def now(self) -> datetime:
        return self.wall

    def monotonic(self) -> float:
        return self.mono

    def advance(self, seconds: float) -> None:
        self.wall += timedelta(seconds=seconds)
        self.mono += seconds


def process_metrics() -> dict:
    if sys.platform != "win32":
        return {}
    from ctypes import wintypes

    class MemoryCounters(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("PageFaultCount", wintypes.DWORD),
            *[
                (name, ctypes.c_size_t)
                for name in (
                    "PeakWorkingSetSize",
                    "WorkingSetSize",
                    "QuotaPeakPagedPoolUsage",
                    "QuotaPagedPoolUsage",
                    "QuotaPeakNonPagedPoolUsage",
                    "QuotaNonPagedPoolUsage",
                    "PagefileUsage",
                    "PeakPagefileUsage",
                )
            ],
        ]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.GetProcessHandleCount.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel.GetProcessHandleCount.restype = wintypes.BOOL
    psapi.GetProcessMemoryInfo.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(MemoryCounters),
        wintypes.DWORD,
    ]
    psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
    process = kernel.GetCurrentProcess()
    memory, handles = MemoryCounters(), wintypes.DWORD()
    memory.cb = ctypes.sizeof(memory)
    if not psapi.GetProcessMemoryInfo(process, ctypes.byref(memory), memory.cb):
        raise ctypes.WinError(ctypes.get_last_error())
    if not kernel.GetProcessHandleCount(process, ctypes.byref(handles)):
        raise ctypes.WinError(ctypes.get_last_error())
    return {"working_set_bytes": memory.WorkingSetSize, "handles": handles.value}


def drain(app: QApplication) -> None:
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def delete_qa_windows(app: QApplication) -> None:
    for window in app.topLevelWidgets():
        window.deleteLater()
    drain(app)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cycles", type=int, default=12)
    args = parser.parse_args()
    if not 3 <= args.cycles <= 100:
        parser.error("Use 3~100 lifecycle cycles.")
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    app.setStyle("Fusion")
    directory = ROOT / ".qa" / "stability" / uuid.uuid4().hex
    directory.mkdir(parents=True)
    path = directory / "buddy.db"
    clock = ManualClock()
    rows, refs, asset_refs = [], [], []
    baseline_timers = len(app.findChildren(QTimer))
    wall_start, cpu_start = time.perf_counter(), time.process_time()
    report = {"platform": app.platformName(), "cycles": rows, "passed": False}
    try:
        for cycle in range(1, args.cycles + 1):
            guard = SingleInstance(directory)
            assert guard.acquire()
            store = Store(path)
            SettingsService(store).update(notifications_enabled=False, show_on_start=False)
            keys = ApiKeyService(NoCredentials())
            buddy = BuddyApplication(
                app,
                store,
                guard,
                directory,
                show_onboarding=False,
                api_keys=keys,
                online_client=NoNetwork(),
            )
            # Run initial queued layouts, as the real application's event loop does.
            drain(app)
            drain(app)
            refs.append(weakref.ref(buddy))
            asset_refs.extend(
                weakref.ref(item) for item in (buddy.pet, buddy.characters, buddy.animation)
            )
            buddy.focus_timer.timer.stop()
            buddy.focus_timer.clock = clock
            if cycle == 1:
                buddy.planning.save(Task("QA preserved task", buddy.planning.today()))
                buddy.focus_timer.start(minutes=60)
            else:
                assert buddy.focus_timer.status == "paused"
                assert buddy.focus_timer.elapsed == (cycle - 1) * 3
                buddy.focus_timer.resume()
            clock.advance(3)
            buddy.focus_timer.tick()
            buddy.shutdown()
            buddy.shutdown()
            assert buddy.online.client.calls == 0
            assert all(
                not timer.isActive()
                for timer in (
                    buddy.focus_timer.timer,
                    buddy.notifications.timer,
                    buddy.companion.timer,
                    buddy.briefing.timer,
                    buddy.behavior.timer,
                    buddy.celebration.timer,
                    buddy._tray_click,
                    buddy.pet.animation_timer,
                )
            )
            keys.deleteLater()
            guard.deleteLater()
            delete_qa_windows(app)
            del buddy, guard, store, keys
            gc.collect()
            drain(app)
            check = Store(path)
            assert check.connection.execute("PRAGMA quick_check").fetchone() == ("ok",)
            assert not check.connection.execute("PRAGMA foreign_key_check").fetchall()
            assert check.connection.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 1
            assert (
                check.connection.execute(
                    "SELECT SUM(active_seconds) FROM focus_sessions"
                ).fetchone()[0]
                == cycle * 3
            )
            check.close()
            del check
            row = {
                "cycle": cycle,
                "retained_controllers": sum(ref() is not None for ref in refs),
                "retained_asset_owners": sum(ref() is not None for ref in asset_refs),
                "application_timers": len(app.findChildren(QTimer)),
                "buddy_threads": len(
                    [t for t in threading.enumerate() if t.name.startswith("buddy-")]
                ),
                **process_metrics(),
            }
            rows.append(row)
            print(json.dumps(row), flush=True)
            assert row["application_timers"] == baseline_timers
            assert row["retained_controllers"] == 0 and row["buddy_threads"] == 0
            assert row["retained_asset_owners"] == 0
            clock.advance(3600)  # Simulated downtime must never become focus credit.
        report["passed"] = True
        return 0
    finally:
        report.update(
            wall_seconds=time.perf_counter() - wall_start,
            cpu_seconds=time.process_time() - cpu_start,
        )
        (directory / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(str(directory / "report.json"), flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
