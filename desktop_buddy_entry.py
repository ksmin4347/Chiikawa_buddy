import sys
from pathlib import Path


def launch() -> int:
    if not getattr(sys, "frozen", False):
        sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
    from desktop_buddy.main import main

    return main()


if __name__ == "__main__":
    raise SystemExit(launch())
