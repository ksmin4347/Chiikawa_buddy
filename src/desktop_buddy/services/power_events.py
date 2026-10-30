import ctypes
import logging
import sys
from ctypes.wintypes import MSG

from PySide6.QtCore import QAbstractNativeEventFilter


class PowerEventFilter(QAbstractNativeEventFilter):
    """Observe Windows power broadcasts without changing system power settings."""

    def __init__(self, timer):
        super().__init__()
        self.timer = timer

    def handle(self, message: int, event: int) -> None:
        if message == 0x0218 and event in (4, 6, 7, 18):
            try:
                self.timer.pause("suspended" if event == 4 else "resumed")
            except Exception as error:
                self.timer._storage_error(error)

    def nativeEventFilter(self, event_type, message):
        if sys.platform == "win32" and bytes(event_type) in (
            b"windows_generic_MSG",
            b"windows_dispatcher_MSG",
        ):
            try:
                native = ctypes.cast(int(message), ctypes.POINTER(MSG)).contents
                self.handle(native.message, native.wParam)
            except (TypeError, ValueError, OverflowError):
                logging.getLogger(__name__).warning("Invalid power broadcast")
        return False, 0
