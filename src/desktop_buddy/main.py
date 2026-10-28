import argparse
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QMessageBox

from desktop_buddy.app import BuddyApplication
from desktop_buddy.core.metadata import APP_NAME, VERSION
from desktop_buddy.core.paths import data_directory
from desktop_buddy.database.store import Store
from desktop_buddy.services.single_instance import SingleInstance


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Desktop Buddy 데스크톱 캐릭터")
    parser.add_argument("--data-dir", type=Path, help="개발/테스트용 별도 데이터 폴더")
    parser.add_argument("--version", action="version", version=VERSION)
    args = parser.parse_args(argv)
    app = QApplication([sys.argv[0]])
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(VERSION)
    app.setOrganizationName("DesktopBuddy")
    app.setQuitOnLastWindowClosed(False)
    app.setStyle("Fusion")
    app.setFont(QFont("Malgun Gothic", 10))
    guard = None
    store = None
    try:
        directory = data_directory(args.data_dir)
        directory.mkdir(parents=True, exist_ok=True)
        guard = SingleInstance(directory)
        if not guard.acquire():
            return 0
        log_dir = directory / "logs"
        log_dir.mkdir(exist_ok=True)
        handler = RotatingFileHandler(
            log_dir / "app.log", maxBytes=512_000, backupCount=2, encoding="utf-8"
        )
        logging.basicConfig(
            level=logging.INFO,
            handlers=[handler],
            format="%(asctime)s %(levelname)s %(name)s %(message)s",
            force=True,
        )
        store = Store(directory / "buddy.db")
        controller = BuddyApplication(app, store, guard, directory)
    except Exception as error:
        logging.getLogger(__name__).error("Application startup failed (%s)", type(error).__name__)
        if store is not None:
            store.close()
        if guard is not None:
            guard.close()
        QMessageBox.critical(
            None,
            APP_NAME,
            "앱을 시작하지 못했어요. 데이터는 초기화하지 않았어요.\n"
            "저장 폴더의 쓰기 권한과 오류 로그를 확인해 주세요.\n"
            "새 버전에서 만든 데이터라면 앱을 업데이트해 주세요.",
        )
        return 1

    def report_exception(exc_type, _value, _traceback):
        logging.getLogger(__name__).error("Unhandled UI error (%s)", exc_type.__name__)
        controller.manager.statusBar().showMessage(
            "작업 중 문제가 생겼어요. 앱을 다시 실행하고 오류 로그를 확인해 주세요.", 15000
        )
        controller.manager.open_page()

    sys.excepthook = report_exception
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
