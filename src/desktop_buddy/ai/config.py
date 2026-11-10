import re

DEFAULT_MODEL = "gpt-5.6-terra"
API_BASE = "https://api.openai.com/v1"
REQUEST_SECONDS = 60
MAX_RESPONSE_BYTES = 1024 * 1024
MAX_REPLY_CHARACTERS = 16000


def validate_model(value: str) -> str:
    if (
        not isinstance(value, str)
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", value) is None
        or value.lower().startswith("sk-")
    ):
        raise ValueError("모델 ID를 확인해 주세요. API 키는 전용 입력칸에 보관해요.")
    return value
