"""Hard rule checks on generated Tinder messages.

The prompt only *asks* the model to behave; this module enforces the rules that
can be verified mechanically, so a bad draft is regenerated or dropped instead
of being sent.
"""
import re

from ai.question_detector import count_questions, is_question

_BANNED_START_RE = re.compile(r"^\s*(kk+|haha+|hihi+|hehe+|ồ|ô|à|ui|oh|wow)\b[\s,!.:)-]*", re.IGNORECASE)
_EMOTICON_D_RE = re.compile(r"(?<![\w:])[:;]D\b")
_PRONOUN_RE = re.compile(r"(?<!\w)(anh|em|bé|chị)(?!\w)", re.IGNORECASE)
_FAKE_COMMON_RE = re.compile(
    r"giống nhau|trùng hợp|cùng sở thích|giống mình|giống tui|hợp nhau ghê", re.IGNORECASE
)
_CHATBOT_RE = re.compile(
    r"còn bạn thì sao|thế em có đọc|rất vui được làm quen|báu vật|"
    r"tranh thủ nghỉ|nghỉ ngơi đi|đừng cầm máy|đừng nhìn màn hình|sức khỏe quan trọng|"
    r"cố gắng lên",
    re.IGNORECASE,
)
_GREETING_NAME_RE = re.compile(r"^\s*(chào|hello|hi|hey)\b", re.IGNORECASE)

MAX_WORDS_PER_MESSAGE = 30


def _has_pronoun_from_them(pronoun_hits: set[str], their_texts: list[str]) -> set[str]:
    """Return pronoun hits that the other person never used themselves."""
    their = " ".join(their_texts).lower()
    return {p for p in pronoun_hits if not re.search(rf"(?<!\w){re.escape(p)}(?!\w)", their)}


def find_violations(
    messages: list[str],
    their_texts: list[str] | None = None,
    *,
    is_opener: bool = False,
    name: str = "",
    recent_outgoing: list[str] | None = None,
) -> list[str]:
    """Return human-readable violations (Vietnamese); empty list means OK.

    `their_texts` are messages written by the *other person*; pronouns such as
    anh/em are only acceptable when they already used them first.
    """
    their_texts = their_texts or []
    problems: list[str] = []

    # Interview guard: after two consecutive question messages of ours, the
    # next draft must not ask again.
    last_two = (recent_outgoing or [])[-2:]
    if len(last_two) == 2 and all(is_question(m) for m in last_two) and any(is_question(m) for m in messages):
        problems.append("đã hỏi 2 lượt liên tiếp, lượt này không được hỏi tiếp (phản hồi/trêu/chia sẻ thôi)")

    if sum(count_questions(m) for m in messages) > 1:
        problems.append("hỏi nhiều hơn 1 câu hỏi trong một lượt (chỉ được tối đa 1 câu hỏi chính)")

    for m in messages:
        text = (m or "").strip()
        if not text:
            continue
        if _BANNED_START_RE.match(text):
            problems.append(f"mở đầu bằng từ cấm (kk/haha/hihi/ồ/à/ui): '{text}'")
        if _EMOTICON_D_RE.search(text):
            problems.append(f"dùng emoticon ':D': '{text}'")
        if len(text.split()) > MAX_WORDS_PER_MESSAGE:
            problems.append(f"quá dài (>{MAX_WORDS_PER_MESSAGE} từ): '{text[:40]}...'")
        if _FAKE_COMMON_RE.search(text):
            problems.append(f"tự nhận điểm chung/giống nhau khi chưa có dữ liệu: '{text}'")
        if _CHATBOT_RE.search(text):
            problems.append(f"câu sáo rỗng/kiểu chatbot/lời khuyên lặp: '{text}'")

        hits = {h.lower() for h in _PRONOUN_RE.findall(text)}
        if hits:
            bad = _has_pronoun_from_them(hits, their_texts)
            if bad:
                problems.append(
                    f"tự xưng/gọi {', '.join(sorted(bad))} khi đối phương chưa dùng cách xưng hô đó: '{text}'"
                )

        if is_opener:
            if name and _GREETING_NAME_RE.match(text) and name.lower() in text.lower():
                problems.append(f"opener rập khuôn 'chào {name} ...': '{text}'")

    # de-duplicate while preserving order
    seen: set[str] = set()
    return [p for p in problems if not (p in seen or seen.add(p))]


def build_retry_feedback(problems: list[str], *, json_reply: bool) -> str:
    bullets = "\n".join(f"- {p}" for p in problems)
    tail = (
        "Viết lại đúng JSON contract, ngắn, giống người thật, sửa hết các lỗi trên. "
        "Họ đang chờ trả lời nên KHÔNG trả WAIT; nếu khó hỏi thì chỉ cần phản hồi/trêu/chia sẻ ngắn."
        if json_reply
        else "Viết lại đúng 1 tin nhắn ngắn, giống người thật, sửa hết các lỗi trên."
    )
    return f"Bản nháp trước vi phạm quy tắc:\n{bullets}\n\n{tail}"
