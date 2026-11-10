import asyncio
import threading

from PySide6.QtCore import QObject, Signal

from desktop_buddy.ai.config import REQUEST_SECONDS
from desktop_buddy.models.online import OnlineError, OnlineResult


class JobSignals(QObject):
    prepared = Signal(str)
    finished = Signal(str, object)


class OnlineJob:
    def __init__(self, request, vault, client, signals, deadline: float = REQUEST_SECONDS):
        self.request, self.vault, self.client, self.signals = request, vault, client, signals
        self.deadline = deadline
        self.cancelled = threading.Event()
        self.lock = threading.Lock()
        self.loop = self.task = None
        self.gate = None
        self.thread = threading.Thread(target=self._run, daemon=True, name="buddy-online")

    def start(self) -> None:
        self.thread.start()

    def cancel(self) -> None:
        self.cancelled.set()
        with self.lock:
            if self.loop is not None and self.task is not None:
                try:
                    self.loop.call_soon_threadsafe(self.task.cancel)
                except RuntimeError:
                    pass

    async def _execute(self):
        with self.lock:
            self.loop = asyncio.get_running_loop()
            self.task = asyncio.current_task()
        try:
            if self.cancelled.is_set():
                raise asyncio.CancelledError
            return await asyncio.wait_for(
                self.client.run(
                    self.vault, self.request, self.cancelled, before_send=self._authorize
                ),
                self.deadline,
            )
        finally:
            with self.lock:
                self.loop = self.task = None
                self.gate = None

    async def _authorize(self):
        with self.lock:
            self.gate = asyncio.get_running_loop().create_future()
        try:
            self.signals.prepared.emit(self.request.id)
        except RuntimeError:
            raise asyncio.CancelledError from None
        if not await self.gate:
            raise OnlineError("storage")

    def approve(self, allowed: bool) -> None:
        def resolve():
            if self.gate is not None and not self.gate.done():
                self.gate.set_result(allowed)

        with self.lock:
            if self.loop is not None:
                try:
                    self.loop.call_soon_threadsafe(resolve)
                except RuntimeError:
                    pass

    def _run(self):
        try:
            outcome = asyncio.run(self._execute())
            if not isinstance(outcome, OnlineResult):
                outcome = OnlineResult(error="response")
        except asyncio.CancelledError:
            outcome = OnlineResult(error="cancelled")
        except TimeoutError:
            outcome = OnlineResult(error="timeout")
        except OnlineError as error:
            outcome = OnlineResult(error=error.code)
        except Exception:
            outcome = OnlineResult(error="unknown")
        try:
            self.signals.finished.emit(self.request.id, outcome)
        except RuntimeError:
            # The application can exit while a cancelled daemon worker is finishing.
            pass
