import re
from datetime import date, time, timedelta

from desktop_buddy.models.chat import Intent

HELP = (
    "기본 모드에서는 아래 명령을 사용할 수 있어요.\n"
    "• 오늘 할 일 보여줘 / 내일 일정 보여줘\n"
    "• 오늘 얼마나 공부했어? / 이번 주 공부 시간 / 전체 공부 시간\n"
    "• 25분 집중 시작 / 5분 짧은 휴식 시작\n"
    "• 타이머 일시정지 / 타이머 재개 / 타이머 중지 / 타이머 초기화\n"
    "• 할 일 추가: 자료구조 복습\n"
    "• 내일 오후 3시에 알고리즘 공부 추가해줘\n"
    "• 내일 15:00 회의 일정 추가해줘\n"
    "• 오늘 자료구조 복습 완료해줘 / 완료 취소해줘 / 삭제해줘\n"
    "• 오늘 자료구조 복습 내일로 옮겨줘\n"
    "• 캘린더 열어줘 / 설정 열어줘 / 내 상태 알려줘\n"
    "한 번에 한 명령만 처리해요. 할 일·일정 변경은 확인 후 저장해요."
)
SMALL_TALK = {
    "오늘 공부하기 싫어": "reluctant",
    "공부하기 싫어": "reluctant",
    "나 오늘 시험 잘 봤어": "celebrate",
    "오늘 시험 잘 봤어": "celebrate",
    "오늘 계획 다 못 지켰어": "unfinished",
    "나 오늘 계획 다 못 지켰어": "unfinished",
    "나 좀 응원해 줘": "encourage",
    "응원해 줘": "encourage",
    "응원해줘": "encourage",
    "고마워": "thanks",
    "고마워요": "thanks",
}
DAY = r"오늘|내일|모레|\d{4}-\d{2}-\d{2}"


class SecretInputError(ValueError):
    pass


def validate_input(text: str) -> str:
    if re.search(
        r"\bsk-[A-Za-z0-9_-]{12,}|-----BEGIN .*PRIVATE KEY|api[_ -]?key\s*[:=]", text, re.I
    ):
        raise SecretInputError(
            "키로 보이는 내용은 채팅에 저장할 수 없어요. 현재는 오프라인 모드예요."
        )
    if not text.strip() or len(text) > 2000 or "\n" in text or "\r" in text:
        raise ValueError("명령을 한 줄로 1~2,000자 이내로 입력해 주세요.")
    return re.sub(r"\s+", " ", text.strip())


def day_value(value: str, today: date) -> date:
    if value in ("오늘", "내일", "모레"):
        return today + timedelta(days=("오늘", "내일", "모레").index(value))
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise ValueError("실제로 존재하는 날짜를 YYYY-MM-DD 형식으로 입력해 주세요.") from error


def _clock(hour: str | int, minute: str | int) -> time:
    try:
        return time(int(hour), int(minute))
    except ValueError as error:
        raise ValueError("시각은 00:00~23:59 사이로 입력해 주세요.") from error


def _time_prefix(text: str) -> tuple[time | None, time | None, bool, str]:
    if text.startswith("종일 "):
        return None, None, True, text[3:]
    match = re.match(r"(\d{1,2}):(\d{2})(?:\s*[~～-]\s*(\d{1,2}):(\d{2}))?(?:에)?\s+(.+)", text)
    if match:
        h, m, eh, em, rest = match.groups()
        return _clock(h, m), _clock(eh, em) if eh else None, False, rest
    match = re.match(r"(오전|오후) (\d{1,2})시(?:\s*(\d{1,2})분)?(?:에)?\s+(.+)", text)
    if match:
        ampm, hour, minute, rest = match.groups()
        hour = int(hour)
        if not 1 <= hour <= 12:
            raise ValueError("오전·오후 시각은 1~12시로 입력해 주세요.")
        return _clock(hour % 12 + (12 if ampm == "오후" else 0), minute or 0), None, False, rest
    if re.match(r"(?:\d+시|오전|오후|\d+:)", text):
        raise ValueError("시각을 '오후 3시' 또는 '15:00'처럼 입력해 주세요.")
    return None, None, False, text


def parse(text: str, today: date) -> Intent:
    text = validate_input(text)
    small_talk = SMALL_TALK.get(text.rstrip("!.?~"))
    if small_talk:
        return Intent("smalltalk", {"event": small_talk})
    if text in ("안녕", "안녕하세요", "안녕!", "도움말", "명령어"):
        return Intent("help")
    if text in ("캘린더 열어줘", "캘린더", "설정 열어줘", "설정"):
        return Intent("navigate", {"page": "settings" if text.startswith("설정") else "calendar"})
    if text in ("내 상태 알려줘", "타이머 상태", "현재 상태"):
        return Intent("status")
    match = re.fullmatch(rf"({DAY}) (할 일|일정)(?: 보여줘| 알려줘| 조회)?[?.]?", text)
    if match:
        day, kind = match.groups()
        return Intent(
            "list", {"day": day_value(day, today), "kind": "task" if kind == "할 일" else "event"}
        )
    match = re.fullmatch(
        r"(오늘|이번 ?주|이번 ?달|전체)(?: 얼마나 공부했어| 공부 시간| 누적 공부 시간)[?.]?", text
    )
    if match:
        return Intent("study", {"period": match[1].replace(" ", "")})
    match = re.fullmatch(
        r"(?:(\d+)시간\s*)?(?:(\d+)분\s*)?(집중|짧은 ?휴식|긴 ?휴식) 시작(?:해줘)?", text
    )
    if match and (match[1] or match[2]):
        minutes = int(match[1] or 0) * 60 + int(match[2] or 0)
        if not 1 <= minutes <= 1440:
            raise ValueError("타이머는 1~1,440분으로 입력해 주세요.")
        kind = {"집중": "focus", "짧은휴식": "short_break", "긴휴식": "long_break"}[
            match[3].replace(" ", "")
        ]
        return Intent("timer_start", {"minutes": minutes, "phase": kind})
    match = re.fullmatch(r"타이머 (일시정지|재개|중지|초기화)(?:해줘)?", text)
    if match:
        return Intent(
            {
                "일시정지": "timer_pause",
                "재개": "timer_resume",
                "중지": "timer_stop",
                "초기화": "timer_reset",
            }[match[1]]
        )
    match = re.fullmatch(rf"(?:({DAY}) )?할 일 추가\s*:\s*(.+)", text)
    if match:
        return _add(match[2], day_value(match[1] or "오늘", today), "task")
    match = re.fullmatch(rf"({DAY}) (.+?) 추가(?:해줘)?", text)
    if match:
        rest, kind = match[2], None
        for suffix, value in ((" 할 일", "task"), (" 일정", "event")):
            if rest.endswith(suffix):
                rest, kind = rest[: -len(suffix)], value
                break
        return _add(rest, day_value(match[1], today), kind)
    match = re.fullmatch(
        rf"(?:({DAY}) )?(?:(할 일|일정) )?(.+?) (완료 취소|완료|삭제)(?:해줘)?", text
    )
    if match:
        day, kind, title, action = match.groups()
        return _target(
            title,
            day_value(day or "오늘", today),
            kind,
            {"완료 취소": "uncomplete", "완료": "complete", "삭제": "delete"}[action],
        )
    match = re.fullmatch(rf"(?:({DAY}) )?(?:(할 일|일정) )?(.+?) ({DAY})로 옮겨줘", text)
    if match:
        day, kind, title, destination = match.groups()
        return _target(
            title, day_value(day or "오늘", today), kind, "move", day_value(destination, today)
        )
    raise ValueError("이 문장은 아직 지원하지 않아요.\n" + HELP)


def _add(text: str, day: date, kind: str | None) -> Intent:
    start, end, all_day, title = _time_prefix(text)
    if not 1 <= len(title) <= 200:
        raise ValueError("제목은 1~200자로 입력해 주세요.")
    if end and end <= start:
        raise ValueError("종료 시각은 같은 날 시작 시각 이후로 입력해 주세요.")
    return Intent(
        "add",
        {"day": day, "kind": kind, "title": title, "start": start, "end": end, "all_day": all_day},
    )


def _target(
    title: str, day: date, kind: str | None, action: str, destination: date | None = None
) -> Intent:
    if title in (
        "이",
        "이 할 일",
        "이 할 일을",
        "이 일정",
        "이 일정을",
        "그",
        "그 할 일",
        "그 할 일을",
        "그 일정",
        "그 일정을",
    ):
        raise ValueError("대상을 알 수 없어요. 날짜와 정확한 제목을 입력해 주세요.")
    return Intent(
        action,
        {
            "day": day,
            "title": title,
            "kind": {"할 일": "task", "일정": "event"}.get(kind),
            "destination": destination,
        },
    )
