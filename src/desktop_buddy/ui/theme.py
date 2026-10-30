from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication


def apply_theme(app: QApplication, theme: str) -> None:
    dark = theme == "dark"
    c = {
        "bg": "#202824" if dark else "#faf9f6",
        "side": "#19211d" if dark else "#f1f3ed",
        "card": "#2a342e" if dark else "#ffffff",
        "text": "#edf1e9" if dark else "#293e34",
        "muted": "#b6c3b9" if dark else "#617168",
        "line": "#46534a" if dark else "#dce3d9",
        "accent": "#b6d8bf" if dark else "#315f49",
        "soft": "#374d40" if dark else "#e4efdf",
        "hero": "#3d3a31" if dark else "#f6eedf",
    }
    palette = QPalette()
    for role, color in [
        (QPalette.ColorRole.Window, c["bg"]),
        (QPalette.ColorRole.Base, c["card"]),
        (QPalette.ColorRole.Text, c["text"]),
        (QPalette.ColorRole.WindowText, c["text"]),
        (QPalette.ColorRole.Button, c["card"]),
        (QPalette.ColorRole.ButtonText, c["text"]),
        (QPalette.ColorRole.Highlight, c["soft"]),
        (QPalette.ColorRole.HighlightedText, c["text"]),
    ]:
        palette.setColor(role, QColor(color))
    app.setPalette(palette)
    app.setStyleSheet(
        """
        QMainWindow, QWidget#page, QScrollArea, QStackedWidget {{ background: {bg}; }}
        QWidget {{ color: {text}; font-family: 'Malgun Gothic'; font-size: 14px; }}
        QFrame#sidebar {{ background: {side}; border-right: 1px solid {line}; }}
        QFrame#card {{ background: {card}; border: 1px solid {line}; border-radius: 16px; }}
        QFrame#hero {{ background: {hero}; border: 0; border-radius: 20px; }}
        QLabel {{ background: transparent; }}
        QLabel[kind='title'] {{ font-size: 28px; font-weight: 700; }}
        QLabel[kind='countdown'] {{ font-size: 64px; font-weight: 700; }}
        QLabel[kind='heading'] {{ font-size: 18px; font-weight: 700; }}
        QLabel[kind='muted'] {{ color: {muted}; font-size: 13px; }}
        QLabel[kind='eyebrow'] {{ color: {accent}; font-size: 12px; font-weight: 700; }}
        QPushButton {{ background: {card}; border: 1px solid {line};
            border-radius: 9px; padding: 10px 15px; min-height: 20px; font-weight: 600; }}
        QPushButton:hover {{ background: {soft}; }}
        QPushButton:focus {{ border: 2px solid {accent}; }}
        QPushButton[primary='true'] {{ background: #315f49; color: white; border: 0; }}
        QPushButton:disabled, QPushButton[primary='true']:disabled {{
            background: {side}; color: {muted}; border: 1px solid {line}; }}
        QSpinBox:disabled, QComboBox:disabled, QDateEdit:disabled {{ color: {muted}; }}
        QPushButton[nav='true'] {{ text-align: left; border: 0; background: transparent;
            padding: 12px 16px; }}
        QPushButton[nav='true']:checked {{ background: {soft}; }}
        QLineEdit, QSpinBox, QComboBox {{ background: {bg}; border: 1px solid {line};
            border-radius: 8px; padding: 8px; min-height: 22px; }}
        QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{ border: 2px solid {accent}; }}
        QCheckBox {{ spacing: 10px; min-height: 30px; }}
        QCheckBox::indicator {{ width: 19px; height: 19px; }}
        QToolTip, QMenu {{ color: {text}; background: {card}; border: 1px solid {line}; }}
        QMenu::item {{ padding: 9px 24px; }}
        QMenu::item:selected {{ background: {soft}; }}
        QDialog {{ background: {bg}; }}
        QTableWidget, QListWidget, QGraphicsView, QTextEdit {{
            background: {card}; color: {text}; border: 1px solid {line};
            alternate-background-color: {bg}; gridline-color: {line}; }}
        QTableWidget::item, QListWidget::item {{ padding: 6px; }}
        QTableWidget::item:selected, QListWidget::item:selected {{
            background: {soft}; color: {text}; }}
        QHeaderView::section {{ background: {side}; color: {muted}; padding: 7px;
            border: 0; border-bottom: 1px solid {line}; }}
        QDateEdit, QTimeEdit, QDateTimeEdit {{ background: {bg}; color: {text};
            border: 1px solid {line}; border-radius: 7px; padding: 7px; }}
        QFrame#dayCell {{ background: {card}; border: 0; }}
        QFrame#dayCell[outside='true'] {{ background: {bg}; }}
        QFrame#dayCell[selected='true'] {{ background: {soft}; }}
        QPushButton#dayNumber {{ padding: 0 2px; min-height: 0; border: 0;
            text-align: left; background: transparent; font-size: 12px; }}
        QPushButton#dayNumber[sunday='true'] {{ color: #bb514b; }}
        QPushButton#dayNumber[saturday='true'] {{ color: #5478b0; }}
        QPushButton#calendarEntry, QPushButton#calendarMore {{ padding: 0 3px;
            min-height: 0; border: 0; border-radius: 3px; background: transparent;
            text-align: left; font-size: 12px; font-weight: 400; }}
        QPushButton#calendarEntry:hover, QPushButton#calendarMore:hover {{ background: {soft}; }}
        QProgressBar {{ background: {soft}; color: {text}; border: 0; border-radius: 6px;
            text-align: center; font-size: 11px; }}
        QProgressBar::chunk {{ background: #7fa98a; border-radius: 6px; }}
        QScrollArea {{ border: 0; }}
        QScrollBar:vertical {{ background: {bg}; width: 10px; }}
        QScrollBar::handle:vertical {{ background: {line}; border-radius: 5px; min-height: 30px; }}
    """.format(**c)
    )
