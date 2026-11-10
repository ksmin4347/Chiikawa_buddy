from dataclasses import dataclass


@dataclass(frozen=True, repr=False)
class OnlineRequest:
    id: str
    kind: str
    model: str
    text: str
    character_id: str


@dataclass(frozen=True, repr=False)
class OnlineResult:
    text: str = ""
    input_tokens: int | None = None
    output_tokens: int | None = None
    error: str = ""


class OnlineError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code
