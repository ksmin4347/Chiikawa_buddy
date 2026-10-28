import os
import sys
from pathlib import Path

from desktop_buddy.core.metadata import DATA_FOLDER


def data_directory(override: Path | None = None) -> Path:
    if override is not None:
        return override.expanduser().resolve()
    local = os.environ.get("LOCALAPPDATA")
    return (Path(local) if local else Path.home() / ".local" / "share") / DATA_FOLDER


def asset_directory() -> Path:
    bundled = getattr(sys, "_MEIPASS", None)
    root = Path(bundled) if bundled else Path(__file__).resolve().parents[3]
    return root / "assets"
