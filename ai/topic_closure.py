"""Detect when the other person closes / denies / dismisses the current topic.

"hong á", "không", "thôi bỏ qua", "k có gì", "đâu có" ... mean the topic we just
raised is finished. Only the NEWEST message of theirs counts, and only when the
message is (almost) nothing but the denial - a longer message that merely starts
with "không" carries new content and is not a closure.
"""
import re
import unicodedata
from dataclasses import dataclass

_EMOTICON_RE = re.compile(
    r"[:=;]-?[)(dpo]+|<3|[\U0001F300-\U0001FAFF☀-➿⭐️]+", re.IGNORECASE
)
_PUNCT_RE = re.compile(r"[^\w\sÀ-ỹ]", re.UNICODE)

# explicit "drop it" phrases, valid anywhere in a short message
_DISMISS_RE = re.compile(
    r"\b(thôi bỏ qua|bỏ qua đi|thôi bỏ đi|thôi kệ|kệ đi|thôi khỏi|khỏi nói|đừng hỏi|hỏi chi nữa|hỏi làm gì|"
    r"không muốn nói|k muốn nói|ko muốn nói|không nói chuyện này|chuyện khác đi|nói chuyện khác|"
    r"đổi chủ đề|thôi không nói|thôi đừng|bỏ qua)\b"
)

_NEG_HEADS = {"không", "khum", "hông", "hong", "hok", "hổng", "hem", "k", "ko", "chả", "chẳng", "thôi", "khỏi"}
_NEG_HEAD_PHRASES = ("đâu có", "đâu phải", "đâu nà")
_NEG_REST = {
    "có", "gì", "j", "đâu", "đó", "nha", "nè", "á", "ạ", "à", "hà", "đi", "nữa", "cần", "muốn", "phải",
    "thôi", "luôn", "cũng", "nói", "sao", "nhé", "đấy", "mà", "ha", "hen", "z", "vậy", "thế", "ừ", "nhen",
    "chi", "ai", "đâu", "hết", "đâu", "tui", "t", "mình",
}
MAX_CLOSURE_TOKENS = 5


@dataclass(frozen=True)
class Closure:
    phrase: str      # what they said, normalized
    kind: str        # "negation" | "dismiss"


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFC", text or "").lower()
    text = _EMOTICON_RE.sub(" ", text)
    text = _PUNCT_RE.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def _is_negation_only(norm: str) -> bool:
    tokens = norm.split()
    if not tokens or len(tokens) > MAX_CLOSURE_TOKENS:
        return False
    head_ok = tokens[0] in _NEG_HEADS or any(norm.startswith(p) for p in _NEG_HEAD_PHRASES)
    if not head_ok:
        return False
    skip = 2 if any(norm.startswith(p) for p in _NEG_HEAD_PHRASES) else 1
    return all(t in _NEG_REST for t in tokens[skip:])


def detect_closure(texts: list[str]) -> Closure | None:
    """Closure signal of the NEWEST message in `texts` (older messages of the bundle are ignored)."""
    latest = next((t for t in reversed(texts or []) if t and t.strip()), "")
    norm = _normalize(latest)
    if not norm:
        return None
    if len(norm.split()) <= MAX_CLOSURE_TOKENS + 2 and _DISMISS_RE.search(norm):
        return Closure(norm, "dismiss")
    if _is_negation_only(norm):
        return Closure(norm, "negation")
    return None
