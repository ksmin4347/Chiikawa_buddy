import re
from dataclasses import asdict, dataclass, fields

from desktop_buddy.core.metadata import DEFAULT_CHARACTER_NAME


@dataclass(frozen=True)
class Settings:
    character_name: str = DEFAULT_CHARACTER_NAME
    size: int = 176
    animation_speed: int = 100
    reduce_motion: bool = False
    always_on_top: bool = True
    bubbles_enabled: bool = True
    show_on_start: bool = True
    theme: str = "light"
    week_start: int = 6
    notifications_enabled: bool = True
    notifications_paused: bool = False
    quiet_enabled: bool = False
    quiet_start: str = "22:00"
    quiet_end: str = "08:00"
    focus_minutes: int = 25
    break_minutes: int = 5
    long_break_minutes: int = 15
    long_break_interval: int = 4
    auto_next_phase: bool = False
    timer_notifications: bool = True
    focus_quiet: bool = True
    mini_timer_mode: str = "focus"
    x: int | None = None
    y: int | None = None

    @classmethod
    def from_mapping(cls, values: dict) -> "Settings":
        defaults = cls()
        clean = {}
        for field in fields(cls):
            value = values.get(field.name, getattr(defaults, field.name))
            if field.name in {"x", "y"}:
                clean[field.name] = value if type(value) is int else None
            elif field.name in {"size", "animation_speed"}:
                lower, upper = (96, 320) if field.name == "size" else (50, 150)
                clean[field.name] = (
                    max(lower, min(upper, value))
                    if type(value) is int
                    else getattr(defaults, field.name)
                )
            elif field.name in {
                "focus_minutes",
                "break_minutes",
                "long_break_minutes",
                "long_break_interval",
            }:
                upper = (
                    1440
                    if field.name == "focus_minutes"
                    else (12 if field.name == "long_break_interval" else 240)
                )
                clean[field.name] = (
                    max(1, min(upper, value))
                    if type(value) is int
                    else getattr(defaults, field.name)
                )
            elif field.name == "mini_timer_mode":
                clean[field.name] = (
                    value if value in ("always", "focus", "hover", "never") else "focus"
                )
            elif field.name == "week_start":
                clean[field.name] = value if type(value) is int and value in (0, 6) else 6
            elif field.name in {"quiet_start", "quiet_end"}:
                clean[field.name] = (
                    value
                    if isinstance(value, str) and re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value)
                    else getattr(defaults, field.name)
                )
            elif field.name == "character_name":
                clean[field.name] = (
                    value.strip()[:20] or DEFAULT_CHARACTER_NAME
                    if isinstance(value, str)
                    else DEFAULT_CHARACTER_NAME
                )
            elif field.name == "theme":
                clean[field.name] = value if value in ("light", "dark") else "light"
            else:
                clean[field.name] = value if type(value) is bool else getattr(defaults, field.name)
        return cls(**clean)

    def to_mapping(self) -> dict:
        return asdict(self)
