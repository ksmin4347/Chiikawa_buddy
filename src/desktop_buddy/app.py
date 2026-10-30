import logging

from PySide6.QtCore import QTimer
from PySide6.QtGui import QGuiApplication, QIcon
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from desktop_buddy.characters.animation import AnimationState, load_clips
from desktop_buddy.core.metadata import APP_NAME
from desktop_buddy.core.paths import asset_directory
from desktop_buddy.services.focus_timer import FocusTimerService
from desktop_buddy.services.notification_service import NotificationService
from desktop_buddy.services.planning_service import PlanningService
from desktop_buddy.services.power_events import PowerEventFilter
from desktop_buddy.services.settings_service import SettingsService
from desktop_buddy.services.study_statistics import StudyStatistics
from desktop_buddy.ui.management import ManagementWindow
from desktop_buddy.ui.mini_timer import MiniTimer
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
        self.planning = PlanningService(store)
        self.focus_timer = FocusTimerService(store, self.settings, self.planning)
        self.statistics = StudyStatistics(store, self.planning, self.focus_timer)
        self.power_filter = PowerEventFilter(self.focus_timer)
        app.installNativeEventFilter(self.power_filter)
        self.animation = AnimationState(load_clips(asset_directory() / "default_character"))
        self.pet = PetWindow(self.animation, self.settings.current)
        icon = QIcon(self.animation.frame)
        app.setWindowIcon(icon)
        self.manager = ManagementWindow(
            self.settings,
            self.animation.frame,
            data_dir,
            self.planning,
            self.focus_timer,
            self.statistics,
        )
        self.mini_timer = MiniTimer(self.pet, self.focus_timer, self.settings)
        self.focus_timer.updated.connect(self._timer_updated)
        self.focus_timer.phase_finished.connect(self._phase_finished)
        self.focus_timer.error.connect(
            lambda text: self.manager.statusBar().showMessage(text, 15000)
        )
        self.tray = QSystemTrayIcon(icon, app)
        self.tray.setToolTip(f"{APP_NAME} · 더블클릭하면 관리창")
        self.tray_menu = QMenu()
        self.tray_menu.addAction("관리창 열기", self.manager.open_page)
        self.show_action = self.tray_menu.addAction("캐릭터 숨기기", self.toggle_pet)
        self.tray_menu.addAction("캐릭터를 오른쪽 아래로 이동", self.reset_position)
        self.tray_menu.addSeparator()
        self.tray_menu.addAction(
            "집중 타이머", lambda: self.manager.open_page(self.manager.FOCUS_PAGE)
        )
        self.tray_menu.addAction(
            "공부 통계", lambda: self.manager.open_page(self.manager.STATISTICS_PAGE)
        )
        self.tray_menu.addAction("설정", lambda: self.manager.open_page(self.manager.SETTINGS_PAGE))
        self.tray_menu.addSeparator()
        self.tray_menu.addAction("프로그램 종료", self.quit)
        self.tray.setContextMenu(self.tray_menu)
        self._tray_click = QTimer(app)
        self._tray_click.setSingleShot(True)
        self._tray_click.timeout.connect(self.toggle_pet)
        self.tray.activated.connect(self._tray_activated)
        self.pet.manage_requested.connect(self.manager.open_page)
        self.pet.timer_requested.connect(lambda: self.manager.open_page(self.manager.FOCUS_PAGE))
        self.pet.quit_requested.connect(self.quit)
        self.pet.hide_requested.connect(self.hide_pet)
        self.pet.reset_requested.connect(self.reset_position)
        self.pet.position_changed.connect(lambda x, y: self.settings.update(x=x, y=y))
        self.pet.visibility_changed.connect(self._visibility_changed)
        self.manager.greet_requested.connect(self.greet)
        self.manager.find_requested.connect(self.find_pet)
        self.manager.toggle_pet_requested.connect(self.toggle_pet)
        self.manager.reset_requested.connect(self.reset_position)
        self.manager.quit_requested.connect(self.quit)
        self.manager.closing.connect(self._manager_closed)
        self.settings.changed.connect(self._settings_changed)
        self.settings.save_failed.connect(self._save_error)
        guard.activation_requested.connect(self._activate_existing)
        app.screenAdded.connect(self._screen_added)
        app.screenRemoved.connect(self.pet.ensure_visible_position)
        for screen in QGuiApplication.screens():
            self._screen_added(screen)
        self.planning.task_completed.connect(self._task_completed)
        self.notifications = NotificationService(
            self.planning, self.settings, is_focusing=lambda: self.focus_timer.snapshot.focusing
        )
        self.notifications.due.connect(self._notify)
        self.notifications.failed.connect(
            lambda text: self.manager.statusBar().showMessage(text, 15000)
        )
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

        self.notifications.start()
        self._timer_updated(self.focus_timer.snapshot)
        self.focus_timer.start_clock()

    def _timer_updated(self, snapshot) -> None:
        base = (
            ("focus" if snapshot.phase == "focus" else "break")
            if snapshot.status == "running"
            else "idle"
        )
        self.animation.set_base(base)
        if self.settings.current.reduce_motion and self.animation.state != base:
            self.animation.play(self.animation.base_state)

    def _phase_finished(self, result) -> None:
        if not self.settings.current.reduce_motion:
            self.animation.play("complete")
        text = (
            "집중 시간이 끝났어요. 잠깐 쉬어도 좋아요."
            if result.phase == "focus"
            else "휴식이 끝났어요. 준비되면 다시 시작해요."
        )
        self.manager.statusBar().showMessage(text, 15000)
        if (
            self.settings.current.timer_notifications
            and not self.settings.current.notifications_paused
            and not self.notifications.quiet_hours(self.focus_timer.clock.now())
        ):
            self.pet.speak(text)
            if (
                not self.settings.current.notifications_paused
                and self.tray.isVisible()
                and QSystemTrayIcon.supportsMessages()
            ):
                self.tray.showMessage(
                    "타이머 완료", text, QSystemTrayIcon.MessageIcon.Information, 8000
                )

    def _task_completed(self) -> None:
        if not self.settings.current.reduce_motion:
            self.animation.play("happy")
        self.pet.speak("하나 끝냈네요. 잘했어요! 잠깐 숨을 돌려도 좋아요.")

    def _notify(self, reminders) -> None:
        title = "다가오는 일정" if len(reminders) == 1 else f"알림 {len(reminders)}개"
        lines = [
            f"{'마감' if value.occurrence.kind == 'task' else '일정'} · {value.occurrence.title}"
            for value in reminders[:4]
        ]
        if len(reminders) > 4:
            lines.append(f"외 {len(reminders) - 4}개 · 캘린더에서 확인해 주세요.")
        text = "\n".join(lines)
        if self.tray.isVisible() and QSystemTrayIcon.supportsMessages():
            self.tray.showMessage(title, text, QSystemTrayIcon.MessageIcon.Information, 8000)
        else:
            self.manager.statusBar().showMessage(text, 15000)
            self.pet.speak(lines[0])

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
        self.manager.open_page(self.manager.SETTINGS_PAGE)
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

    def quit(self) -> None:
        # Normal window-close handlers keep the buddy alive; explicitly permit a full exit.
        self.manager.allow_close = True
        self.pet.allow_close = True
        self.shutdown()
        self.app.quit()

    def shutdown(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.notifications.stop()
        self._tray_click.stop()
        self.pet._click_timer.stop()
        self.pet.animation_timer.stop()
        try:
            self.focus_timer.shutdown()
        except Exception as error:
            logging.getLogger(__name__).warning(
                "Timer shutdown checkpoint failed (%s)", type(error).__name__
            )
        self.manager.statistics_page.refresh_timer.stop()
        self.app.removeNativeEventFilter(self.power_filter)
        self.settings.update(x=self.pet.x(), y=self.pet.y())
        self.pet.hide()
        self.mini_timer.hide()
        self.pet.bubble.close()
        self.manager.hide()
        self.tray.hide()
        self.guard.close()
        self.store.close()
