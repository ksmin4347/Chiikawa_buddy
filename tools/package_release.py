"""Validate a one-folder build and create a local ZIP; never publish it."""

# ruff: noqa: E402 -- Run directly from a source checkout.
import argparse
import hashlib
import json
import os
import re
import stat
import sys
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from desktop_buddy.core.metadata import APP_NAME, VERSION

ASSETS = ROOT / "assets"
CHARACTERS = ("chiikawa", "hachiware", "usagi")
PACK_FILES = ("manifest.json", "atlas.png", "focus_001.png", "focus_002.png", "focus_003.png")
MANIFEST = "DesktopBuddy/파일목록.json"
GUIDE = "DesktopBuddy/사용법.txt"


def digest_file(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def executable_version(path: Path) -> str:
    from PyInstaller.utils.win32.versioninfo import read_version_info_from_executable

    info = read_version_info_from_executable(str(path))
    values = {
        item.name: item.val
        for group in info.kids
        if group.__class__.__name__ == "StringFileInfo"
        for table in group.kids
        for item in table.kids
    }
    if values.get("ProductName") != APP_NAME or values.get("FileVersion") != values.get(
        "ProductVersion"
    ):
        raise ValueError("실행 파일의 제품 이름과 버전을 확인해 주세요.")
    return values["ProductVersion"]


def approved_assets() -> dict[str, Path]:
    result = {}
    for directory in ("default_character", "icons"):
        for path in (ASSETS / directory).rglob("*"):
            if path.is_file():
                result[path.relative_to(ASSETS).as_posix()] = path
    for character in CHARACTERS:
        for name in PACK_FILES:
            result[f"character_packs/{character}/{name}"] = (
                ASSETS / "character_packs" / character / name
            )
        result[f"completion_audio/{character}.wav"] = (
            ASSETS / "completion_audio" / f"{character}.wav"
        )
    return result


def validate_bundle(source: Path, version: str) -> list[Path]:
    if source.is_symlink() or source.is_junction():
        raise ValueError("배포 원본에 링크를 사용할 수 없어요.")
    source = source.resolve()
    if {path.name for path in source.iterdir()} != {"DesktopBuddy.exe", "_internal"}:
        raise ValueError("배포 폴더에는 실행 파일과 _internal만 있어야 해요.")
    files = []
    for path in source.rglob("*"):
        if path.is_symlink() or path.is_junction() or not path.resolve().is_relative_to(source):
            raise ValueError("배포 폴더에 링크나 폴더 밖 파일이 있어요.")
        relative = path.relative_to(source)
        forbidden = {".git", ".qa", ".venv", "logs", "characters", "__pycache__"}
        if any(
            part.lower() in forbidden for part in relative.parts
        ) or path.name.lower().startswith(".env"):
            raise ValueError("배포 폴더에 사용자 데이터나 작업 파일이 있어요.")
        if path.is_file():
            if path.name.casefold() in {"icu.dll", "icuuc.dll", "icuin.dll"} or (
                path.name.casefold().startswith("icudt") and path.suffix.casefold() == ".dll"
            ):
                raise ValueError("Windows ICU를 가리는 DLL이 배포 폴더에 있어요.")
            if path.suffix.lower() in {".db", ".sqlite", ".sqlite3", ".log", ".key"} or re.search(
                r"\.(?:db|sqlite3?)-(?:wal|shm|journal)$", path.name, re.IGNORECASE
            ):
                raise ValueError("배포 폴더에 사용자 데이터나 로그가 있어요.")
            files.append(path)
    if executable_version(source / "DesktopBuddy.exe") != version:
        raise ValueError("실행 파일 버전이 소스와 달라요. 먼저 다시 빌드해 주세요.")
    for required in ("_internal/PySide6/plugins/platforms/qwindows.dll", "_internal/winsound.pyd"):
        if not (source / required).is_file():
            raise ValueError("필수 Windows 실행 파일이 빠졌어요.")
    expected = approved_assets()
    asset_root = source / "_internal" / "assets"
    actual = {
        path.relative_to(asset_root).as_posix(): path
        for path in asset_root.rglob("*")
        if path.is_file()
    }
    if actual.keys() != expected.keys() or any(
        digest_file(actual[key]) != digest_file(expected[key]) for key in expected
    ):
        raise ValueError("번들 캐릭터·음악·아이콘 파일이 원본과 달라요.")
    return sorted(files)


def verify_archive(path: Path) -> dict:
    with zipfile.ZipFile(path) as archive:
        entries = archive.infolist()
        names = [entry.filename for entry in entries]
        if len(entries) > 4096 or sum(entry.file_size for entry in entries) > 1024**3:
            raise ValueError("배포 ZIP 크기나 파일 수가 제한을 넘었어요.")
        if len(names) != len(set(names)):
            raise ValueError("배포 ZIP에 중복 경로가 있어요.")
        for entry in entries:
            name = PurePosixPath(entry.filename)
            if (
                name.is_absolute()
                or ".." in name.parts
                or "\\" in entry.filename
                or ":" in entry.filename
                or name.as_posix() != entry.filename
                or not entry.filename.startswith("DesktopBuddy/")
                or stat.S_ISLNK(entry.external_attr >> 16)
                or entry.is_dir()
            ):
                raise ValueError("배포 ZIP의 파일 경로가 올바르지 않아요.")
        if MANIFEST not in names or archive.getinfo(MANIFEST).file_size > 1024**2:
            raise ValueError("배포 파일 목록이 없거나 너무 커요.")
        manifest = json.loads(archive.read(MANIFEST))
        if (
            not isinstance(manifest, dict)
            or manifest.get("format_version") != 1
            or not isinstance(manifest.get("files"), list)
            or manifest.get("app_name") != APP_NAME
            or not isinstance(manifest.get("app_version"), str)
            or re.fullmatch(r"\d+\.\d+\.\d+", manifest["app_version"]) is None
        ):
            raise ValueError("배포 파일 목록 형식이 올바르지 않아요.")
        records = manifest["files"]
        listed = [
            record.get("path")
            for record in records
            if isinstance(record, dict) and isinstance(record.get("path"), str)
        ]
        if (
            len(listed) != len(records)
            or len(set(listed)) != len(listed)
            or set(listed) != set(names) - {MANIFEST}
        ):
            raise ValueError("배포 파일 목록과 ZIP 내용이 달라요.")
        if not {GUIDE, "DesktopBuddy/DesktopBuddy.exe"} <= set(listed):
            raise ValueError("실행 파일이나 사용법이 빠졌어요.")
        for record in records:
            info = archive.getinfo(record["path"])
            if type(record.get("size")) is not int or record["size"] != info.file_size:
                raise ValueError("배포 파일 크기가 달라요.")
            with archive.open(info) as content:
                actual_hash = hashlib.file_digest(content, "sha256").hexdigest()
            if record.get("sha256") != actual_hash:
                raise ValueError("배포 파일의 SHA-256이 달라요.")
    return manifest


def create_package(source: Path, destination: Path, version: str) -> Path:
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError("버전 형식이 올바르지 않아요.")
    if destination.resolve().is_relative_to(source.resolve()):
        raise ValueError("ZIP은 배포 원본 폴더 밖에 만들어야 해요.")
    files = validate_bundle(source, version)
    source = source.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    guide = (
        f"{APP_NAME} {version}\n\n"
        "1. ZIP 전체를 새 폴더에 압축 해제해 주세요.\n"
        "2. DesktopBuddy.exe와 _internal 폴더를 함께 두세요.\n"
        "3. DesktopBuddy.exe를 실행하고 캐릭터를 골라요.\n"
        "4. 캐릭터 더블클릭으로 관리창, F1로 키보드 안내를 열어요.\n"
        "5. 완전히 끝내려면 트레이의 프로그램 종료를 눌러요.\n\n"
        "사용자 데이터: %LOCALAPPDATA%\\DesktopBuddy\n"
        "업데이트할 때 앱을 종료하고 새 폴더에 압축 해제하세요.\n"
        "기존 데이터 폴더는 그대로 사용해요.\n"
        "기본 기능은 인터넷과 API 키 없이 동작해요.\n"
        "실제 Windows 10·깨끗한 PC의 실행 검증은 남은 초기 배포 후보예요.\n"
    ).encode("utf-8-sig")
    records = [
        {
            "path": "DesktopBuddy/" + path.relative_to(source).as_posix(),
            "size": path.stat().st_size,
            "sha256": digest_file(path),
        }
        for path in files
    ]
    records.append({"path": GUIDE, "size": len(guide), "sha256": hashlib.sha256(guide).hexdigest()})
    manifest = {"format_version": 1, "app_name": APP_NAME, "app_version": version, "files": records}
    handle, temporary = tempfile.mkstemp(prefix=".package-", suffix=".zip", dir=destination.parent)
    os.close(handle)
    temporary_path = Path(temporary)
    try:
        with zipfile.ZipFile(temporary_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            for path in files:
                archive.write(path, "DesktopBuddy/" + path.relative_to(source).as_posix())
            archive.writestr(GUIDE, guide)
            archive.writestr(MANIFEST, json.dumps(manifest, ensure_ascii=False, indent=2))
        verify_archive(temporary_path)
        checksum = digest_file(temporary_path)
        os.replace(temporary_path, destination)
        destination.with_suffix(destination.suffix + ".sha256").write_text(
            f"{checksum}  {destination.name}\n", encoding="utf-8"
        )
    finally:
        temporary_path.unlink(missing_ok=True)
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", type=Path, help="Verify an existing ZIP without extracting it")
    args = parser.parse_args()
    if args.verify:
        manifest = verify_archive(args.verify)
        sidecar = args.verify.with_suffix(args.verify.suffix + ".sha256")
        if sidecar.exists() and sidecar.read_text(encoding="utf-8").split()[0] != digest_file(
            args.verify
        ):
            raise ValueError("ZIP의 SHA-256이 달라요.")
        print(f"검증 완료: {manifest['app_version']} · {len(manifest['files'])}개 파일")
    else:
        output = ROOT / "dist" / "releases" / f"Meonjakgwi-{VERSION}-windows-x64.zip"
        print(create_package(ROOT / "dist" / "DesktopBuddy", output, VERSION))


if __name__ == "__main__":
    main()
