import hashlib
from pathlib import Path

from PySide6.QtCore import QLockFile, QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket


class SingleInstance(QObject):
    activation_requested = Signal()

    def __init__(self, data_dir: Path):
        super().__init__()
        identity = hashlib.sha256(str(data_dir.resolve()).casefold().encode()).hexdigest()[:24]
        self.name = f"desktop-buddy-{identity}"
        self.lock = QLockFile(str(data_dir / "instance.lock"))
        self.lock.setStaleLockTime(0)
        self.server = QLocalServer(self)
        self.server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        self.server.newConnection.connect(self._receive)
        self._clients: list[QLocalSocket] = []
        self._buffers: dict[QLocalSocket, bytes] = {}

    def acquire(self) -> bool:
        if not self.lock.tryLock(0):
            if self.lock.error() != QLockFile.LockError.LockFailedError:
                raise RuntimeError(
                    "실행 잠금 파일을 만들지 못했어요. 저장 폴더 권한을 확인해 주세요."
                )
            socket = QLocalSocket()
            socket.connectToServer(self.name)
            if socket.waitForConnected(1200):
                socket.write(b"show")
                socket.waitForBytesWritten(500)
                socket.waitForReadyRead(1500)  # Existing process acknowledges before we exit.
                socket.disconnectFromServer()
            return False
        QLocalServer.removeServer(self.name)
        if not self.server.listen(self.name):
            self.lock.unlock()
            raise RuntimeError("앱의 로컬 실행 채널을 열지 못했어요.")
        return True

    def _receive(self) -> None:
        while self.server.hasPendingConnections():
            socket = self.server.nextPendingConnection()
            self._clients.append(socket)
            self._buffers[socket] = b""
            socket.readyRead.connect(lambda s=socket: self._activate(s))
            socket.disconnected.connect(lambda s=socket: self._release(s))
            if socket.bytesAvailable():
                self._activate(socket)

    def _activate(self, socket: QLocalSocket) -> None:
        self._buffers[socket] += socket.readAll().data()
        if len(self._buffers[socket]) < 4:
            return
        if self._buffers[socket] == b"show":
            self.activation_requested.emit()
            socket.write(b"ok")
            socket.flush()
        socket.disconnectFromServer()

    def _release(self, socket: QLocalSocket) -> None:
        if socket in self._clients:
            self._clients.remove(socket)
        self._buffers.pop(socket, None)
        socket.deleteLater()

    def close(self) -> None:
        for socket in self._clients[:]:
            socket.abort()
        self.server.close()
        self.lock.unlock()
