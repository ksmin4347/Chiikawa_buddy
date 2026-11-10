"""Keep unrelated tools on the developer PATH out of the Windows bundle."""

import os
from pathlib import Path

SYSTEM_ICU = {"icu.dll", "icuuc.dll", "icuin.dll"}


def configure_build_path(
    python_root: Path, scripts: Path, bindings: list[Path], windows: Path
) -> None:
    candidates = [
        *bindings,
        scripts,
        python_root,
        python_root / "DLLs",
        windows / "System32",
        windows,
    ]
    paths = dict.fromkeys(str(path.resolve()) for path in candidates if path.is_dir())
    os.environ["PATH"] = os.pathsep.join(paths)


def system_icu_filter(binaries: list[tuple], system32: Path) -> list[tuple]:
    result = []
    for entry in binaries:
        name = Path(entry[0]).name.casefold()
        if name in SYSTEM_ICU:
            if Path(entry[1]).parent.resolve() != system32.resolve():
                raise ValueError("다른 도구의 ICU DLL이 섞였어요. 빌드 PATH를 확인해 주세요.")
            # Qt uses the Windows ICU API; do not shadow it with an app-local copy.
            continue
        if name.startswith("icudt") and name.endswith(".dll"):
            raise ValueError("허용하지 않은 ICU 데이터 DLL이 섞였어요.")
        result.append(entry)
    return result
