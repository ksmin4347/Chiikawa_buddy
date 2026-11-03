from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from desktop_buddy.models.planning import Occurrence


@dataclass(frozen=True)
class Intent:
    kind: str
    values: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Choice:
    key: str
    label: str


@dataclass(frozen=True)
class Reply:
    text: str
    request_id: str | None = None
    choices: tuple[Choice, ...] = ()


@dataclass(frozen=True)
class Pending:
    request_id: str
    intent: Intent
    summary: str
    expires_at: datetime
    fingerprint: str
    target: Occurrence | None = None
    choices: dict[str, Any] = field(default_factory=dict)
