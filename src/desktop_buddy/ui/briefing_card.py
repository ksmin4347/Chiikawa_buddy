from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QFrame, QHBoxLayout, QScrollArea, QVBoxLayout, QWidget

from desktop_buddy.ui.common import button, label


class BriefingCard(QFrame):
    planning_requested = Signal()

    def __init__(self):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint)
        self.setObjectName("card")
        self.setWindowTitle("Desktop Buddy · 오늘의 브리핑")
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setMinimumWidth(300)
        self.resize(410, 360)
        body = QVBoxLayout(self)
        body.setContentsMargins(22, 20, 22, 20)
        body.addWidget(label("TODAY, AT YOUR PACE", "eyebrow"))
        self.heading = label("", "heading")
        self.summary = label("")
        self.details_area = QScrollArea()
        self.details_area.setWidgetResizable(True)
        self.details = label("", "muted")
        text_page = QWidget()
        text_body = QVBoxLayout(text_page)
        text_body.setContentsMargins(0, 0, 0, 0)
        text_body.addWidget(self.heading)
        text_body.addWidget(self.summary)
        text_body.addWidget(self.details)
        text_body.addStretch()
        self.details_area.setWidget(text_page)
        body.addWidget(self.details_area, 1)
        row = QHBoxLayout()
        row.addWidget(button("오늘의 계획 보기", self.open_planning, True))
        row.addWidget(button("닫기", self.hide))
        body.addLayout(row)

    def present(self, briefing, detailed: bool, anchor=None) -> None:
        self.heading.setText(briefing.heading)
        self.summary.setText(briefing.summary)
        self.details.setText(briefing.details)
        self.details.setVisible(detailed)
        self.resize(410, 360 if detailed else 255)
        screen = QGuiApplication.screenAt(anchor.center()) if anchor else None
        screen = screen or QGuiApplication.primaryScreen()
        area = screen.availableGeometry()
        self.resize(min(self.width(), area.width()), min(self.height(), area.height()))
        self.move(
            max(area.left(), area.right() - self.width() - 18),
            max(area.top(), area.bottom() - self.height() - 18),
        )
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.show()
        self.raise_()

    def open_planning(self) -> None:
        self.hide()
        self.planning_requested.emit()
