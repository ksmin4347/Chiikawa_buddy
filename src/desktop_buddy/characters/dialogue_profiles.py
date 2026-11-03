from dataclasses import dataclass


@dataclass(frozen=True)
class DialogueProfile:
    id: str
    name: str
    description: str


PROFILES = (
    DialogueProfile("moru", "모루", "기존 기본 말투"),
    DialogueProfile("chiikawa", "치이카와", "수줍고 조심스러운 짧은 반말. 편안할 때는 밝게 반응."),
    DialogueProfile("hachiware", "하치와레", "밝고 다정한 반말. 공감한 뒤 쉬운 설명과 해결책."),
    DialogueProfile(
        "usagi", "우사기", "감정에 맞는 감탄사 + (짧고 장난스러운 반말). 정보는 정확하게."
    ),
)
PROFILE_IDS = tuple(profile.id for profile in PROFILES)
PROFILE_VERSION = 1


def profile(character_id: str) -> DialogueProfile:
    return next((item for item in PROFILES if item.id == character_id), PROFILES[0])
