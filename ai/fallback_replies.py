"""Last-resort replies used only when every model regeneration failed.

Fallbacks are deliberately reaction-only. Questions must be generated from the
current conversation context; a generic/random question is worse than a short
neutral acknowledgement.
"""
import random
from pathlib import Path

from ai.quality import QualityContext, check_reply
from ai.schemas import AIReply

# Short, topic-neutral reactions (persona: Gen Z Việt, chữ thường, ngắn).
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

def load_question_bank(path: Path | None = None) -> list[tuple[str, str, str]]:
    """Compatibility API: guidance files are never converted into reply templates."""
    return []


def _candidates(ctx: QualityContext, rng: random.Random, limit: int = 60) -> list[AIReply]:
    """Reaction-only candidates; never inject a context-free question."""
    reactions = REACTIONS[:]
    rng.shuffle(reactions)
    return [AIReply(messages=[react], reply_style="react") for react in reactions[:limit]]


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
        "ĐÂY LÀ LẦN CUỐI, hãy đổi cách diễn đạt HOÀN TOÀN:\n"
        f"- Không dùng lại từ/ý nào trong các tin tôi vừa gửi: {sent}\n"
        "- Phản hồi đúng tin mới nhất và mạch hiện tại bằng một ý MỚI; chỉ hỏi nếu có điểm bám thật trong context.\n"
        "- Ngắn (3-12 từ), tự nhiên, không trả WAIT.\n"
    )
    if hints:
        text += f"Gợi ý hướng mới (tự nghĩ câu riêng, đừng chép nguyên nếu không hợp):\n{hints}\n"
    return text + "\nTrả lại JSON đúng OUTPUT CONTRACT."
