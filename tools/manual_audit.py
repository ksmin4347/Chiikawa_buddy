"""Launch an isolated native window for genuine mouse/keyboard audit; no real user DB."""

# ruff: noqa: E402 -- Set source path before importing this application.
import json
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from PySide6.QtCore import QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from desktop_buddy.app import BuddyApplication
from desktop_buddy.database.store import Store
from desktop_buddy.services.single_instance import SingleInstance

app = QApplication([])
app.setApplicationName("Desktop Buddy Audit")
app.setQuitOnLastWindowClosed(False)
app.setStyle("Fusion")
app.setFont(QFont("Malgun Gothic", 10))
directory = ROOT / ".qa" / "manual-audit" / uuid.uuid4().hex
directory.mkdir(parents=True)
guard = SingleInstance(directory)
assert guard.acquire()
store = Store(directory / "buddy.db")
controller = BuddyApplication(app, store, guard, directory)
controller.settings.update(focus_minutes=1)
controller.manager.setWindowTitle("Desktop Buddy · 감사용 테스트 창")
controller.pet.setWindowTitle("Desktop Buddy · 감사용 캐릭터")
controller.manager.open_page(1)
(ROOT / ".qa" / "manual-audit-current.json").write_text(
    json.dumps({"directory": str(directory)}, ensure_ascii=False), encoding="utf-8"
)
# Prevent an abandoned audit process from remaining after a disconnected UI session.
QTimer.singleShot(20 * 60 * 1000, controller.quit)
raise SystemExit(app.exec())
