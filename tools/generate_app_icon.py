"""Package the bundled waving Usagi frame as PNG and multi-size Windows ICO."""

import struct
from pathlib import Path

from PySide6.QtCore import QBuffer, QIODevice, Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter


def save_icons(root: Path) -> None:
    sheet = QImage(str(root / "assets/character_packs/usagi/atlas.png"))
    if sheet.isNull():
        raise ValueError("우사기 이미지를 읽지 못했어요.")
    frame = sheet.copy(192 * 2, 208 * 3, 192, 208)
    image = QImage(256, 256, QImage.Format.Format_RGBA8888)
    image.fill(Qt.GlobalColor.transparent)
    fitted = frame.scaled(
        248, 248, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
    )
    painter = QPainter(image)
    painter.drawImage((256 - fitted.width()) // 2, (256 - fitted.height()) // 2, fitted)
    painter.end()
    folder = root / "assets/icons"
    folder.mkdir(parents=True, exist_ok=True)
    if not image.save(str(folder / "buddy.png")):
        raise OSError("아이콘 이미지를 저장하지 못했어요.")
    sizes = (16, 24, 32, 48, 64, 128, 256)
    entries, payloads = [], []
    offset = 6 + 16 * len(sizes)
    for size in sizes:
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        scaled = image.scaled(
            size,
            size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        if not scaled.save(buffer, "PNG"):
            raise OSError("아이콘 크기를 변환하지 못했어요.")
        payload = bytes(buffer.data())
        entries.append(
            struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(payload), offset)
        )
        payloads.append(payload)
        offset += len(payload)
    (folder / "buddy.ico").write_bytes(
        struct.pack("<HHH", 0, 1, len(sizes)) + b"".join(entries) + b"".join(payloads)
    )


if __name__ == "__main__":
    app = QGuiApplication([])
    save_icons(Path(__file__).resolve().parents[1])
    print("Created Usagi app icon in 7 Windows sizes.")
