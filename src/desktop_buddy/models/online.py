from dataclasses import dataclass


@dataclass(frozen=True, repr=False)
class OnlineRequest:
    id: str
    kind: str
    model: str
    text: str
    character_id: str
    allow_actions: bool = False
    local_date: str = ""


@dataclass(frozen=True, repr=False)
class ToolProposal:
    name: str
    arguments: str


@dataclass(frozen=True, repr=False)
class OnlineResult:
    text: str = ""
    input_tokens: int | None = None
    output_tokens: int | None = None
    error: str = ""
    proposal: ToolProposal | None = None


class OnlineError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code
