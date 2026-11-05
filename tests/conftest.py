import gc
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    for name in ("malgun.ttf", "malgunbd.ttf"):
        font = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / name
        if font.exists():
            QFontDatabase.addApplicationFont(str(font))
    app.setFont(QFont("Malgun Gothic", 10))
    app.setQuitOnLastWindowClosed(False)
    yield app


@pytest.fixture(autouse=True)
def release_test_windows():
    """Do not retain old test windows when a later test reapplies the global theme."""
    yield
    app = QApplication.instance()
    if app is not None:
        for widget in app.topLevelWidgets():
            widget.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        gc.collect()
