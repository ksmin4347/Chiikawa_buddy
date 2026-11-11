"""Render and inspect only the app's widgets, using an isolated QA database.

Set QT_QPA_PLATFORM=windows to check native Qt. QT_SCALE_FACTOR is a multiplier
of the screen's existing scale; report.json records the effective device ratio.
"""

# ruff: noqa: E402 -- Configure Qt and project imports before loading widgets.
import argparse
import asyncio
import json
import os
import re
import sys
import uuid
from datetime import datetime, time, timedelta
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QAbstractButton, QApplication, QComboBox, QLabel, QScrollArea, QWidget

from desktop_buddy.app import BuddyApplication
from desktop_buddy.database.store import Store
from desktop_buddy.models.online import OnlineResult, ToolProposal
from desktop_buddy.models.planning import CalendarEvent, Task
from desktop_buddy.services.api_key_service import ApiKeyService
from desktop_buddy.services.single_instance import SingleInstance
from desktop_buddy.ui.api_key_dialog import ApiKeyDialog
from desktop_buddy.ui.common import fit_window
from desktop_buddy.ui.keyboard_help import KeyboardHelp
from desktop_buddy.ui.planning_dialogs import CategoryDialog, ItemEditor, ScopeDialog


class QAKeyVault:
    """Memory-only data for rendering; never access Windows credentials."""

    value = None
    fail = False

    def exists(self):
        if self.fail:
            raise RuntimeError("QA storage unavailable")
        return self.value is not None

    def write(self, value):
        self.value = value

    def read(self):
        raise AssertionError("The key UI must not read the saved secret")

    def delete(self):
        self.value = None


class QAResponses:
    """UI states only: no HTTP or credential reads."""

    delay = 0.001
    proposal = None

    async def run(self, vault, request, cancelled, *, before_send=None):
        if before_send is not None:
            await before_send()
        await asyncio.sleep(self.delay)
        return OnlineResult(
            text="OK" if request.kind == "test" else "가짜 AI 답변으로 만든 화면이에요.",
            input_tokens=7,
            output_tokens=9,
            proposal=self.proposal if request.allow_actions else None,
        )


app = QApplication([])
for font_file in ("malgun.ttf", "malgunbd.ttf"):
    QFontDatabase.addApplicationFont(
        str(Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / font_file)
    )
app.setFont(QFont("Malgun Gothic", 10))
app.setStyle("Fusion")
app.setQuitOnLastWindowClosed(False)
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("tag", nargs="?", default="current")
parser.add_argument("--width", type=int, default=720)
parser.add_argument("--height", type=int, default=560)
parser.add_argument(
    "--ignore-work-area", action="store_true", help="Offscreen-only larger viewport"
)
args = parser.parse_args()
if not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", args.tag) or args.width < 1 or args.height < 1:
    parser.error("Use a simple tag and positive window dimensions.")
if args.ignore_work_area and app.platformName() != "offscreen":
    parser.error("--ignore-work-area is only available with the offscreen platform.")
tag = args.tag
output = ROOT / ".qa" / ("ui-audit-" + tag)
output.mkdir(parents=True, exist_ok=True)
data = output / uuid.uuid4().hex
data.mkdir()
guard = SingleInstance(data)
assert guard.acquire()
store = Store(data / "buddy.db")
qa_vault, qa_responses = QAKeyVault(), QAResponses()
buddy = BuddyApplication(
    app,
    store,
    guard,
    data,
    show_onboarding=False,
    api_keys=ApiKeyService(qa_vault),
    online_client=qa_responses,
)
buddy.settings.update(briefing_enabled=False, sleep_enabled=False, quiet_enabled=False)
buddy.characters.select("hachiware")
planning = buddy.planning
day = planning.today()
planning.save_category("가나다라마바사아자차카타파하" * 2, "#4e8061")
category_id = next(c.id for c in planning.categories() if c.name.startswith("가나다"))
planning.save(
    Task(
        "아주 긴 할 일 제목을 줄바꿈 없이 끝까지 확인할 수 있을까 " * 4,
        day,
        category_id=category_id,
        recurrence="FREQ=DAILY;COUNT=3",
        due_at=datetime.combine(day, time(18), planning.zone),
    )
)
for i in range(6):
    start = datetime.combine(day, time(9), planning.zone) + timedelta(minutes=15 * i)
    planning.save(
        CalendarEvent(
            "겹치는 일정 " + str(i) + " 긴 제목 " * 5,
            start,
            start + timedelta(hours=1),
            category_id=category_id,
        )
    )
for i in range(4):
    start = datetime.combine(day, time(), planning.zone)
    planning.save(
        CalendarEvent(
            "종일 일정 " + str(i) + " 긴 제목 " * 12, start, start + timedelta(days=1), all_day=True
        )
    )


def settle():
    app.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QTest.qWait(30)
    app.processEvents()


def describe(w):
    text = w.text() if hasattr(w, "text") else w.currentText() if isinstance(w, QComboBox) else ""
    return w.metaObject().className() + ":" + str(text)[:95]


def inspect(root):
    report = {
        "size": [root.width(), root.height()],
        "minimum": [root.minimumSizeHint().width(), root.minimumSizeHint().height()],
        "overflow": [],
        "clipped": [],
        "overlap": [],
    }
    for w in root.findChildren(QScrollArea):
        if w.isVisible() and w.widget() is not None:
            if w.horizontalScrollBar().maximum() > 0:
                report["overflow"].append(
                    [describe(w.widget()), w.widget().width(), w.viewport().width()]
                )
    for w in root.findChildren(QAbstractButton):
        if w.isVisible() and w.width() + 2 < w.minimumSizeHint().width():
            report["clipped"].append([describe(w), w.width(), w.minimumSizeHint().width()])
    for w in root.findChildren(QLabel):
        if w.isVisible() and w.wordWrap() and w.heightForWidth(w.width()) > w.height() + 3:
            report["clipped"].append(
                [describe(w), "height", w.height(), w.heightForWidth(w.width())]
            )
    for container in [root, *root.findChildren(QWidget)]:
        if not container.isVisible() or container.layout() is None:
            continue
        children = [
            child
            for child in container.findChildren(QWidget)
            if child.parentWidget() is container and child.isVisible() and not child.isWindow()
        ]
        for index, first in enumerate(children):
            for second in children[index + 1 :]:
                if first.geometry().intersects(second.geometry()):
                    report["overlap"].append([describe(first), describe(second)])
    return report


results = {
    "platform": app.platformName(),
    "dpr": app.devicePixelRatio(),
    "configured_style": "Fusion",
    "pages": {},
}
for theme in ("light", "dark"):
    buddy.settings.update(theme=theme)
    for index, name in enumerate(
        (
            "home",
            "today",
            "calendar",
            "focus",
            "statistics",
            "companion",
            "chat",
            "character",
            "settings",
        )
    ):
        buddy.manager.open_page(index)
        buddy.manager.resize(args.width, args.height)
        if not args.ignore_work_area:
            buddy.manager.ensure_visible_position()
        settle()
        report = inspect(buddy.manager)
        page = buddy.manager.pages.currentWidget()
        if isinstance(page, QScrollArea):
            page.verticalScrollBar().setValue(0)
        settle()
        buddy.manager.grab().save(str(output / f"{theme}-{name}.png"))
        if isinstance(page, QScrollArea):
            page.verticalScrollBar().setValue(page.verticalScrollBar().maximum())
            settle()
            buddy.manager.grab().save(str(output / f"{theme}-{name}-bottom.png"))
        results["pages"][theme + "-" + name] = report
    for mode in ("week", "day"):
        buddy.manager.open_page(2)
        buddy.manager.resize(args.width, args.height)
        if not args.ignore_work_area:
            buddy.manager.ensure_visible_position()
        buddy.manager.calendar_page.mode_combo.setCurrentIndex(
            buddy.manager.calendar_page.mode_combo.findData(mode)
        )
        settle()
        results["pages"][theme + "-calendar-" + mode] = inspect(buddy.manager)
        buddy.manager.grab().save(str(output / f"{theme}-calendar-{mode}.png"))
    buddy.manager.calendar_page.mode_combo.setCurrentIndex(0)
    buddy.manager.open_page(buddy.manager.CHAT_PAGE)
    buddy.chat.submit("할 일 추가: 긴 입력 후 확인 카드")
    buddy.manager.resize(args.width, args.height)
    if not args.ignore_work_area:
        buddy.manager.ensure_visible_position()
    settle()
    results["pages"][theme + "-chat-confirm"] = inspect(buddy.manager)
    buddy.manager.grab().save(str(output / f"{theme}-chat-confirm.png"))
    buddy.chat.cancel()
    help_dialog = KeyboardHelp(buddy.manager)
    help_dialog.show()
    settle()
    results["pages"][theme + "-keyboard-help"] = inspect(help_dialog)
    help_dialog.grab().save(str(output / f"{theme}-keyboard-help.png"))
    help_dialog.close()
    help_dialog.deleteLater()
    vault = qa_vault
    vault.value, vault.fail = None, False
    buddy.online.reset()
    key_dialog = ApiKeyDialog(buddy.api_keys, buddy.manager, online=buddy.online)
    key_dialog.show()
    for phase in ("empty", "masked", "saved", "error"):
        canary = "not-a-real-key-for-qa-render"
        if phase == "masked":
            key_dialog.input.setText(canary)
            assert canary not in key_dialog.input.displayText()
        elif phase == "saved":
            key_dialog.save()
            assert not key_dialog.input.text()
        elif phase == "error":
            vault.fail = True
            key_dialog.refresh_status()
        settle()
        assert canary not in key_dialog.status.text()
        results["pages"][theme + "-api-key-" + phase] = inspect(key_dialog)
        key_dialog.grab().save(str(output / f"{theme}-api-key-{phase}.png"))
    vault.fail = False
    key_dialog.refresh_status()
    qa_responses.delay = 2
    key_dialog.test_connection()
    settle()
    results["pages"][theme + "-api-test-wait"] = inspect(key_dialog)
    key_dialog.grab().save(str(output / f"{theme}-api-test-wait.png"))
    buddy.online.cancel()
    for _ in range(600):
        settle()
        if not buddy.online.busy:
            break
    assert not buddy.online.busy
    qa_responses.delay = 0.001
    key_dialog.test_connection()
    for _ in range(600):
        settle()
        if not buddy.online.busy:
            break
    assert buddy.online.ready
    results["pages"][theme + "-api-test-ready"] = inspect(key_dialog)
    key_dialog.grab().save(str(output / f"{theme}-api-test-ready.png"))
    key_dialog.close()
    key_dialog.deleteLater()
    buddy.manager.navigate(buddy.manager.CHAT_PAGE)
    buddy.online.set_enabled(True)
    qa_responses.delay = 2
    buddy.manager.chat_page.input.setText("가짜 AI 화면 검증")
    buddy.manager.chat_page.send_button.click()
    settle()
    results["pages"][theme + "-ai-wait"] = inspect(buddy.manager)
    buddy.manager.grab().save(str(output / f"{theme}-ai-wait.png"))
    buddy.online.cancel()
    for _ in range(600):
        settle()
        if not buddy.online.busy:
            break
    assert not buddy.online.busy
    qa_responses.delay = 0.001
    buddy.manager.chat_page.send_button.click()
    for _ in range(600):
        settle()
        if not buddy.online.busy:
            break
    results["pages"][theme + "-ai-reply"] = inspect(buddy.manager)
    buddy.manager.grab().save(str(output / f"{theme}-ai-reply.png"))
    buddy.online.set_actions_allowed(True)
    qa_responses.proposal = ToolProposal(
        "propose_add_item",
        json.dumps(
            dict(
                title=("AI 검증용 긴 제목 " * 12).strip(),
                item_kind="task",
                day=day.isoformat(),
                start=None,
                end=None,
                all_day=False,
            ),
            ensure_ascii=False,
        ),
    )
    buddy.manager.chat_page.input.setText("복습을 추가해 줘")
    buddy.manager.chat_page.send_button.click()
    for _ in range(600):
        settle()
        if not buddy.online.busy:
            break
    assert buddy.chat.pending is not None and buddy.chat.pending.source == "ai"
    for state in ("ai-proposal", "ai-applied"):
        if state == "ai-applied":
            buddy.manager.chat_page.confirm_button.click()
            assert buddy.chat.pending is None
        settle()
        results["pages"][theme + "-" + state] = inspect(buddy.manager)
        buddy.manager.grab().save(str(output / f"{theme}-{state}.png"))
    for _ in range(2):
        planning.save(Task("AI 동명 대상", day))
    qa_responses.proposal = ToolProposal(
        "propose_change_item",
        json.dumps(
            dict(
                action="delete",
                item_kind="task",
                day=day.isoformat(),
                title="AI 동명 대상",
                destination=None,
            ),
            ensure_ascii=False,
        ),
    )
    buddy.manager.chat_page.input.setText("AI 동명 대상을 삭제해 줘")
    buddy.manager.chat_page.send_button.click()
    for _ in range(600):
        settle()
        if not buddy.online.busy:
            break
    assert buddy.chat.pending is not None and buddy.chat.pending.choices
    results["pages"][theme + "-ai-choices"] = inspect(buddy.manager)
    buddy.manager.grab().save(str(output / f"{theme}-ai-choices.png"))
    buddy.online.set_actions_allowed(False)
    assert buddy.chat.pending is None
    qa_responses.proposal = None
    buddy.online.set_enabled(False)
    buddy.online.reset()
    vault.value = None

buddy.settings.update(theme="light")
results["logo"] = {
    "visible": buddy.manager.logo.isVisible(),
    "rect": str(buddy.manager.logo.geometry()),
    "pixmap": str(buddy.manager.logo.pixmap().size()),
}
buddy.manager.logo.grab().save(str(output / "logo.png"))
record = planning.repository.records("task")[0]
for name, dialog in [
    ("task-editor", ItemEditor(planning, record, planning.save, buddy.manager)),
    (
        "event-editor",
        ItemEditor(planning, planning.repository.records("event")[0], planning.save, buddy.manager),
    ),
    ("categories", CategoryDialog(planning, buddy.manager)),
    (
        "scope",
        ScopeDialog(
            planning.occurrences(day, day + timedelta(days=1), "task")[0], parent=buddy.manager
        ),
    ),
]:
    dialog.show()
    dialog.resize(540, 480)
    fit_window(dialog)
    settle()
    results["pages"][name] = inspect(dialog)
    dialog.grab().save(str(output / f"{name}.png"))
    dialog.close()
    dialog.deleteLater()
buddy.settings.update(character_selection_done=False)
buddy._show_character_picker()
settle()
results["pages"]["picker"] = inspect(buddy.picker)
buddy.picker.grab().save(str(output / "picker.png"))
buddy.picker.reject()
buddy.shutdown()
(output / "report.json").write_text(
    json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
)
print(json.dumps(results, ensure_ascii=False))
assert all(
    not page["overflow"] and not page["clipped"] and not page["overlap"]
    for page in results["pages"].values()
)
