"""Read explicitly selected local files; replace an approved export atomically."""

import hashlib
import os
import stat
import tempfile
from pathlib import Path

from desktop_buddy.calendar.ics_codec import MAX_BYTES
from desktop_buddy.models.calendar_transfer import CalendarFileError


def check_path(path: Path) -> None:
    is_reserved = getattr(os.path, "isreserved", lambda value: value.is_reserved())
    if (
        not path.is_absolute()
        or path.suffix.casefold() != ".ics"
        or ":" in path.name
        or is_reserved(path)
    ):
        raise CalendarFileError("로컬 .ics 파일을 선택해 주세요.")
    if any(p.is_symlink() or p.is_junction() for p in (path, *path.parents)):
        raise CalendarFileError("링크나 연결 폴더 대신 실제 파일 위치를 선택해 주세요.")


def read_calendar(path: Path) -> bytes:
    check_path(path)
    if not stat.S_ISREG(path.stat().st_mode):
        raise CalendarFileError("일반 ICS 파일을 선택해 주세요.")
    with path.open("rb") as stream:
        data = stream.read(MAX_BYTES + 1)
    if not data or len(data) > MAX_BYTES:
        raise CalendarFileError("파일은 비어 있지 않은 8 MiB 이하 ICS여야 해요.")
    return data


def file_token(path: Path):
    check_path(path)
    if not path.exists():
        return None
    if not stat.S_ISREG(path.stat().st_mode):
        raise CalendarFileError("일반 ICS 파일 위치를 선택해 주세요.")
    with path.open("rb") as stream:
        data = stream.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise CalendarFileError("기존 파일이 8 MiB를 넘어요. 새 파일 위치를 선택해 주세요.")
    value = path.stat()
    return (
        value.st_dev,
        value.st_ino,
        value.st_size,
        value.st_mtime_ns,
        hashlib.sha256(data).hexdigest(),
    )


def write_calendar(path: Path, data: bytes, expected, cancelled=lambda: False) -> None:
    check_path(path)
    if not data or len(data) > MAX_BYTES:
        raise CalendarFileError("내보낼 파일 크기를 확인해 주세요.")
    if file_token(path) != expected:
        raise CalendarFileError("선택한 파일이 바뀌었어요. 저장 위치를 다시 선택해 주세요.")
    temporary = None
    try:
        descriptor, name = tempfile.mkstemp(
            prefix=".buddy-calendar-", suffix=".tmp", dir=path.parent
        )
        temporary = Path(name)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        check_path(path)
        if cancelled():
            raise CalendarFileError("파일 저장을 취소했어요.")
        if file_token(path) != expected:
            raise CalendarFileError("저장 중 대상 파일이 바뀌었어요. 다시 선택해 주세요.")
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
