"""Convert developer-provided FLAC tracks to bounded, local PCM WAV files."""

import argparse
import wave
from pathlib import Path

DURATIONS = {"chiikawa": 27, "hachiware": 57, "usagi": 16}


def prepare(source: Path, destination: Path) -> None:
    import soundfile

    destination.mkdir(parents=True, exist_ok=True)
    for key, seconds in DURATIONS.items():
        with soundfile.SoundFile(source / f"{key}.flac") as audio:
            if (audio.samplerate, audio.channels, audio.frames) != (48000, 2, seconds * 48000):
                raise ValueError(f"Unexpected audio format: {key}")
            pcm = audio.buffer_read(audio.frames, dtype="int16")
        with wave.open(str(destination / f"{key}.wav"), "wb") as output:
            output.setnchannels(2)
            output.setsampwidth(2)
            output.setframerate(48000)
            output.writeframes(pcm)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    arguments = parser.parse_args()
    prepare(arguments.source, arguments.destination)
