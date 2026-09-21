"""Last-resort replies, used only when every regeneration failed the quality check.

Silence is worse than a short natural line: the other person is left hanging. So
when the model keeps failing we (1) ask it once more with a hard change of
direction and (2) fall back to a small bank of neutral reactions / fresh open
questions. Every candidate must still PASS `check_reply`, so it never repeats
what we already sent, never re-asks a known topic and respects the question rhythm.
"""
import random
import re
from pathlib import Path

from ai.output_guard import find_violations
from ai.prompts import BASE_DIR
from ai.quality import QualityContext, check_reply, content_tokens, normalize
from ai.question_detector import is_question
from ai.schemas import AIReply
from utils.logger import logger

QUESTION_FILE = "cau_hoi.md"
_SKIP_SECTIONS = ("KHEN",)          # section 11 holds compliments, not questions
_BULLET_RE = re.compile(r'^\s*\*\s+"(.+)"\s*$')
_HEADING_RE = re.compile(r"^(#{1,3})\s+(.*)$")
_bank_cache: dict[str, object] = {"mtime": None, "path": None, "items": []}

# short, topic-neutral reactions (persona: Gen Z Việt, chữ thường, ngắn)
REACTIONS: list[str] = [
    "z cũng ổn á :))",
    "nghe cũng dc đó",
    "hiểu r :))",
    "ừa z cũng hay á",
    "thế thì ok luôn",
    "nghe có vẻ ổn á",
    "z là dc r nha",
    "ừ cũng đúng á",
    "chắc cũng vui đó :))",
]

# built-in questions, used only if cau_hoi.md is missing/unreadable: (text, question_key)
QUESTIONS: list[tuple[str, str]] = [
    ("dạo ni b hay nghe nhạc gì z", "music_taste"),
    ("cuối tuần b hay đi đâu chơi", "weekend_activity"),
    ("rảnh b hay làm gì z", "free_time"),
    ("b hay xem phim hay chơi game hơn", "movie_or_game"),
    ("b thích cf hay trà sữa hơn", "drink_preference"),
    ("b có quán ăn nào ruột k", "favorite_food_place"),
    ("nay b làm tới mấy giờ z", "work_hours_today"),
    ("b thuộc team ngủ sớm hay cú đêm", "sleep_habit"),
    ("b có hay đi biển k", "beach_habit"),
    ("dạo ni có gì vui k b", "recent_news"),
]


def load_question_bank(path: Path | None = None) -> list[tuple[str, str, str]]:
    """Questions from cau_hoi.md as (text, question_key, section). Cached until the file changes.

    Only quoted bullets (`* "..."`) that really are questions and pass the persona rules
    are kept; the compliment section is skipped. Returns [] if the file is unusable.
    """
    path = path or (BASE_DIR / QUESTION_FILE)
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return []
    if _bank_cache["path"] == str(path) and _bank_cache["mtime"] == mtime:
        return _bank_cache["items"]  # type: ignore[return-value]

    items: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    section = ""
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            head = _HEADING_RE.match(line)
            if head:
                section = head.group(2).strip()
                continue
            m = _BULLET_RE.match(line)
            if not m or any(s in section.upper() for s in _SKIP_SECTIONS):
                continue
            text = m.group(1).strip()
            norm = normalize(text)
            if not norm or norm in seen or not is_question(text) or find_violations([text], []):
                continue
            seen.add(norm)
            slug = "_".join(norm.split()[:5])
            items.append((text, f"cau_hoi:{slug}", section))
    except OSError as e:
        logger.warning(f"Could not read {QUESTION_FILE}: {e}")
        return []
    _bank_cache.update(mtime=mtime, path=str(path), items=items)
    return items


def _question_pool() -> list[tuple[str, str]]:
    bank = [(text, key) for text, key, _ in load_question_bank()]
    return bank or QUESTIONS[:]


def _ranked_questions(ctx: QualityContext, rng: random.Random) -> list[tuple[str, str]]:
    """Questions from cau_hoi.md, those touching the current topic first (then random)."""
    topic: set[str] = set()
    for _, text in ctx.dialogue[-6:]:
        topic |= content_tokens(text)
    for text in ctx.new_texts:
        topic |= content_tokens(text)
    pool = _question_pool()
    rng.shuffle(pool)
    return sorted(pool, key=lambda item: -len(content_tokens(item[0]) & topic))


def _candidates(ctx: QualityContext, rng: random.Random, limit: int = 60) -> list[AIReply]:
    """Candidate replies in priority order (reaction+question, question, reaction)."""
    recent_asked = ctx.last_asked[-2:]
    streak = len(recent_asked) == 2 and all(recent_asked)   # asked twice in a row -> no question now

    reactions = REACTIONS[:]
    rng.shuffle(reactions)
    questions = _ranked_questions(ctx, rng) if not streak else []

    out: list[AIReply] = []
    if not streak:
        for text, key in questions[:6]:
            for react in reactions[:4]:
                out.append(AIReply(messages=[react, text], reply_style="question", question_key=key))
                if len(out) >= limit:
                    break
        for text, key in questions:
            out.append(AIReply(messages=[text], reply_style="question", question_key=key))
    for react in reactions:
        out.append(AIReply(messages=[react], reply_style="react"))
    return out


def fallback_candidates(ctx: QualityContext, limit: int = 3) -> list[str]:
    """A few fresh lines that pass every check (used as inspiration in the rescue prompt)."""
    rng = random.Random()
    found: list[str] = []
    for cand in _candidates(ctx, rng):
        if len(cand.messages) == 1 and not check_reply(cand, ctx):
            found.append(cand.messages[0])
            if len(found) >= limit:
                break
    return found


def pick_fallback(ctx: QualityContext) -> AIReply | None:
    """First bank candidate that passes the full quality check, or None."""
    for cand in _candidates(ctx, random.Random()):
        if not check_reply(cand, ctx):
            return cand
    return None


def build_rescue_feedback(problems: list[str], recent_sent: list[str], suggestions: list[str]) -> str:
    seen: set[str] = set()
    reasons = "\n".join(f"- {p}" for p in problems if not (p in seen or seen.add(p)))
    sent = " | ".join(recent_sent[-3:]) or "(chưa có)"
    hints = "\n".join(f"- {s}" for s in suggestions)
    text = (
        "Các bản nháp trước đều bị loại vì:\n"
        f"{reasons}\n\n"
        "ĐÂY LÀ LẦN CUỐI, hãy đổi hướng HOÀN TOÀN:\n"
        f"- Không dùng lại từ/ý nào trong các tin tôi vừa gửi: {sent}\n"
        "- Phản hồi đúng tin mới nhất của họ bằng một ý MỚI, hoặc hỏi đúng 1 câu về một chủ đề khác chưa hỏi.\n"
        "- Ngắn (3-12 từ), tự nhiên, không trả WAIT.\n"
    )
    if hints:
        text += f"Gợi ý hướng mới (tự nghĩ câu riêng, đừng chép nguyên nếu không hợp):\n{hints}\n"
    return text + "\nTrả lại JSON đúng OUTPUT CONTRACT."
