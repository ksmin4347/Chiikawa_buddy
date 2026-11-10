import importlib.util
import json
import shutil
import zipfile
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "release_package", Path(__file__).resolve().parents[1] / "tools" / "package_release.py"
)
package = importlib.util.module_from_spec(spec)
spec.loader.exec_module(package)


@pytest.fixture
def bundle(tmp_path, monkeypatch):
    reference = tmp_path / "assets"
    for name in ("default_character/manifest.json", "icons/buddy.ico"):
        path = reference / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"approved")
    for character in package.CHARACTERS:
        for name in package.PACK_FILES:
            path = reference / "character_packs" / character / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"approved")
        path = reference / "completion_audio" / f"{character}.wav"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"approved")
    source = tmp_path / "bundle"
    source.mkdir()
    (source / "DesktopBuddy.exe").write_bytes(b"test executable")
    shutil.copytree(reference, source / "_internal" / "assets")
    for relative in ("PySide6/plugins/platforms/qwindows.dll", "winsound.pyd"):
        path = source / "_internal" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"runtime")
    monkeypatch.setattr(package, "ASSETS", reference)
    monkeypatch.setattr(package, "executable_version", lambda _path: "0.5.8")
    return source, tmp_path / "releases" / "buddy.zip"


def test_complete_folder_archive_and_sha256_roundtrip(bundle):
    source, output = bundle
    package.create_package(source, output, "0.5.8")
    manifest = package.verify_archive(output)
    assert manifest["app_version"] == "0.5.8"
    with zipfile.ZipFile(output) as archive:
        assert archive.read("DesktopBuddy/DesktopBuddy.exe") == b"test executable"
        assert archive.read("DesktopBuddy/_internal/winsound.pyd") == b"runtime"
        assert "API 키 없이" in archive.read(package.GUIDE).decode("utf-8-sig")
    assert output.with_suffix(".zip.sha256").read_text().split()[0] == package.digest_file(output)


@pytest.mark.parametrize(
    "relative",
    [
        "buddy.db",
        "_internal/session.db-wal",
        "_internal/app.log",
        "_internal/.env",
        "_internal/assets/characters/photo.png",
    ],
)
def test_user_data_and_work_files_are_rejected(bundle, relative):
    source, output = bundle
    path = source / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"private")
    with pytest.raises(ValueError):
        package.create_package(source, output, "0.5.8")
    assert not output.exists()


def test_changed_character_asset_is_rejected(bundle):
    source, output = bundle
    (source / "_internal/assets/character_packs/usagi/atlas.png").write_bytes(b"changed")
    with pytest.raises(ValueError, match="원본"):
        package.create_package(source, output, "0.5.8")


def test_stale_executable_version_is_rejected(bundle, monkeypatch):
    source, output = bundle
    monkeypatch.setattr(package, "executable_version", lambda _path: "0.5.7")
    with pytest.raises(ValueError, match="버전"):
        package.create_package(source, output, "0.5.8")


def test_missing_native_runtime_is_rejected(bundle):
    source, output = bundle
    (source / "_internal/winsound.pyd").unlink()
    with pytest.raises(ValueError, match="Windows"):
        package.create_package(source, output, "0.5.8")


def test_foreign_icu_runtime_cannot_shadow_windows_icu(bundle):
    source, output = bundle
    (source / "_internal/icuuc.dll").write_bytes(b"wrong ICU version")
    with pytest.raises(ValueError, match="ICU"):
        package.create_package(source, output, "0.5.8")


@pytest.mark.parametrize(
    "attack",
    [
        "changed",
        "missing",
        "extra",
        "duplicate",
        "../escape",
        "DesktopBuddy/../escape",
        "DesktopBuddy/C:/bad",
    ],
)
def test_incomplete_or_modified_archive_is_rejected(bundle, attack):
    source, output = bundle
    package.create_package(source, output, "0.5.8")
    with zipfile.ZipFile(output) as archive:
        records = {name: archive.read(name) for name in archive.namelist()}
    target = "DesktopBuddy/_internal/winsound.pyd"
    if attack == "changed":
        records[target] = b"corrupted"
    elif attack == "missing":
        del records[target]
    elif attack == "extra":
        records["DesktopBuddy/unlisted.txt"] = b"extra"
    elif attack != "duplicate":
        records[attack] = b"unsafe path"
    with zipfile.ZipFile(output, "w") as archive:
        for name, data in records.items():
            archive.writestr(name, data)
        if attack == "duplicate":
            with pytest.warns(UserWarning):
                archive.writestr(target, b"duplicate")
    with pytest.raises(ValueError):
        package.verify_archive(output)


def test_manifest_hash_mismatch_is_rejected_even_when_sizes_match(bundle):
    source, output = bundle
    package.create_package(source, output, "0.5.8")
    with zipfile.ZipFile(output) as archive:
        records = {name: archive.read(name) for name in archive.namelist()}
    target = "DesktopBuddy/_internal/winsound.pyd"
    records[target] = b"RUNTIME"
    with zipfile.ZipFile(output, "w") as archive:
        for name, data in records.items():
            archive.writestr(name, data)
    with pytest.raises(ValueError, match="SHA-256"):
        package.verify_archive(output)


def test_failed_zip_write_preserves_previous_artifact(bundle, monkeypatch):
    source, output = bundle
    output.parent.mkdir()
    output.write_bytes(b"previous release")

    def fail(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(package.zipfile.ZipFile, "write", fail)
    with pytest.raises(OSError):
        package.create_package(source, output, "0.5.8")
    assert output.read_bytes() == b"previous release"
    assert not list(output.parent.glob(".package-*.zip"))


def test_output_cannot_be_inside_the_bundle(bundle):
    source, output = bundle
    with pytest.raises(ValueError, match="폴더 밖"):
        package.create_package(source, source / "release.zip", "0.5.8")


@pytest.mark.parametrize(
    "manifest", [[], {"format_version": 2}, {"format_version": 1, "files": [{"path": []}]}]
)
def test_malformed_manifest_is_rejected(bundle, manifest):
    source, output = bundle
    package.create_package(source, output, "0.5.8")
    with zipfile.ZipFile(output) as archive:
        records = {name: archive.read(name) for name in archive.namelist()}
    records[package.MANIFEST] = json.dumps(manifest).encode()
    with zipfile.ZipFile(output, "w") as archive:
        for name, data in records.items():
            archive.writestr(name, data)
    with pytest.raises(ValueError):
        package.verify_archive(output)
