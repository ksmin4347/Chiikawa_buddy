import logging

from PySide6.QtCore import QTimer
from PySide6.QtGui import QGuiApplication, QIcon
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from desktop_buddy.characters.animation import AnimationState, load_clips
from desktop_buddy.core.metadata import APP_NAME
from desktop_buddy.core.paths import asset_directory
from desktop_buddy.services.settings_service import SettingsService
from desktop_buddy.ui.management import ManagementWindow
from desktop_buddy.ui.pet import PetWindow
from desktop_buddy.ui.theme import apply_theme


class BuddyApplication:
    def __init__(self, app: QApplication, store, guard, data_dir):
        self.app = app
        self.store = store
        self.guard = guard
        self._closed = False
        self._theme = None
        self._position_ready = False
        self.settings = SettingsService(store)
        self.animation = AnimationState(load_clips(asset_directory() / "default_character"))
        self.pet = PetWindow(self.animation, self.settings.current)
        icon = QIcon(self.animation.frame)
        app.setWindowIcon(icon)
        self.manager = ManagementWindow(self.settings, self.animation.frame, data_dir)
        self.tray = QSystemTrayIcon(icon, app)
        self.tray.setToolTip(f"{APP_NAME} · 더블클릭하면 관리창")
        self.tray_menu = QMenu()
        self.tray_menu.addAction("관리창 열기", self.manager.open_page)
        self.show_action = self.tray_menu.addAction("캐릭터 숨기기", self.toggle_pet)
        self.tray_menu.addAction("캐릭터를 오른쪽 아래로 이동", self.reset_position)
        self.tray_menu.addSeparator()
        self.tray_menu.addAction("설정", lambda: self.manager.open_page(1))
        self.tray_menu.addSeparator()
        self.tray_menu.addAction("프로그램 종료", app.quit)
        self.tray.setContextMenu(self.tray_menu)
        self._tray_click = QTimer(app)
        self._tray_click.setSingleShot(True)
        self._tray_click.timeout.connect(self.toggle_pet)
        self.tray.activated.connect(self._tray_activated)
        self.pet.manage_requested.connect(self.manager.open_page)
        self.pet.quit_requested.connect(app.quit)
        self.pet.hide_requested.connect(self.hide_pet)
        self.pet.reset_requested.connect(self.reset_position)
        self.pet.position_changed.connect(lambda x, y: self.settings.update(x=x, y=y))
        self.pet.visibility_changed.connect(self._visibility_changed)
        self.manager.greet_requested.connect(self.greet)
        self.manager.find_requested.connect(self.find_pet)
        self.manager.toggle_pet_requested.connect(self.toggle_pet)
        self.manager.reset_requested.connect(self.reset_position)
        self.manager.quit_requested.connect(app.quit)
        self.manager.closing.connect(self._manager_closed)
        self.settings.changed.connect(self._settings_changed)
        self.settings.save_failed.connect(self._save_error)
        guard.activation_requested.connect(self._activate_existing)
        app.screenAdded.connect(self._screen_added)
        app.screenRemoved.connect(self.pet.ensure_visible_position)
        for screen in QGuiApplication.screens():
            self._screen_added(screen)
        app.aboutToQuit.connect(self.shutdown)
        self._settings_changed(self.settings.current)
        current = self.settings.current
        if current.x is None or current.y is None:
            self.reset_position(show=False)
        else:
            self.pet.move(*self.pet.safe_position(current.x, current.y))
            self.pet.ensure_visible_position()
        self._position_ready = True
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.show()
        if current.show_on_start or not self.tray.isVisible():
            self.pet.show()
            QTimer.singleShot(
                700, lambda: self.pet.speak("반가워요! 나를 더블클릭하면 관리창이 열려요.")
            )

    def _screen_added(self, screen) -> None:
        screen.availableGeometryChanged.connect(self.pet.ensure_visible_position)
        screen.geometryChanged.connect(self.pet.ensure_visible_position)
        screen.logicalDotsPerInchChanged.connect(self.pet.ensure_visible_position)
        if self.pet.isVisible():
            self.pet.ensure_visible_position()

    def _settings_changed(self, settings) -> None:
        if settings.theme != self._theme:
            self._theme = settings.theme
            apply_theme(self.app, settings.theme)
        self.pet.apply_settings(settings)
        if self._position_ready:
            self.pet.ensure_visible_position()

    def _visibility_changed(self, visible: bool) -> None:
        self.manager.set_pet_visible(visible)
        self.show_action.setText("캐릭터 숨기기" if visible else "캐릭터 다시 표시")

    def _tray_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._tray_click.stop()
            self.manager.open_page()
        elif reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._tray_click.start(QApplication.doubleClickInterval())

    def _save_error(self, message: str) -> None:
        logging.getLogger(__name__).warning("Settings save failed")
        self.manager.save_status.setText(message)
        self.manager.statusBar().showMessage(message, 15000)
        self.manager.open_page(1)
        self.manager.refresh(self.settings.current)
        self.manager.save_status.setText(message)

    def _manager_closed(self) -> None:
        if not self.tray.isVisible():
            self.find_pet()

    def _activate_existing(self) -> None:
        self.find_pet()
        self.manager.open_page()

    def find_pet(self) -> None:
        self.pet.ensure_visible_position()
        self.pet.show()
        self.pet.raise_()

    def hide_pet(self) -> None:
        self.pet.hide()
        if not self.tray.isVisible():
            self.manager.open_page()

    def toggle_pet(self) -> None:
        if self.pet.isVisible():
            self.hide_pet()
        else:
            self.find_pet()

    def greet(self) -> None:
        self.find_pet()
        self.pet.react()

    def reset_position(self, show: bool = True) -> None:
        area = QGuiApplication.primaryScreen().availableGeometry()
        self.pet.move(
            *self.pet.safe_position(
                area.right() - self.pet.width() - 24, area.bottom() - self.pet.height() - 16
            )
        )
        self.pet.position_changed.emit(self.pet.x(), self.pet.y())
        if show:
            self.find_pet()

    def shutdown(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._tray_click.stop()
        self.pet._click_timer.stop()
        self.pet.animation_timer.stop()
        self.settings.update(x=self.pet.x(), y=self.pet.y())
        self.pet.hide()
        self.pet.bubble.close()
        self.manager.hide()
        self.tray.hide()
        self.guard.close()
        self.store.close()
