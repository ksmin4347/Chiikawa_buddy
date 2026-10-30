import ctypes
import sys


class WindowsAttention:
    """Read only Windows notification state; never inspect titles, input, or pixels."""

    def __init__(self) -> None:
        self.query = None
        self.available = sys.platform == "win32"
        if self.available:
            try:
                self.query = ctypes.WinDLL("shell32").SHQueryUserNotificationState
                self.query.argtypes = [ctypes.POINTER(ctypes.c_int)]
                self.query.restype = ctypes.c_long
            except (OSError, AttributeError):
                self.available = False

    def fullscreen(self) -> bool:
        if self.query is None:
            return False
        value = ctypes.c_int()
        try:
            result = self.query(ctypes.byref(value))
        except (OSError, ValueError):
            self.available = False
            return False
        self.available = result == 0
        # QUNS_BUSY includes Windows' fullscreen heuristic; 3/4 are D3D and presentation.
        return result == 0 and value.value in (2, 3, 4)
