"""Per-conversation memory: builds the final LLM context for ONE user (match).

Flow (see ConversationMemory.build_context):
  1. load ALL messages of this conversation_id only (isolation by key)
  2. load saved memory: conversations.summary + match_profiles.notes_json
     ({"facts": [...], "summarized_until_id": N})
  3. old messages not yet summarized are folded into summary/facts by the LLM
     (only when there are enough of them); the watermark is saved so nothing
     is summarized twice
  4. heuristic analysis: pronouns, styles of both sides, questions I already
     asked, current topic
  5. return ConversationContext -> render() gives the text block for the prompt
No new tables/columns: reuses the existing ones.
"""
import asyncio
import json
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Callable

from ai.question_detector import is_question
from database.db import get_db_session
from database.repository import (
    ConversationRepository,
    MatchProfileRepository,
    MessageRepository,
)
from utils.logger import logger

RECENT_LIMIT = 40          # normal window (spec: 20-50)
RECENT_MAX = 50            # hard cap when extending the window with unsummarized older msgs
SUMMARIZE_MIN_OLD = 12     # fold old messages into memory only when at least this many
SUMMARIZE_CHUNK = 80       # max messages sent to the LLM per summarize call
MAX_FACTS = 30
MAX_ASKED = 12
MAX_QUESTIONS_STORED = 30   # questions_already_asked kept per user
MAX_STYLES_STORED = 6       # last_reply_styles kept per user
MAX_CLOSED_TOPICS = 5       # topics the other person closed, kept per user
CLOSED_TOPIC_TTL = 8        # a closed topic stays closed for this many of our sent replies

SELF_TERMS = ["tui", "mình", "mik", "tớ", "anh", "em", "chị", "tao", "t"]
ADDRESS_TERMS = ["b", "bạn", "cậu", "ông", "anh", "em", "chị", "mày", "m"]
ABBREVIATIONS = ["k", "ko", "dc", "đc", "r", "z", "j", "b", "t", "sn", "nc", "kk", "xí"]
EMOTICON_RE = re.compile(
    r"[\U00010000-\U0010ffff]|:\)+|=\)+|:D|:\(|<3|\bkk+\b|\bhaha+\b|\bhihi+\b", re.I
)
QUESTION_RE = re.compile(
    r"\?|\b(không|k|ko|chưa|hả|nhỉ|thế nào|sao|ở đâu|gì|j|mấy|bao nhiêu|bao nhiu)(\s+(z|vậy|nhỉ|á|nè|nha|hả|thế))?\s*$", re.I
)
STOPWORDS = set(
    "và là của có không cũng thì mà nha nè á ơi ừ rồi r z vậy được dc k ko này kia đó ấy "
    "tui mình bạn b anh em chị cái một những các cho với ở đi lại thế sao gì j".split()
)

SUMMARY_SYSTEM_PROMPT = """Bạn là bộ nhớ hội thoại cho một tool chat Tinder. Nhiệm vụ: gộp tin nhắn CŨ vào bản tóm tắt và danh sách facts.
QUY TẮC:
- CHỈ ghi những gì được nói RÕ RÀNG trong tin nhắn hoặc trong tóm tắt/facts cũ. TUYỆT ĐỐI không suy đoán, không bịa.
- Facts là câu ngắn, mỗi fact một ý, gắn rõ chủ thể: "[họ] ..." hoặc "[tôi] ...". Ví dụ: "[họ] học năm 3 ĐH Kinh tế", "[họ] chưa đi trekking", "[tôi] đã nói ở Đà Nẵng".
- Giữ mọi fact cũ còn đúng, thêm fact mới, bỏ fact trùng/mâu thuẫn (ưu tiên thông tin mới). Tối đa 30 facts.
- Summary: 2-4 câu tiếng Việt về diễn biến, chủ đề đã nói, mood, câu hỏi nào đã hỏi/đã được trả lời.
- Chỉ trả về JSON hợp lệ: {"summary": "...", "facts": ["..."]}"""


@dataclass
class ConversationContext:
    conversation_id: str
    total_messages: int
    stage: str
    summary: str
    facts: list[str]
    recent: list[dict[str, str]]           # [{"who": "họ" | "tôi", "content": ...}]
    address: str
    style_them: str
    style_me: str
    asked_by_me: list[str]
    topic: str
    asked_intents: list[str] = field(default_factory=list)
    used_openers: list[str] = field(default_factory=list)
    recent_topics: list[str] = field(default_factory=list)
    recent_reply_patterns: list[str] = field(default_factory=list)
    new_messages: list[str] = field(default_factory=list)
    questions_asked: list[str] = field(default_factory=list)     # questions_already_asked (persisted)
    last_reply_styles: list[str] = field(default_factory=list)   # question/share/tease/flirt/compliment/...
    last_reply_asked: list[bool] = field(default_factory=list)   # did each recent turn ask something
    guidance: str = ""                                           # rhythm hints for this turn
    closed_topics: list[dict] = field(default_factory=list)      # active closed topics (not expired)
    reply_counter: int = 0                                       # how many replies we have really sent

    def render(self) -> str:
        """Text block dropped into the user prompt (facts, summary, recent, new message)."""
        facts_them = [f for f in self.facts if f.startswith("[họ]")]
        facts_me = [f for f in self.facts if f.startswith("[tôi]")]
        facts_other = [f for f in self.facts if f not in facts_them and f not in facts_me]
        them_text = "\n".join(f"- {f}" for f in facts_them + facts_other) or "- (chưa có)"
        me_text = "\n".join(f"- {f}" for f in facts_me) or "- (chưa có)"
        asked = "\n".join(f"- {q}" for q in self.asked_by_me) or "- (chưa hỏi gì)"
        questions_stored = "\n".join(f"- {q}" for q in self.questions_asked[-MAX_QUESTIONS_STORED:]) or "- (chưa có)"
        guidance_block = f"\n{self.guidance}\n" if self.guidance else ""
        labels = {"tôi": "TÔI (đã gửi)", "họ": "HỌ (đối phương)"}
        recent = "\n".join(
            f"{labels.get(m['who'], m['who'])}: {m['content']}" for m in self.recent
        ) or "(chưa có tin nào)"
        new = "\n".join(self.new_messages)
        return (
            f"CONVERSATION_STAGE: {self.stage} ({self.total_messages} tin)\n\n"
            f"FACT VỀ HỌ (đối phương trong conversation này):\n{them_text}\n\n"
            f"FACT VỀ TÔI ĐÃ XUẤT HIỆN TRONG CHAT:\n{me_text}\n\n"
            f"TÓM TẮT HỘI THOẠI CŨ:\n{self.summary or '(chưa có, cuộc trò chuyện còn ngắn)'}\n\n"
            f"CÁCH XƯNG HÔ: {self.address}\n"
            f"PHONG CÁCH CỦA HỌ: {self.style_them}\n"
            f"PHONG CÁCH CỦA TÔI: {self.style_me}\n"
            f"CHỦ ĐỀ HIỆN TẠI: {self.topic}\n"
            f"CÁC CHỦ ĐỀ VỪA NÓI GẦN ĐÂY (chọn chủ đề mới nếu cần đổi): {', '.join(self.recent_topics[-5:]) or '(chưa có)'}\n"
            f"PATTERN GẦN ĐÂY: {', '.join(self.recent_reply_patterns[-5:]) or '(chưa có)'}\n\n"
            f"CÂU TÔI ĐÃ HỎI RỒI (KHÔNG HỎI LẠI):\n{asked}\n"
            f"CÁC INTENT ĐÃ HỎI (TUYỆT ĐỐI KHÔNG HỎI LẠI DƯỚI BẤT KỲ HÌNH THỨC NÀO): {', '.join(self.asked_intents) or '(chưa có)'}\n"
            f"CÁC CÂU HỎI ĐÃ HỎI TRƯỚC ĐÂY (KHÔNG HỎI LẠI CÙNG VẤN ĐỀ, KỂ CẢ ĐỔI CÁCH HỎI):\n{questions_stored}\n"
            f"OPENER ĐÃ DÙNG (không dùng lại): {', '.join(self.used_openers) or '(chưa có)'}\n"
            f"{guidance_block}\n"
            f"{len(self.recent)} TIN GẦN NHẤT (cũ -> mới):\n{recent}\n\n"
            f"TIN MỚI NHẤT CỦA HỌ (đối phương, cần trả lời; các dòng TÔI ở trên là tin tôi đã gửi, KHÔNG trả lời chúng):\n{new}"
        )


# ----------------------------- heuristic analysis -----------------------------

def _words(text: str) -> list[str]:
    return re.findall(r"[\wÀ-ỹ]+", text.lower())


def detect_stage(total: int) -> str:
    if total <= 2:
        return "NEW_MATCH"
    if total <= 6:
        return "WARM_UP"
    if total <= 20:
        return "ACTIVE_CHAT"
    return "DEEP_CHAT"


def _count_terms(texts: list[str], terms: list[str]) -> Counter:
    c: Counter = Counter()
    for t in texts:
        for w in _words(t):
            if w in terms:
                c[w] += 1
    return c


def analyze_address(incoming: list[str], outgoing: list[str]) -> str:
    """Who calls whom what, from real usage (not from age guessing)."""
    them_self = _count_terms(incoming, SELF_TERMS).most_common(1)
    them_to_me = _count_terms(incoming, ADDRESS_TERMS).most_common(1)
    me_self = _count_terms(outgoing, SELF_TERMS).most_common(1)
    me_to_them = _count_terms(outgoing, ADDRESS_TERMS).most_common(1)
    parts = []
    if them_self:
        parts.append(f"họ xưng '{them_self[0][0]}'")
    if them_to_me:
        parts.append(f"gọi tôi là '{them_to_me[0][0]}'")
    if me_self:
        parts.append(f"tôi đang xưng '{me_self[0][0]}'")
    if me_to_them:
        parts.append(f"gọi họ là '{me_to_them[0][0]}'")
    if not parts:
        return "chưa rõ, dùng 'mình - bạn' và bắt chước họ khi họ đổi cách xưng"
    return "; ".join(parts) + " (giữ nhất quán, đừng tự đổi)"


def analyze_style(texts: list[str]) -> str:
    if not texts:
        return "chưa có dữ liệu"
    n = len(texts)
    avg_words = sum(len(_words(t)) for t in texts) / n
    lower = sum(1 for t in texts if t[:1].islower() or not t[:1].isalpha()) / n
    abbr = sum(1 for t in texts if any(w in ABBREVIATIONS for w in _words(t))) / n
    emo = sum(1 for t in texts if EMOTICON_RE.search(t)) / n
    ques = sum(1 for t in texts if is_question(t)) / n
    length = (
        "rất ngắn" if avg_words <= 4 else "ngắn" if avg_words <= 10
        else "vừa" if avg_words <= 20 else "dài"
    )
    return (
        f"tin {length} (~{avg_words:.0f} từ), "
        f"{'chữ thường' if lower > 0.6 else 'viết hoa chuẩn'}, "
        f"{'hay viết tắt' if abbr > 0.3 else 'ít viết tắt'}, "
        f"{'hay dùng icon/emoji' if emo > 0.4 else 'ít icon' if emo > 0.1 else 'gần như không icon'}, "
        f"{'hay hỏi' if ques > 0.4 else 'ít hỏi'}"
    )


def extract_asked_questions(outgoing: list[str]) -> list[str]:
    asked = [t.strip() for t in outgoing if is_question(t.strip())]
    return [q[:90] for q in asked[-MAX_ASKED:]]


def guess_topic(recent: list[dict[str, str]]) -> str:
    """Cheap topic guess: frequent content words of the last few messages + last thing they said."""
    tail = recent[-8:]
    words = [w for m in tail for w in _words(m["content"]) if len(w) >= 3 and w not in STOPWORDS]
    top = [w for w, _ in Counter(words).most_common(4)]
    last_them = next((m["content"] for m in reversed(recent) if m["who"] == "họ"), "")
    if not top and not last_them:
        return "chưa có (mới bắt đầu)"
    return f"từ khóa: {', '.join(top) or '-'}; họ vừa nói: \"{last_them[:80]}\""


# ----------------------------- memory manager -----------------------------

def _parse_json(text: str) -> dict[str, Any] | None:
    try:
        start, end = text.index("{"), text.rindex("}")
        data = json.loads(text[start:end + 1])
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _dedupe_facts(facts: list[Any]) -> list[str]:
    seen, out = set(), []
    for f in facts:
        f = str(f).strip()
        key = f.lower()
        if f and key not in seen:
            seen.add(key)
            out.append(f)
    return out[-MAX_FACTS:]


class ConversationMemory:
    """Builds per-user context and keeps summary/facts up to date in the DB."""

    def __init__(self, llm_client, session_factory: Callable = get_db_session):
        self.llm = llm_client
        self._session = session_factory
        self._locks: dict[str, asyncio.Lock] = {}   # one summarize at a time per user

    async def build_context(
        self,
        conversation_id: str,
        new_messages: list[str] | None = None,
    ) -> ConversationContext:
        new_messages = new_messages or []
        async with self._session() as session:
            msgs = await MessageRepository(session).get_all_messages(conversation_id)
            conv = await ConversationRepository(session).get_by_id(conversation_id)
            profile = await MatchProfileRepository(session).get_by_match_id(conversation_id)

        summary = (conv.summary if conv else "") or ""
        notes = self._load_notes(profile.notes_json if profile else None)
        facts, watermark = notes["facts"], notes["summarized_until_id"]

        # The pending (unanswered) messages are already stored; show them once, as "new".
        n = len(new_messages)
        if n and [m.content for m in msgs[-n:]] == list(new_messages):
            msgs = msgs[:-n]

        # Split: recent window vs older messages not yet folded into memory.
        window_start = max(0, len(msgs) - RECENT_LIMIT)
        older_unsummarized = [m for m in msgs[:window_start] if m.id > watermark]
        if len(older_unsummarized) >= SUMMARIZE_MIN_OLD:
            summary, facts = await self._summarize(conversation_id, summary, facts, older_unsummarized)
        elif older_unsummarized:
            # too few to summarize: keep them visible instead of dropping (cap RECENT_MAX)
            window_start = max(0, len(msgs) - RECENT_MAX, window_start - len(older_unsummarized))

        window = msgs[window_start:]
        recent = [
            {"who": "tôi" if m.role == "outgoing" else "họ", "content": m.content} for m in window
        ]
        incoming = [m.content for m in msgs if m.role == "incoming"]
        outgoing = [m.content for m in msgs if m.role == "outgoing"]
        total = len(msgs) + n

        return ConversationContext(
            conversation_id=conversation_id,
            total_messages=total,
            stage=detect_stage(total),
            summary=summary,
            facts=facts,
            recent=recent,
            address=analyze_address(incoming[-30:] + new_messages, outgoing[-30:]),
            style_them=analyze_style(incoming[-30:] + new_messages),
            style_me=analyze_style(outgoing[-30:]),
            asked_by_me=extract_asked_questions(outgoing),
            asked_intents=notes.get("asked_intents", []),
            used_openers=notes.get("used_openers", []),
            recent_topics=notes.get("recent_topics", []),
            recent_reply_patterns=notes.get("recent_reply_patterns", []),
            topic=guess_topic(recent + [{"who": "họ", "content": t} for t in new_messages]),
            new_messages=list(new_messages),
            questions_asked=notes.get("questions_already_asked", []),
            last_reply_styles=notes.get("last_reply_styles", []),
            last_reply_asked=notes.get("last_reply_asked", []),
            closed_topics=[
                e for e in notes.get("closed_topics", [])
                if notes.get("reply_counter", 0) - int(e.get("at", 0) or 0) <= CLOSED_TOPIC_TTL
            ],
            reply_counter=notes.get("reply_counter", 0),
        )

    # ---- persistence helpers ----

    @staticmethod
    def _load_notes(raw: str | None) -> dict[str, Any]:
        data = (_parse_json(raw) if raw else None) or {}
        facts = data.get("facts")
        return {
            "facts": [str(f) for f in facts] if isinstance(facts, list) else [],
            "summarized_until_id": int(data.get("summarized_until_id", 0) or 0),
            "asked_intents": data.get("asked_intents", []),
            "used_openers": data.get("used_openers", []),
            "recent_topics": data.get("recent_topics", []),
            "recent_reply_patterns": data.get("recent_reply_patterns", []),
            "questions_already_asked": [str(q) for q in data.get("questions_already_asked", []) if q],
            "last_reply_styles": [str(s) for s in data.get("last_reply_styles", []) if s],
            "last_reply_asked": [bool(a) for a in data.get("last_reply_asked", [])],
            "closed_topics": [e for e in data.get("closed_topics", []) if isinstance(e, dict)],
            "reply_counter": int(data.get("reply_counter", 0) or 0),
        }

    async def _save(self, conversation_id: str, summary: str, facts: list[str], until_id: int) -> None:
        async with self._session() as session:
            conv_repo = ConversationRepository(session)
            if await conv_repo.get_by_id(conversation_id) is None:
                await conv_repo.upsert_conversation(conversation_id, conversation_id)
            await conv_repo.update_summary(conversation_id, summary)
            profile_repo = MatchProfileRepository(session)
            existing = await profile_repo.get_by_match_id(conversation_id)
            notes = (_parse_json(existing.notes_json) if existing and existing.notes_json else None) or {}
            notes = {**notes, "facts": facts, "summarized_until_id": until_id}
            await profile_repo.upsert_profile(match_id=conversation_id, notes_json=notes)

    async def update_advanced_memory(self, conversation_id: str, new_intent: str, new_topic: str, new_pattern: str, is_opener: bool = False, sent_messages: list[str] = None) -> None:
        async with self._session() as session:
            profile_repo = MatchProfileRepository(session)
            existing = await profile_repo.get_by_match_id(conversation_id)
            if not existing:
                return
            
            notes = (_parse_json(existing.notes_json) if existing.notes_json else None) or {}
            
            if new_intent:
                intents = notes.get("asked_intents", [])
                if new_intent not in intents:
                    intents.append(new_intent)
                    notes["asked_intents"] = intents[-MAX_ASKED:]
            
            if new_topic:
                topics = notes.get("recent_topics", [])
                if not topics or topics[-1] != new_topic:
                    topics.append(new_topic)
                    notes["recent_topics"] = topics[-5:]
                    
            if new_pattern:
                patterns = notes.get("recent_reply_patterns", [])
                patterns.append(new_pattern)
                notes["recent_reply_patterns"] = patterns[-5:]
                
            if is_opener and sent_messages:
                openers = notes.get("used_openers", [])
                openers.append(sent_messages[0])
                notes["used_openers"] = openers[-5:]

            await profile_repo.upsert_profile(match_id=conversation_id, notes_json=notes)

    async def record_sent_reply(
        self,
        conversation_id: str,
        *,
        reply_style: str = "",
        asked: bool = False,
        question_key: str = "",
        question_texts: list[str] | None = None,
    ) -> None:
        """Persist what a reply that was ACTUALLY sent did (questions asked, style rhythm).

        Called only after a real send so a rejected/regenerated suggestion never
        pollutes `questions_already_asked` or `last_reply_styles`.
        """
        async with self._session() as session:
            profile_repo = MatchProfileRepository(session)
            existing = await profile_repo.get_by_match_id(conversation_id)
            notes = (_parse_json(existing.notes_json) if existing and existing.notes_json else None) or {}

            questions = [str(q) for q in notes.get("questions_already_asked", []) if q]
            for q in question_texts or []:
                q = q.strip()
                if q and q not in questions:
                    questions.append(q[:120])
            notes["questions_already_asked"] = questions[-MAX_QUESTIONS_STORED:]

            if question_key:
                keys = notes.get("asked_intents", [])
                if question_key not in keys:
                    keys.append(question_key)
                notes["asked_intents"] = keys[-MAX_QUESTIONS_STORED:]

            if reply_style:
                styles = [str(s) for s in notes.get("last_reply_styles", []) if s]
                styles.append(reply_style)
                notes["last_reply_styles"] = styles[-MAX_STYLES_STORED:]
            flags = [bool(a) for a in notes.get("last_reply_asked", [])]
            flags.append(bool(asked))
            notes["last_reply_asked"] = flags[-MAX_STYLES_STORED:]
            notes["reply_counter"] = int(notes.get("reply_counter", 0) or 0) + 1

            await profile_repo.upsert_profile(match_id=conversation_id, notes_json=notes)

    async def record_closed_topic(self, conversation_id: str, entry: dict) -> None:
        """Remember a topic the other person closed ("hong á", "thôi bỏ qua"...) so later turns
        do not bring it up again (until CLOSED_TOPIC_TTL of our replies have passed)."""
        if not entry or not (entry.get("tokens") or entry.get("text")):
            return
        async with self._session() as session:
            profile_repo = MatchProfileRepository(session)
            existing = await profile_repo.get_by_match_id(conversation_id)
            notes = (_parse_json(existing.notes_json) if existing and existing.notes_json else None) or {}
            topics = [e for e in notes.get("closed_topics", []) if isinstance(e, dict)]
            counter = int(notes.get("reply_counter", 0) or 0)
            entry = {**entry, "at": counter}
            if topics and topics[-1].get("text") == entry.get("text") and topics[-1].get("at") == counter:
                return  # same closure recorded twice in one turn (regenerate/retry)
            topics.append(entry)
            notes["closed_topics"] = topics[-MAX_CLOSED_TOPICS:]
            await profile_repo.upsert_profile(match_id=conversation_id, notes_json=notes)

    async def _summarize(self, conversation_id, summary, facts, old_msgs) -> tuple[str, list[str]]:
        lock = self._locks.setdefault(conversation_id, asyncio.Lock())
        async with lock:
            chunk = old_msgs[:SUMMARIZE_CHUNK]   # the rest is handled on the next call
            transcript = "\n".join(
                f"{'TÔI' if m.role == 'outgoing' else 'HỌ'}: {m.content}" for m in chunk
            )
            user_prompt = (
                f"TÓM TẮT CŨ:\n{summary or '(chưa có)'}\n\n"
                f"FACTS CŨ:\n{json.dumps(facts, ensure_ascii=False)}\n\n"
                f"TIN NHẮN MỚI CẦN GỘP (cũ -> mới):\n{transcript}"
            )
            try:
                raw = await self.llm.chat(
                    [{"role": "system", "content": SUMMARY_SYSTEM_PROMPT},
                     {"role": "user", "content": user_prompt}],
                    temperature=0.2, max_tokens=700,
                )
                data = _parse_json(raw)
                if not data or "summary" not in data:
                    raise ValueError("summary JSON missing")
                new_summary = str(data["summary"]).strip()
                new_facts = _dedupe_facts(list(data.get("facts") or []))
            except Exception as e:
                # Keep old memory and the old watermark: nothing lost, nothing invented, retry later.
                logger.warning(f"Summarize failed for {conversation_id}: {e}")
                return summary, facts

            await self._save(conversation_id, new_summary, new_facts, chunk[-1].id)
            logger.info(f"Memory updated for {conversation_id}: folded {len(chunk)} old messages.")
            return new_summary, new_facts
