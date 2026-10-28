"""Render only this app's widgets with Qt's offscreen renderer; no desktop capture."""

# ruff: noqa: E402 -- Configure offscreen Qt and source path before importing GUI modules.
import os
import sys
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication

from desktop_buddy.app import BuddyApplication
from desktop_buddy.database.store import Store
from desktop_buddy.services.single_instance import SingleInstance

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
controller = BuddyApplication(app, store, guard, Path("%LOCALAPPDATA%") / "DesktopBuddy")
controller.settings.update(theme="light")
output = ROOT / "docs" / "images"
output.mkdir(exist_ok=True)
controller.manager.open_page()
app.processEvents()
assert controller.manager.grab().save(str(output / "home.png"))
controller.manager.open_page(1)
controller.manager.resize(960, 980)
app.processEvents()
assert controller.manager.grab().save(str(output / "settings.png"))
controller.settings.update(theme="dark")
controller.manager.open_page(0)
controller.manager.resize(960, 760)
app.processEvents()
assert controller.manager.grab().save(str(output / "home-dark.png"))
controller.shutdown()
print("Rendered home, settings, and dark home from app widgets.")
