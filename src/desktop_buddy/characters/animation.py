import json
import math
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QObject, QRect, Qt, Signal
from PySide6.QtGui import QColor, QImage, QImageReader, QPainter, QPixmap


@dataclass
class Clip:
    frames: list[QPixmap]
    fps: float
    loop: bool
    durations_ms: tuple[int, ...] = ()
    manual: bool = False


def fallback_pixmap() -> QPixmap:
    pixmap = QPixmap(256, 256)
    pixmap.fill(QColor("transparent"))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QColor("#38564d"))
    painter.setBrush(QColor("#bfe3cd"))
    painter.drawEllipse(36, 36, 184, 192)
    painter.setBrush(QColor("#38564d"))
    painter.drawEllipse(88, 112, 10, 14)
    painter.drawEllipse(158, 112, 10, 14)
    painter.drawArc(110, 136, 36, 24, 180 * 16, 180 * 16)
    painter.end()
    return pixmap


class AssetError(ValueError):
    pass


MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_MEMORY_BYTES = 64 * 1024 * 1024
MAX_FRAMES = 64


class PackDecoder:
    def __init__(self, root: Path, strict: bool):
        self.root, self.strict = root.resolve(), strict
        self.images: dict[Path, QImage] = {}
        self.memory = 0
        self.count = 0

    def image(self, relative: str, atlas: bool = False) -> QImage:
        if not isinstance(relative, str) or not relative or len(relative) > 240:
            raise AssetError("이미지 경로가 올바르지 않아요.")
        path = (self.root / relative).resolve()
        if not path.is_relative_to(self.root) or path.suffix.lower() != ".png":
            raise AssetError("이미지는 캐릭터 폴더 안의 PNG만 사용할 수 있어요.")
        if path in self.images:
            return self.images[path]
        try:
            with path.open("rb") as stream:
                payload = stream.read(MAX_FILE_BYTES + 1)
        except OSError as error:
            raise AssetError("캐릭터 이미지 파일을 읽지 못했어요.") from error
        if len(payload) > MAX_FILE_BYTES:
            raise AssetError("이미지 파일 한 장은 8 MiB 이하여야 해요.")
        buffer = QBuffer()
        buffer.setData(QByteArray(payload))
        buffer.open(QIODevice.OpenModeFlag.ReadOnly)
        reader = QImageReader(buffer)
        size = reader.size()
        maximum = 4096 if atlas else 1024
        pixels = size.width() * size.height()
        if (
            reader.format() != b"png"
            or not size.isValid()
            or max(size.width(), size.height()) > maximum
            or pixels > 4_194_304
        ):
            raise AssetError("이미지 형식이나 크기를 확인해 주세요.")
        # Account for a 16-bit decode, conversion and pixmap before allocating pixels.
        if self.memory + pixels * 16 > MAX_MEMORY_BYTES:
            raise AssetError("캐릭터 이미지 메모리 한도를 초과했어요.")
        image = reader.read()
        if image.isNull() or (self.strict and not image.hasAlphaChannel()):
            raise AssetError("손상되었거나 투명도를 지원하지 않는 이미지예요.")
        image = image.convertToFormat(QImage.Format.Format_RGBA8888)
        self.images[path] = image
        self.memory += image.sizeInBytes()
        return image

    def frame(self, image: QImage) -> QPixmap:
        if self.memory + 256 * 256 * 4 > MAX_MEMORY_BYTES:
            raise AssetError("캐릭터 이미지 메모리 한도를 초과했어요.")
        if self.strict and not any(bytes(image.constBits())[3::4]):
            raise AssetError("비어 있는 캐릭터 프레임이에요.")
        canvas = QImage(256, 256, QImage.Format.Format_RGBA8888)
        canvas.fill(Qt.GlobalColor.transparent)
        fitted = image.scaled(
            232, 232, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
        )
        painter = QPainter(canvas)
        painter.drawImage((256 - fitted.width()) // 2, 244 - fitted.height(), fitted)
        painter.end()
        self.memory += canvas.sizeInBytes()
        pixmap = QPixmap.fromImage(canvas)
        if pixmap.isNull():
            raise AssetError("캐릭터 표시 메모리를 준비하지 못했어요.")
        return pixmap


def load_clips(
    root: Path, *, strict: bool = False, expected_id: str | None = None
) -> dict[str, Clip]:
    try:
        with (root / "manifest.json").open("rb") as stream:
            payload = stream.read(65537)
        if len(payload) > 65536:
            raise AssetError("캐릭터 설정 파일이 너무 커요.")
        manifest = json.loads(payload)
        states = manifest.get("states") if isinstance(manifest, dict) else None
        if not isinstance(states, dict) or not 1 <= len(states) <= 16:
            raise AssetError("캐릭터 상태 구성이 올바르지 않아요.")
        if expected_id is not None and manifest.get("id") != expected_id:
            raise AssetError("캐릭터 ID가 일치하지 않아요.")
        decoder = PackDecoder(root, strict)
        atlas = manifest.get("atlas")
        sheet = decoder.image(atlas.get("path"), atlas=True) if isinstance(atlas, dict) else None
        clips: dict[str, Clip] = {}
        for name, spec in states.items():
            if not isinstance(name, str) or not isinstance(spec, dict):
                if strict:
                    raise AssetError("캐릭터 상태 구성이 올바르지 않아요.")
                continue
            frames = spec.get("frames")
            if not isinstance(frames, list) or not 1 <= len(frames) <= MAX_FRAMES:
                if strict:
                    raise AssetError("상태별 프레임 수를 확인해 주세요.")
                continue
            decoder.count += len(frames)
            if decoder.count > MAX_FRAMES:
                raise AssetError("캐릭터 프레임은 총 64개 이하여야 해요.")
            fps = spec.get("fps", 3)
            if type(fps) not in (int, float) or not math.isfinite(fps):
                fps = 3
            durations = spec.get("durations_ms", [])
            if (
                not isinstance(durations, list)
                or (durations and len(durations) != len(frames))
                or any(type(delay) is not int or not 33 <= delay <= 5000 for delay in durations)
            ):
                raise AssetError("프레임 재생 시간을 확인해 주세요.")
            decoded, holds = [], []
            for index, frame in enumerate(frames):
                try:
                    if isinstance(frame, str):
                        image = decoder.image(frame)
                        # Preserve original default pack canvases in compatibility mode.
                        pixmap = decoder.frame(image) if strict else QPixmap.fromImage(image)
                    elif sheet is not None and isinstance(frame, dict):
                        values = [
                            atlas.get("cell_width"),
                            atlas.get("cell_height"),
                            frame.get("column"),
                            frame.get("row"),
                        ]
                        if any(type(value) is not int for value in values):
                            raise AssetError("프레임 좌표가 올바르지 않아요.")
                        width, height, column, row = values
                        if (
                            not 1 <= min(width, height)
                            or max(width, height) > 1024
                            or min(row, column) < 0
                            or (column + 1) * width > sheet.width()
                            or (row + 1) * height > sheet.height()
                        ):
                            raise AssetError("프레임이 이미지 범위를 벗어났어요.")
                        rect = QRect(column * width, row * height, width, height)
                        pixmap = decoder.frame(sheet.copy(rect))
                    else:
                        raise AssetError("프레임 구성이 올바르지 않아요.")
                    decoded.append(pixmap)
                    if durations:
                        holds.append(durations[index])
                except AssetError:
                    if strict:
                        raise
            if decoded:
                loop = spec.get("loop", True)
                clips[name] = Clip(
                    decoded,
                    max(1, min(30, fps)),
                    loop if type(loop) is bool else True,
                    tuple(holds),
                    spec.get("manual") is True,
                )
        if "idle" not in clips:
            raise AssetError("기본 캐릭터 프레임이 없어요.")
        aliases = manifest.get("aliases", {})
        if not isinstance(aliases, dict) or len(aliases) > 16:
            raise AssetError("대체 상태 구성이 올바르지 않아요.")
        for alias, target in aliases.items():
            if not isinstance(alias, str) or target not in clips or alias in clips:
                raise AssetError("대체 상태 구성이 올바르지 않아요.")
            clips[alias] = clips[target]
        return clips
    except (
        OSError,
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
        RecursionError,
        OverflowError,
    ) as error:
        if strict:
            if isinstance(error, AssetError):
                raise
            raise AssetError("캐릭터 자료를 읽지 못했어요.") from error
        return {"idle": Clip([fallback_pixmap()], 2, True)}


class AnimationState(QObject):
    """Single authority for state transitions. Future services send events here."""

    state_changed = Signal(str)

    def __init__(self, clips: dict[str, Clip]):
        super().__init__()
        self.clips = clips
        self.base_state = "idle"
        self.base_priority = 0
        self.priority = 0
        self.state = "idle"
        self.index = 0
        self.ambient = False
        self.held = False

    @property
    def clip(self) -> Clip:
        return self.clips[self.state]

    @property
    def frame(self) -> QPixmap:
        return self.clip.frames[self.index]

    def play(
        self, state: str, priority: int = 50, force: bool = False, *, hold: bool = False
    ) -> None:
        if not force and (not self.clip.loop or self.held) and priority < self.priority:
            return
        self.priority = priority
        self.ambient = False
        self.held = hold
        self.state = state if state in self.clips else "idle"
        self.index = 0
        self.state_changed.emit(self.state)

    def set_base(self, state: str, priority: int = 0) -> None:
        old_base = self.base_state
        self.base_state = state if state in self.clips else "idle"
        self.base_priority = priority
        if (
            (self.ambient or self.held)
            and old_base == self.base_state
            and priority <= self.priority
        ):
            return
        if self.state == old_base or self.clip.loop or priority > self.priority:
            if self.state != self.base_state:
                self.play(self.base_state, priority=priority, force=True)

    @property
    def frame_delay_ms(self) -> float:
        return (
            self.clip.durations_ms[self.index] if self.clip.durations_ms else 1000 / self.clip.fps
        )

    def replace_clips(self, clips: dict[str, Clip]) -> None:
        self.ambient = False
        self.held = False
        self.clips = clips
        self.state = self.base_state if self.base_state in clips else "idle"
        self.base_state = self.state
        self.index, self.priority = 0, self.base_priority
        self.state_changed.emit(self.state)

    def advance(self) -> None:
        if self.clip.manual:
            return
        if self.index + 1 < len(self.clip.frames):
            self.index += 1
        elif self.clip.loop:
            self.index = 0
        else:
            self.play(self.base_state, priority=self.base_priority, force=True)

    def show_ambient(self, state: str, index: int | None = None) -> bool:
        if (
            self.base_state != "idle"
            or (self.state != self.base_state and not self.ambient)
            or state not in self.clips
        ):
            return False
        target = self.clips[state]
        frame = index if index is not None else self.index if self.state == state else 0
        if not 0 <= frame < len(target.frames):
            return False
        changed = self.state != state or self.index != frame
        self.state, self.index = state, frame
        self.priority = max(25, self.base_priority)
        self.ambient = True
        if changed:
            self.state_changed.emit(state)
        return True

    def clear_ambient(self) -> None:
        if self.ambient:
            self.play(self.base_state, priority=self.base_priority, force=True)
