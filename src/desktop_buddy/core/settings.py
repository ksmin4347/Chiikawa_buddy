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
