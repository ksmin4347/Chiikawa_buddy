"""Render only this app's widgets with Qt's offscreen renderer; no desktop capture."""

# ruff: noqa: E402 -- Configure offscreen Qt and source path before importing GUI modules.
import os
import sys
from datetime import datetime, time, timedelta
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from desktop_buddy.app import BuddyApplication
from desktop_buddy.database.store import Store
from desktop_buddy.models.planning import CalendarEvent, Task
from desktop_buddy.services.planning_service import PlanningService
from desktop_buddy.services.single_instance import SingleInstance


def settle():
    app.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QTest.qWait(60)
    app.processEvents()


app = QApplication([])
for font_file in ["malgun.ttf", "malgunbd.ttf"]:
    font_path = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / font_file
    if font_path.exists():
        QFontDatabase.addApplicationFont(str(font_path))
app.setFont(QFont("Malgun Gothic", 10))
app.setStyle("Fusion")
app.setQuitOnLastWindowClosed(False)
directory = ROOT / ".qa" / "preview-data"
directory.mkdir(parents=True, exist_ok=True)
guard = SingleInstance(directory)
assert guard.acquire()
store = Store(directory / "buddy.db")
# Fixtures exist only in this explicit QA database, never in the real user database.
planning = PlanningService(store)
day = planning.today()
if not planning.repository.records("task") and not planning.repository.records("event"):
    categories = planning.categories()
    for title, hour, completed, category in [
        ("자료구조 개념 복습", 9, True, categories[0].id),
        ("알고리즘 2문제 풀기", 11, False, categories[0].id),
        ("산책하며 잠깐 쉬기", 17, False, categories[1].id),
    ]:
        planning.save(
            Task(title, day, start_time=time(hour), completed=completed, category_id=category)
        )
    start = datetime.combine(day, time(14), planning.zone)
    planning.save(
        CalendarEvent(
            "주간 스터디",
            start,
            start + timedelta(hours=2),
            category_id=categories[0].id,
            recurrence="FREQ=WEEKLY;COUNT=8",
        )
    )
    planning.save(
        CalendarEvent(
            "과제 상담",
            start + timedelta(minutes=30),
            start + timedelta(hours=1),
            category_id=categories[2].id,
        )
    )
    midnight = datetime.combine(day, time(), planning.zone)
    planning.save(
        CalendarEvent(
            "과제 제출일",
            midnight,
            midnight + timedelta(days=1),
            all_day=True,
            category_id=categories[1].id,
        )
    )
controller = BuddyApplication(app, store, guard, Path("%LOCALAPPDATA%") / "DesktopBuddy")
controller.settings.update(theme="light")
output = ROOT / "docs" / "images"
output.mkdir(exist_ok=True)
controller.manager.resize(1120, 820)
for index, filename in [(0, "home.png"), (1, "today.png"), (2, "calendar-month.png")]:
    controller.manager.open_page(index)
    settle()
    assert controller.manager.grab().save(str(output / filename))
calendar_page = controller.manager.calendar_page
for mode, filename in [("week", "calendar-week.png"), ("day", "calendar-day.png")]:
    calendar_page.mode_combo.setCurrentIndex(calendar_page.mode_combo.findData(mode))
    settle()
    assert controller.manager.grab().save(str(output / filename))
controller.manager.open_page(3)
controller.manager.resize(960, 980)
settle()
assert controller.manager.grab().save(str(output / "settings.png"))
controller.settings.update(theme="dark")
controller.manager.open_page(0)
controller.manager.resize(1120, 820)
settle()
assert controller.manager.grab().save(str(output / "home-dark.png"))
calendar_page.mode_combo.setCurrentIndex(0)
controller.manager.open_page(2)
settle()
assert controller.manager.grab().save(str(output / "calendar-dark.png"))
controller.shutdown()
print("Rendered home, planning, calendar views, settings, and dark views from QA fixtures.")
