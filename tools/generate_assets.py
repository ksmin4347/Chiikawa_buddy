"""Recreate the original Moru mascot. No downloaded or copyrighted source art."""

import json
import math
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPainterPath, QPen

ROOT = Path(__file__).resolve().parents[1]


def draw(happy: bool, frame: int, state: str = "idle") -> QImage:
    image = QImage(512, 512, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    p = QPainter(image)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.scale(2, 2)
    lift = math.sin(frame / 8 * math.tau) * (5 if happy else 1.5)
    p.translate(0, -lift)
    outline = QPen(
        QColor("#39594e"),
        4,
        Qt.PenStyle.SolidLine,
        Qt.PenCapStyle.RoundCap,
        Qt.PenJoinStyle.RoundJoin,
    )
    p.setPen(outline)
    p.setBrush(QColor("#c5e6cd"))
    p.drawEllipse(68, 211, 43, 23)
    p.drawEllipse(148, 211, 43, 23)
    p.drawEllipse(35, 140 if not happy else 116, 39, 44)
    p.drawEllipse(184, 140 if not happy else 116, 39, 44)
    body = QPainterPath()
    body.moveTo(128, 64)
    body.cubicTo(78, 64, 51, 105, 53, 161)
    body.cubicTo(52, 210, 78, 227, 128, 227)
    body.cubicTo(181, 227, 206, 209, 204, 161)
    body.cubicTo(207, 104, 179, 64, 128, 64)
    p.drawPath(body)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#edf4dc"))
    p.drawEllipse(89, 170, 79, 46)
    p.setBrush(QColor("#f2b9ab"))
    p.drawEllipse(71, 143, 26, 14)
    p.drawEllipse(163, 143, 26, 14)
    p.setPen(QPen(QColor("#39594e"), 5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    blink = state == "sleep" or (not happy and frame == 6)
    if happy or blink:
        for x in (96, 160):
            eye = QPainterPath(QPointF(x - 7, 132))
            eye.quadTo(x, 123 if happy else 134, x + 7, 132)
            p.drawPath(eye)
    else:
        p.setBrush(QColor("#39594e"))
        p.drawEllipse(91, 122, 10, 16)
        p.drawEllipse(155, 122, 10, 16)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#ffffff"))
        p.drawEllipse(93, 124, 3, 4)
        p.drawEllipse(157, 124, 3, 4)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(outline)
    smile = QPainterPath(QPointF(117, 145))
    smile.quadTo(128, 140 if state == "sad" else 157 if happy else 153, 139, 145)
    p.drawPath(smile)
    p.setPen(QPen(QColor("#557e51"), 5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.drawLine(128, 65, 128, 45)
    p.setBrush(QColor("#8db97d"))
    leaf = QPainterPath(QPointF(127, 49))
    leaf.cubicTo(103, 51, 96, 33, 102, 28)
    leaf.cubicTo(122, 27, 132, 40, 127, 49)
    p.drawPath(leaf)
    leaf2 = QPainterPath(QPointF(129, 46))
    leaf2.cubicTo(126, 28, 143, 20, 157, 25)
    leaf2.cubicTo(157, 42, 146, 51, 129, 46)
    p.drawPath(leaf2)
    if happy:
        p.setPen(QPen(QColor("#c79a40"), 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        for x, y in [(37, 76), (216, 67)]:
            p.drawLine(x - 5, y, x + 5, y)
            p.drawLine(x, y - 5, x, y + 5)
    if state in ("sad", "worried"):
        p.setPen(QPen(QColor("#39594e"), 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(88, 116, 103, 112)
        p.drawLine(153, 112, 168, 116)
        if state == "sad":
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#a6c5d1"))
            p.drawEllipse(166, 140 + frame % 3, 7, 11)
    elif state == "sleep":
        p.setPen(QPen(QColor("#6c8492"), 3))
        for x, y, size in ((209, 90, 8), (227, 70, 11)):
            y -= frame % 4
            p.drawLine(x, y, x + size, y)
            p.drawLine(x + size, y, x, y + size)
            p.drawLine(x, y + size, x + size, y + size)
    if state == "focus":
        p.setPen(outline)
        p.setBrush(QColor("#f8edd3"))
        p.drawRoundedRect(78, 169, 100, 46, 4, 4)
        p.drawLine(128, 172, 128, 212)
        p.setPen(QPen(QColor("#9ca78a"), 2))
        for y in (181, 190, 199):
            p.drawLine(88, y, 117, y)
            p.drawLine(139, y, 167, y)
    elif state == "break":
        p.setPen(outline)
        p.setBrush(QColor("#fff5dd"))
        p.drawEllipse(146, 173, 24, 22)
        p.drawRoundedRect(102, 168, 52, 39, 8, 8)
        p.setPen(QPen(QColor("#769382"), 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        for x in (116, 133):
            steam = QPainterPath(QPointF(x, 159))
            steam.cubicTo(x - 8, 154, x + 7, 149, x, 144 - frame % 3)
            p.drawPath(steam)
    elif state == "complete":
        p.setPen(Qt.PenStyle.NoPen)
        for index, color in enumerate(("#d79e52", "#74a2c4", "#b28cbb", "#8da654")):
            p.setBrush(QColor(color))
            p.drawEllipse(25 + index * 64, 45 + (frame * 5 + index * 11) % 42, 7, 11)
    p.end()
    return image


def main():
    app = QGuiApplication([])
    root = ROOT / "assets" / "default_character"
    states = {}
    for name in ("idle", "happy", "focus", "break", "complete", "worried", "sad", "sleep"):
        directory = root / name
        directory.mkdir(parents=True, exist_ok=True)
        frames = []
        for index in range(8):
            relative = f"{name}/frame_{index + 1:03}.png"
            assert draw(name in ("happy", "complete"), index, name).save(str(root / relative))
            frames.append(relative)
        states[name] = {
            "fps": 1
            if name == "sleep"
            else 2
            if name in ("sad", "worried")
            else 3
            if name in ("idle", "focus", "break")
            else 8,
            "loop": name not in ("happy", "complete"),
            "frames": frames,
        }
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "id": "moru",
                "name": "모루",
                "author": "Desktop Buddy project",
                "states": states,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    icon = draw(False, 0)
    icon.save(str(ROOT / "assets" / "icons" / "buddy.png"))
    icon.save(str(ROOT / "assets" / "icons" / "buddy.ico"))
    print("Created 64 transparent PNG frames and app icons.")
    del app


if __name__ == "__main__":
    main()
