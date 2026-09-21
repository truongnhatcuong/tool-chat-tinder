"""Detect questions in natural Vietnamese chat, with or without a `?`.

Signals combined (strongest first):
  1. an explicit `?`
  2. interrogative words: ai, gì/j/chi, đâu/mô, sao/răng, bao lâu, bao nhiêu, mấy giờ, khi nào...
  3. sentence structure: "A hay B", "hay là ...", "kể nghe coi"
  4. sentence-final question particles: hả, à, không/k/ko, chưa, nhỉ ("nay b đi học hả")
  5. conversation history: a reworded copy of a question we already asked

Reactions that merely look like questions ("ủa thiệt hả", "chưa hả", "vậy à") and
statements that reuse the same words ("không sao", "chả biết gì", "bảo sao k đuối",
"tui đâu có đi") are filtered out first, so they do not count as asking.
"""
import re
from dataclasses import dataclass

try:
    from rapidfuzz import fuzz as _fuzz

    def _similar(a: str, b: str) -> float:
        return max(_fuzz.ratio(a, b), _fuzz.token_sort_ratio(a, b))

except ImportError:  # pragma: no cover
    import difflib

    def _similar(a: str, b: str) -> float:
        return difflib.SequenceMatcher(None, a, b).ratio() * 100

HISTORY_THRESHOLD = 80.0
MIN_HISTORY_CHARS = 8

# emoticons / emoji act as clause breaks: "chưa hả :)) tối ni b tính làm gì z"
_EMOTICON_RE = re.compile(
    r"[:=;]-?[)(dpo]+|<3|[\U0001F300-\U0001FAFF☀-➿⭐️]+", re.IGNORECASE
)
_CLAUSE_RE = re.compile(r"[^.!?\n]+[.!?\n]*")

# --- things that look like questions but are not -------------------------------------
_NOT_QUESTION_PATTERNS = [
    re.compile(p) for p in (
        r"\b(bảo sao|thảo nào|chả trách|hèn chi|hèn gì)\b",                       # "no wonder"
        r"\b(không|k|ko|hong|hông|khum) sao( đâu| mà| đó| hết)?\b|\bcó sao đâu\b",                   # "it's fine"
        r"\b(vậy|thế) sao$",                                                       # "is that so" (reaction)
        r"\b(không|k|ko|chả|chẳng|hổng|chưa) (đi|ở|có|làm|thấy|đến|biết|cần|nói) (\w+ )?(đâu|gì|j|chi)\b",
        r"\blàm (gì|j) có\b|\b(có gì|có j) (đâu|mà)\b",                            # rhetorical "có gì đâu"
        r"\bđâu (có|phải|cần|dám|mà|hề|thể|biết|ngờ)\b",                          # "đâu có" = not at all
        r"\bai (cũng|đó|nấy|biết|mà|ai)\b",                                        # "ai cũng", "ai đó"
        r"\bthế nào cũng\b|\bgì cũng\b|\bđâu cũng\b|\bsao cũng\b",                 # "whatever/anything"
        # pure reactions ending in a particle
        r"\b(ủa |ơ |ê )?(thiệt|thật|z|vậy|thế|luôn|chưa|rồi|ra là vậy|ra vậy|ừ|ok|oke|hiểu) (hả|à|ạ|hen|á)$",
    )
]

_WH_PATTERNS = [
    re.compile(p) for p in (
        r"\b(ai|gì|j|chi|đâu|mô|răng)\b",
        r"\b(bao lâu|bao nhiêu|bao nhiu|bao giờ|khi nào|lúc nào|hồi nào|chừng nào)\b",
        r"\b(mấy giờ|mấy tuổi|mấy năm|mấy người|mấy anh em)\b",
        r"\b(thế nào|như nào|ra sao|tại sao|vì sao|làm sao|mần chi)\b",
        r"^sao\b|\bsao$|\bsao (z|vậy|thế|lại|mà|không|k|ko|hả|á|nè|nhỉ)\b",       # "sao" only as "why/how"
        r"\b\w+ nào$",                                                            # "thích quán nào"
    )
]
_SOLICIT_RE = re.compile(r"\b(kể|nói|chỉ) (tui |t |mình |mik )?(nghe|coi|xem)\b")

_PARTICLE_RE = re.compile(
    r"\b(hả+|à+|nhỉ+|không|khum|hông|hong|ko|k|chưa|chăng)( (ạ|á|nè|nha|z|vậy|thế))?$"
)
_INTERJECTIONS = {"ủa", "ơ", "ê", "ồ", "ui", "ừ", "ờ", "ừa", "ờ", "à", "ha", "hen", "oke", "ok"}
_REACTION_WORDS = {"thiệt", "thật", "z", "vậy", "thế", "luôn", "ghê", "dữ", "r", "rồi", "ha", "hen", "chưa"}

# "hay" as "or" (A hay B) vs adverb "often" (b hay đi cf) vs adjective "good" (hay ghê)
_HAY_ADVERB_PREV = {
    "b", "bạn", "tui", "t", "mình", "mik", "tớ", "cậu", "em", "anh", "chị", "ai", "mọi", "người",
    "cũng", "thường", "rất", "khá", "cứ", "đâu", "luôn", "còn", "mà", "thì", "cả", "đã", "hay",
    "nghe", "thấy", "nhìn", "xem", "coi", "quá", "thật",
}
_HAY_ADJECTIVE_NEXT = {
    "ghê", "dữ", "quá", "lắm", "thật", "á", "nè", "đó", "đấy", "vậy", "thế", "luôn", "phết",
    "mà", "ha", "nha", "nhỉ", "r", "rồi", "đúng", "lên",
}


@dataclass(frozen=True)
class QuestionSignal:
    is_question: bool
    reason: str = ""


def _norm(text: str) -> str:
    text = (text or "").lower()
    text = _EMOTICON_RE.sub(" . ", text)
    return re.sub(r"\s+", " ", text).strip()


def _tokens(text: str) -> list[str]:
    return re.findall(r"[\wÀ-ỹ/]+", text)


def _has_alternative_hay(tokens: list[str]) -> bool:
    for i, tok in enumerate(tokens):
        if tok != "hay" or i == 0 or i == len(tokens) - 1:
            continue
        if tokens[i - 1] in _HAY_ADVERB_PREV or tokens[i + 1] in _HAY_ADJECTIVE_NEXT:
            continue
        return True
    return False


def _fragment_reason(fragment: str) -> str:
    """Why this comma/clause-level fragment is a question ('' if it is not)."""
    frag = fragment.strip()
    if not frag:
        return ""
    for pat in _NOT_QUESTION_PATTERNS:
        frag = pat.sub(" ", frag)
    frag = re.sub(r"\s+", " ", frag).strip()
    if not frag:
        return ""

    if _SOLICIT_RE.search(frag):
        return "solicit"
    if re.search(r"\bhay là\b|\bhay (không|k|ko)\b", frag):
        return "alternative"
    for pat in _WH_PATTERNS:
        if pat.search(frag):
            return "wh-word"
    toks = _tokens(frag)
    if _has_alternative_hay(toks):
        return "alternative"

    m = _PARTICLE_RE.search(frag)
    if m:
        before = [
            t for t in _tokens(frag[: m.start()])
            if t not in _INTERJECTIONS and t not in _REACTION_WORDS
        ]
        if len(before) >= 2:
            return "final-particle"
    return ""


def _question_fragments(text: str) -> list[str]:
    """Question fragments (clauses, split further on commas) found in `text`."""
    found: list[str] = []
    for m in _CLAUSE_RE.finditer(_norm(text)):
        chunk = m.group(0)
        body = chunk.rstrip(".!?\n").strip()
        if not body:
            continue
        if "?" in chunk:
            found.append(body)
            continue
        fragments = [f for f in body.split(",") if f.strip()]
        reasons = [f for f in fragments if _fragment_reason(f)]
        if reasons:
            found.extend(reasons)
        elif _fragment_reason(body):
            found.append(body)
    return found


def detect_question(text: str, asked_history: list[str] | None = None) -> QuestionSignal:
    """Is this message asking something? `asked_history` = questions we already asked."""
    if not text or not text.strip():
        return QuestionSignal(False)
    if "?" in text:
        return QuestionSignal(True, "question-mark")
    for m in _CLAUSE_RE.finditer(_norm(text)):
        body = m.group(0).rstrip(".!?\n").strip()
        for frag in [f for f in body.split(",") if f.strip()] + [body]:
            reason = _fragment_reason(frag)
            if reason:
                return QuestionSignal(True, reason)

    # history: a reworded copy of a question we already asked is still a question
    norm = re.sub(r"[^\w\sÀ-ỹ]", " ", (text or "").lower())
    norm = re.sub(r"\s+", " ", norm).strip()
    if len(norm) >= MIN_HISTORY_CHARS:
        for old in asked_history or []:
            old_norm = re.sub(r"\s+", " ", re.sub(r"[^\w\sÀ-ỹ]", " ", (old or "").lower())).strip()
            if len(old_norm) >= MIN_HISTORY_CHARS and _similar(norm, old_norm) >= HISTORY_THRESHOLD:
                return QuestionSignal(True, "history")
    return QuestionSignal(False)


def is_question(text: str, asked_history: list[str] | None = None) -> bool:
    return detect_question(text, asked_history).is_question


def count_questions(text: str) -> int:
    """How many separate questions one message asks (to catch 'hỏi dồn' in a single message)."""
    if not text or not text.strip():
        return 0
    n = len(_question_fragments(text))
    if n == 0 and "?" in text:
        return 1
    return n
