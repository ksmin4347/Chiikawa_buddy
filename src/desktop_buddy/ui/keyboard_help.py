from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from desktop_buddy.ui.common import fit_window, label

PAGE_NAMES = (
    "홈",
    "오늘의 계획",
    "캘린더",
    "집중 타이머",
    "공부 통계",
    "생활·브리핑",
    "채팅",
    "캐릭터",
    "설정",
)


class KeyboardHelp(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("먼작귀 · 키보드 안내")
        self.resize(540, 480)
        body = QVBoxLayout(self)
        body.addWidget(label("키보드로 함께해요", "heading"))
        body.addWidget(label("단축키는 관리창 안에서만 작동해요.", "muted"))
        rows = [
            *((f"Ctrl+{index}", name + " 열기") for index, name in enumerate(PAGE_NAMES, 1)),
            ("Ctrl+L", "채팅을 열고 입력칸으로 이동"),
            ("Ctrl+Enter", "채팅의 현재 확인 카드 적용 · 대상 선택은 다음 확인으로 진행"),
            ("Escape", "채팅 확인 카드 취소 · 열린 대화상자 닫기"),
            ("Tab / Shift+Tab", "다음 / 이전 조작 항목으로 이동"),
            ("Space", "초점이 있는 버튼 누르기"),
            ("Enter", "채팅 보내기 · 빠른 할 일 추가 · 편집창 저장"),
            ("F1", "이 안내 열기"),
        ]
        self.table = QTableWidget(len(rows), 2)
        self.table.setAccessibleName("키보드 단축키 목록")
        self.table.setHorizontalHeaderLabels(["키", "동작"])
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setColumnWidth(0, 156)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().sectionResized.connect(
            lambda *_args: self.table.resizeRowsToContents()
        )
        for index, row in enumerate(rows):
            for column, text in enumerate(row):
                item = QTableWidgetItem(text)
                item.setToolTip(text)
                self.table.setItem(index, column, item)
        self.table.resizeRowsToContents()
        body.addWidget(self.table, 1)
        body.addWidget(label("한글을 조합하는 중에는 채팅 적용·취소 단축키를 쉬어요.", "muted"))
        buttons = QDialogButtonBox()
        self.close_button = buttons.addButton("닫기", QDialogButtonBox.ButtonRole.RejectRole)
        buttons.rejected.connect(self.reject)
        body.addWidget(buttons)
        self.close_button.setFocus()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        fit_window(self)
