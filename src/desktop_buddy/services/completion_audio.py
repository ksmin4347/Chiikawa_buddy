import sys
import wave
from pathlib import Path

from desktop_buddy.core.paths import asset_directory

SONG_SECONDS = {"chiikawa": 27, "hachiware": 57, "usagi": 16}


class WavePlayer:
    def __init__(self, root: Path | None = None, backend=None):
        self.root = root or asset_directory() / "completion_audio"
        self.backend = backend
        self.playing = False

    def play(self, character_id: str) -> None:
        if character_id not in SONG_SECONDS:
            raise ValueError("이 캐릭터의 완료 음악이 없어요.")
        root = self.root.resolve()
        path = (root / f"{character_id}.wav").resolve()
        if not path.is_relative_to(root) or path.stat().st_size > 12 * 1024 * 1024:
            raise ValueError("완료 음악 파일을 확인해 주세요.")
        with wave.open(str(path), "rb") as audio:
            if (
                audio.getnchannels() != 2
                or audio.getsampwidth() != 2
                or audio.getframerate() != 48000
                or audio.getnframes() != SONG_SECONDS[character_id] * 48000
                or audio.getcomptype() != "NONE"
                or path.stat().st_size < audio.getnframes() * 4 + 44
            ):
                raise ValueError("완료 음악 형식이 올바르지 않아요.")
        if self.backend is None:
            if sys.platform != "win32":
                raise RuntimeError("이 PC에서는 완료 음악을 재생하지 못해요.")
            import winsound

            self.backend = winsound
        self.stop()
        self.backend.PlaySound(
            str(path),
            self.backend.SND_FILENAME | self.backend.SND_ASYNC | self.backend.SND_NODEFAULT,
        )
        self.playing = True

    def stop(self) -> None:
        if self.playing:
            self.playing = False
            try:
                self.backend.PlaySound(None, 0)
            except (OSError, RuntimeError):
                pass
