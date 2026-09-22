"""Conversation quality checks run on every validated reply before it is sent.

Pipeline position:  Pydantic validate -> RapidFuzz duplicate check -> quality check.
Each check returns human-readable reasons (Vietnamese); an empty list means PASS.
The reasons are fed back to the model when it has to regenerate.
"""
import re
import unicodedata
from dataclasses import dataclass, field

from ai.output_guard import find_violations
from ai.question_detector import is_question
from ai.schemas import AIReply
from ai.topic_closure import Closure

try:  # RapidFuzz is the intended engine; keep a stdlib fallback so the bot never crashes.
    from rapidfuzz import fuzz as _fuzz

    def ratio(a: str, b: str) -> float:
        return max(_fuzz.ratio(a, b), _fuzz.token_sort_ratio(a, b))

    def partial(a: str, b: str) -> float:
        return _fuzz.partial_ratio(a, b)

except ImportError:  # pragma: no cover - only when the dependency is missing
    import difflib

    def ratio(a: str, b: str) -> float:
        return difflib.SequenceMatcher(None, a, b).ratio() * 100

    def partial(a: str, b: str) -> float:
        return 100.0 if a and a in b else ratio(a, b)

DUPLICATE_THRESHOLD = 85.0      # reply vs something we already sent
QUESTION_THRESHOLD = 80.0       # question vs a question we already asked
MIN_FUZZY_CHARS = 8             # don't fuzzy-match tiny reactions like "z á"
MIN_EXACT_CHARS = 4
STYLE_HISTORY = 6
ASKED_STREAK_LIMIT = 2          # two question turns in a row -> next turn must not ask
COMPLIMENT_COOLDOWN = 3         # a compliment in the last N turns blocks another
RECENT_SENT_WINDOW = 3          # how many of our latest messages a new reply is compared against
RECOMBINE_THRESHOLD = 80.0      # new reply vs our last 1-3 messages glued together
COVERAGE_REJECT = 0.7           # share of the new reply made of word-pairs we just sent
MIN_TOKENS_FOR_COVERAGE = 4
SEGMENT_REUSE_RATIO = 0.5       # MORE than this share of the reply's segments repeating what we just sent = reject
SEGMENT_THRESHOLD = 85.0

_PUNCT_RE = re.compile(r"[^\w\sÀ-ỹ]", re.UNICODE)
_SPACE_RE = re.compile(r"\s+")
_TOKEN_RE = re.compile(r"[\wÀ-ỹ]+", re.UNICODE)

# Words that carry no topic information (pronouns, particles, question words).
_FILLER = set(
    "b bạn tui t mình mik tớ cậu anh em chị ông và là của có không cũng thì mà nha nè á ơi ừ rồi r z vậy "
    "được dc đc k ko này kia đó ấy cái một những các cho với ở đi lại thế sao gì j hả nhỉ chưa à ạ nào đâu "
    "hay hen hén thôi luôn nữa kk haha".split()
)


def normalize(text: str) -> str:
    text = _PUNCT_RE.sub(" ", unicodedata.normalize("NFC", text or "").lower())
    return _SPACE_RE.sub(" ", text).strip()


def _content_tokens(text: str) -> set[str]:
    return {t for t in _TOKEN_RE.findall(normalize(text)) if t not in _FILLER}


def content_tokens(text: str) -> set[str]:
    """Topic words of a message (pronouns/particles/question words removed)."""
    return _content_tokens(text)


@dataclass
class QualityContext:
    """Everything the checks need to know about ONE conversation."""

    their_texts: list[str] = field(default_factory=list)       # messages written by them (incl. the new ones)
    known_texts: list[str] = field(default_factory=list)       # facts about them ("[họ] ...")
    my_sent: list[str] = field(default_factory=list)           # messages we already sent
    asked_questions: list[str] = field(default_factory=list)   # questions_already_asked (texts)
    asked_keys: list[str] = field(default_factory=list)        # question_key / intent already asked
    last_styles: list[str] = field(default_factory=list)       # last_reply_styles (oldest -> newest)
    last_asked: list[bool] = field(default_factory=list)       # did each recent turn contain a question
    their_active: bool = False                                 # they are chatting actively right now
    recent_sent: list[str] = field(default_factory=list)       # our last few messages, oldest -> newest
    new_texts: list[str] = field(default_factory=list)         # what they just said (the messages being answered)
    dialogue: list[tuple[str, str]] = field(default_factory=list)  # chronological ("them"|"me", text)
    closed_topics: list[dict] = field(default_factory=list)    # topics they closed: {tokens, phrase, text, at}
    closure_now: str = ""                                       # closing phrase in their NEWEST message ('' if none)
    closed_now: dict | None = None                             # the topic closed by that message (to persist)


# ------------------------------- checks -------------------------------

def reply_question_texts(reply: AIReply, ctx: QualityContext) -> list[str]:
    """Question messages: `?`, interrogative words, structure, particles, or a reworded old question."""
    qs = [m for m in reply.messages if is_question(m, ctx.asked_questions)]
    if not qs and reply.question_key and reply.messages:
        qs = [reply.messages[-1]]
    return qs


def reply_asks(reply: AIReply, ctx: QualityContext) -> bool:
    return bool(reply_question_texts(reply, ctx)) or reply.asks_question


def find_duplicate_replies(messages: list[str], past_sent: list[str]) -> list[str]:
    """RapidFuzz: is a new message too similar to one we already sent (or to its sibling)?"""
    problems: list[str] = []
    seen = [normalize(p) for p in past_sent if normalize(p)]
    for msg in messages:
        n = normalize(msg)
        if len(n) < MIN_EXACT_CHARS:
            continue
        for prev in seen:
            if n == prev:
                problems.append(f"trùng y hệt tin đã gửi trước đó: '{msg}'")
                break
            if len(n) >= MIN_FUZZY_CHARS and len(prev) >= MIN_FUZZY_CHARS:
                score = ratio(n, prev)
                if score >= DUPLICATE_THRESHOLD:
                    problems.append(f"quá giống tin đã gửi trước đó ({score:.0f}%): '{msg}'")
                    break
        seen.append(n)  # also catches two near-identical messages inside one reply
    return problems


_SEGMENT_SPLIT_RE = re.compile(
    r"[.!?\n,;]+|[:=;]-?[)(dpo]+|[\U0001F300-\U0001FAFF\u2600-\u27BF]+", re.IGNORECASE
)


def _segments(text: str) -> list[str]:
    """Normalized phrases of a message, split on punctuation/emoticons/emoji."""
    segs = [normalize(p) for p in _SEGMENT_SPLIT_RE.split(text or "")]
    return [s for s in segs if len(s.split()) >= 2 or len(s) >= 8]


def _bigrams(tokens: list[str]) -> set[tuple[str, str]]:
    return set(zip(tokens, tokens[1:]))


def find_recombined_replies(messages: list[str], recent_sent: list[str]) -> list[str]:
    """Catch a 'new' reply that is really our last 1-3 messages glued/paraphrased together.

    Three views, all on normalized text (case, punctuation, emoji, spacing removed):
      1. whole reply vs our last 1, 2 and 3 messages joined
      2. share of the reply made of word-pairs we already sent
      3. share of its phrases that repeat a phrase we already sent
    """
    recent = [normalize(t) for t in (recent_sent or [])[-RECENT_SENT_WINDOW:] if normalize(t)]
    new_norm = normalize(" ".join(messages))
    if not recent or not new_norm:
        return []
    problems: list[str] = []

    # 1. glued windows
    if len(new_norm) >= MIN_FUZZY_CHARS:
        best = 0.0
        for k in range(1, len(recent) + 1):
            best = max(best, ratio(new_norm, " ".join(recent[-k:])))
        if best >= RECOMBINE_THRESHOLD:
            problems.append(
                f"ghép lại từ các tin vừa gửi ({best:.0f}% giống 1-3 tin gần nhất): '{' '.join(messages)}'"
            )

    # 2. word-pair coverage
    new_tokens = new_norm.split()
    if len(new_tokens) >= MIN_TOKENS_FOR_COVERAGE:
        sent_pairs = _bigrams(" ".join(recent).split())
        covered: set[int] = set()
        for i, pair in enumerate(zip(new_tokens, new_tokens[1:])):
            if pair in sent_pairs:
                covered.update((i, i + 1))
        share = len(covered) / len(new_tokens)
        if share >= COVERAGE_REJECT:
            problems.append(
                f"{share:.0%} nội dung chỉ tái sử dụng cụm từ trong 1-3 tin vừa gửi, chưa có ý mới"
            )

    # 3. phrase reuse
    new_segs = [s for m in messages for s in _segments(m)]
    old_segs = [s for t in (recent_sent or [])[-RECENT_SENT_WINDOW:] for s in _segments(t)]
    if len(new_segs) >= 2 and old_segs:
        reused = sum(
            1 for s in new_segs
            if any(
                ratio(s, o) >= SEGMENT_THRESHOLD
                or (len(s) >= MIN_FUZZY_CHARS and partial(s, o) >= 95 and len(s) >= 0.6 * len(o))
                for o in old_segs
            )
        )
        if reused / len(new_segs) > SEGMENT_REUSE_RATIO:
            problems.append(
                f"{reused}/{len(new_segs)} phần của câu đang lặp lại cụm ý vừa gửi ở 1-3 tin gần nhất"
            )
    return problems


def _reaction_pairs(dialogue: list[tuple[str, str]]) -> list[tuple[str, list[str]]]:
    """[(their message, [our messages that followed it before they spoke again])]"""
    pairs: list[tuple[str, list[str]]] = []
    for who, text in dialogue:
        if who == "them":
            pairs.append((text, []))
        elif pairs:
            pairs[-1][1].append(text)
    return [(t, ours) for t, ours in pairs if ours]


def find_repeated_fact_reactions(reply: AIReply, ctx: QualityContext) -> list[str]:
    """Do not react a second time to a fact of theirs that we already reacted to.

    A statement/reaction in the new reply is flagged when it reuses key words of an
    OLD message of theirs (not words from what they just said) and one of our
    earlier messages already reacted to those same words. Follow-up questions that
    deepen the topic are allowed.
    """
    pairs = _reaction_pairs(ctx.dialogue)
    if not pairs:
        return []
    current: set[str] = set()
    for t in ctx.new_texts:
        current |= _content_tokens(t)

    problems: list[str] = []
    for msg in reply.messages:
        if is_question(msg, ctx.asked_questions):
            continue
        msg_tokens = _content_tokens(msg)
        for their, ours in pairs[-8:]:
            fact = _content_tokens(their)
            if not fact:
                continue
            shared = (msg_tokens & fact) - current
            if len(shared) < (1 if len(fact) <= 3 else 2):
                continue
            if any(shared & _content_tokens(o) for o in ours):
                problems.append(
                    f"đã phản ứng với điều họ nói ('{their[:40]}') rồi, không phản ứng lại lần hai: '{msg}'"
                )
                break
    return problems


def build_closed_topic(
    closure: Closure | None,
    dialogue: list[tuple[str, str]],
    new_texts: list[str],
    counter: int = 0,
) -> dict | None:
    """The topic they just closed = what WE said right before their denial/dismissal."""
    if not closure:
        return None
    block: list[str] = []
    skipping_new = True
    for who, text in reversed(dialogue):
        if skipping_new and who == "them" and text in new_texts:
            continue  # the bundle being answered may already be in the history
        skipping_new = False
        if who == "me":
            block.append(text)
        elif block:
            break
    text = " | ".join(reversed(block[:2]))
    return {
        "tokens": sorted(_content_tokens(text)),
        "phrase": closure.phrase,
        "text": text,
        "at": counter,
    }


def find_closed_topic_problems(reply: AIReply, ctx: QualityContext) -> list[str]:
    """After they close a topic: no re-asking, re-explaining, or reacting to it again.

    Also, when the closure is in THEIR NEWEST message, a reaction must not fall back
    on an older message of theirs (it must answer the newest one).
    """
    if not ctx.closed_topics and not ctx.closure_now:
        return []
    current: set[str] = set()
    for t in ctx.new_texts:
        current |= _content_tokens(t)

    problems: list[str] = []
    for entry in ctx.closed_topics:
        closed = set(entry.get("tokens", []))
        if not closed:
            continue
        for msg in reply.messages:
            shared = (_content_tokens(msg) & closed) - current   # they did not bring it up again
            if shared:
                problems.append(
                    f"chủ đề '{', '.join(sorted(shared))}' đã bị họ đóng"
                    f"{' (' + entry['phrase'] + ')' if entry.get('phrase') else ''}; "
                    f"không hỏi lại/giải thích lại/phản ứng lại: '{msg}'"
                )
                break

    if ctx.closure_now:
        old_theirs = [t for who, t in ctx.dialogue if who == "them" and t not in ctx.new_texts][-6:]
        for msg in reply.messages:
            if is_question(msg, ctx.asked_questions):
                continue
            msg_tokens = _content_tokens(msg)
            for old in old_theirs:
                fact = _content_tokens(old)
                shared = (msg_tokens & fact) - current
                if fact and len(shared) >= (1 if len(fact) <= 3 else 2):
                    problems.append(
                        f"đang trả lời lại tin cũ của họ ('{old[:40]}') thay vì tin mới nhất ('{ctx.closure_now}'): '{msg}'"
                    )
                    break
    return problems


_ECHO_LEAD_RE = re.compile(r"^(vậy|z|thế|vậy là|z là|thế là)")


def find_echo_replies(messages: list[str], new_texts: list[str]) -> list[str]:
    """Parroting: a short reply whose every topic word is already in their newest message.

    Such a reply ("vậy là cũng vừa sức á" after "vừa sức th") adds no new idea.
    Real questions are allowed, since asking about their word deepens the topic.
    """
    theirs: set[str] = set()
    for t in new_texts:
        theirs |= _content_tokens(t)
    if not theirs:
        return []
    problems: list[str] = []
    for msg in messages:
        n = normalize(msg)
        tokens = _content_tokens(msg)
        if not tokens or len(n.split()) > 7:
            continue
        if tokens <= theirs and (_ECHO_LEAD_RE.match(n) or not is_question(msg)):
            problems.append(f"nhại lại lời họ vừa nói, chưa có ý mới: '{msg}'")
    return problems


def find_repeated_questions(reply: AIReply, ctx: QualityContext) -> list[str]:
    """Same topic asked again: by question_key, by similar wording, or already told by them."""
    problems: list[str] = []
    key = normalize(reply.question_key).replace(" ", "_")
    if key:
        for old in ctx.asked_keys:
            old_key = normalize(old).replace(" ", "_")
            if old_key and (old_key == key or ratio(old_key, key) >= 90):
                problems.append(f"đã hỏi vấn đề '{reply.question_key}' rồi, không hỏi lại")
                break

    asked = [normalize(q) for q in ctx.asked_questions if normalize(q)]
    for q in reply_question_texts(reply, ctx):
        nq = normalize(q)
        if len(nq) < MIN_FUZZY_CHARS:
            continue
        for old in asked:
            if len(old) >= MIN_FUZZY_CHARS and ratio(nq, old) >= QUESTION_THRESHOLD:
                problems.append(f"câu hỏi gần giống câu đã hỏi trước đó: '{q}'")
                break

        # Asking what they already told us: every content word of the question
        # already appears in one of their messages / known facts.
        # Recent messages need >=2 shared content words; older messages/facts
        # need >=3 so a coincidental word overlap does not block a fresh question.
        q_tokens = _content_tokens(q)
        recent_theirs = ctx.their_texts[-3:]
        older = ctx.their_texts[:-3] + ctx.known_texts
        known_hit = (
            len(q_tokens) >= 2 and any(q_tokens <= _content_tokens(t) for t in recent_theirs)
        ) or (
            len(q_tokens) >= 3 and any(q_tokens <= _content_tokens(t) for t in older)
        )
        if known_hit:
            problems.append(f"hỏi lại điều họ đã nói/đã biết: '{q}'")
    return problems


def find_style_problems(reply: AIReply, ctx: QualityContext) -> list[str]:
    """Rhythm rules: no interview streaks, no compliment spam, no same style over and over."""
    problems: list[str] = []
    recent_asked = ctx.last_asked[-ASKED_STREAK_LIMIT:]
    if (
        reply_asks(reply, ctx)
        and len(recent_asked) == ASKED_STREAK_LIMIT
        and all(recent_asked)
    ):
        problems.append(
            "2 lượt gần nhất đều đã hỏi; lượt này KHÔNG được hỏi, hãy chia sẻ/trêu nhẹ/flirt nhẹ/khen thay vì hỏi tiếp"
        )

    style = reply.reply_style
    if style == "compliment" and "compliment" in ctx.last_styles[-COMPLIMENT_COOLDOWN:]:
        problems.append("vừa khen ở các lượt gần đây, chưa khen lại; hãy phản hồi/trêu/chia sẻ thay vì khen")

    if style != "react" and len(ctx.last_styles) >= 2 and ctx.last_styles[-2:] == [style, style]:
        problems.append(f"đã dùng kiểu '{style}' 2 lượt liên tiếp, hãy đổi kiểu phản hồi khác")
    return problems


def find_dead_end_replies(reply: AIReply, ctx: QualityContext) -> list[str]:
    """Prevent conversation killers: short agreements with no question or hook."""
    if reply_asks(reply, ctx) or ctx.closure_now:
        return []
        
    problems: list[str] = []
    text = " ".join(reply.messages).strip()
    n = normalize(text)
    
    if len(n.split()) <= 7:
        tokens = _content_tokens(text)
        if len(tokens) <= 1:
            problems.append(
                f"câu trả lời quá cụt ngủn/đi vào ngõ cụt: '{text}'. "
                "Yêu cầu: vẫn có thể giữ câu cảm thán/phản hồi đó, NHƯNG phải thêm 1 câu khác (có thể tách thành 2 tin nhắn) để trêu đùa, thả thính ngầm hoặc hỏi nhẹ để đối phương có cớ trả lời tiếp."
            )
    return problems


def check_reply(reply: AIReply, ctx: QualityContext) -> list[str]:
    """Run every check; PASS == empty list."""
    if reply.action == "WAIT" or not reply.messages:
        return []
    problems: list[str] = []
    problems += find_duplicate_replies(reply.messages, ctx.my_sent)
    problems += find_recombined_replies(reply.messages, ctx.recent_sent)
    problems += find_repeated_fact_reactions(reply, ctx)
    problems += find_closed_topic_problems(reply, ctx)
    problems += find_violations(reply.messages, ctx.their_texts)            # persona/hard rules
    problems += find_repeated_questions(reply, ctx)
    problems += find_echo_replies(reply.messages, ctx.new_texts)
    problems += find_style_problems(reply, ctx)
    problems += find_dead_end_replies(reply, ctx)
    seen: set[str] = set()
    return [p for p in problems if not (p in seen or seen.add(p))]


# ------------------------------- guidance -------------------------------

def build_guidance(ctx: QualityContext) -> str:
    """Steering text for the prompt so the first draft already respects the rhythm."""
    lines: list[str] = []
    if ctx.last_styles:
        lines.append(f"KIỂU 6 LƯỢT TRẢ LỜI GẦN NHẤT CỦA TÔI (cũ -> mới): {', '.join(ctx.last_styles[-STYLE_HISTORY:])}")

    recent_asked = ctx.last_asked[-ASKED_STREAK_LIMIT:]
    if len(recent_asked) == ASKED_STREAK_LIMIT and all(recent_asked):
        lines.append(
            "LƯỢT NÀY KHÔNG HỎI: 2 lượt gần nhất tôi đều đã hỏi. Ưu tiên chia sẻ (FACT thật), trêu nhẹ, flirt nhẹ hoặc khen nhẹ nếu hợp ngữ cảnh."
        )
    elif ctx.last_asked[-3:] == [False, False, False] and ctx.their_active:
        lines.append(
            "Họ đang trò chuyện tích cực nhưng 3 lượt gần nhất tôi không hỏi gì: lượt này có thể chủ động mở rộng chủ đề hoặc hỏi 1 câu bám ngữ cảnh (không bắt buộc)."
        )

    if "compliment" in ctx.last_styles[-COMPLIMENT_COOLDOWN:]:
        lines.append("Vừa khen ở lượt gần đây: lượt này không khen.")
    if ctx.closure_now:
        latest = ctx.new_texts[-1] if ctx.new_texts else ctx.closure_now
        closed_text = next((e.get("text", "") for e in reversed(ctx.closed_topics) if e.get("text")), "")
        lines.append(
            f"CHỦ ĐỀ ĐÃ ĐÓNG: tin mới nhất của họ là \"{latest}\" (phủ nhận/không muốn tiếp tục)"
            + (f", chủ đề vừa bị đóng: \"{closed_text}\"" if closed_text else "")
            + ". KHÔNG hỏi lại, KHÔNG giải thích lại, KHÔNG phản ứng lại chủ đề đó. "
            "Chỉ phản hồi nhẹ, trêu tự nhiên hoặc mở một chủ đề mới nếu phù hợp (không bắt buộc phải hỏi)."
        )
    else:
        earlier = [e.get("text", "") for e in ctx.closed_topics if e.get("text")][-2:]
        if earlier:
            lines.append(
                "CHỦ ĐỀ HỌ ĐÃ ĐÓNG TRƯỚC ĐÓ (không nhắc lại trừ khi chính họ nhắc): " + " || ".join(earlier)
            )
    if ctx.new_texts:
        lines.append(
            f"KIỂM TRA TRƯỚC KHI TRẢ LỜI: chỉ phản hồi tin mới nhất của họ (\"{ctx.new_texts[-1]}\"), không vô tình trả lời lại tin cũ. "
            "Họ vừa nhắn tin mới nên KHÔNG được trả WAIT; nếu không hỏi được thì phản hồi/trêu/chia sẻ ngắn."
        )
    if ctx.recent_sent:
        sent = " | ".join(ctx.recent_sent[-RECENT_SENT_WINDOW:])
        lines.append(
            f"CÁC TIN TÔI VỪA GỬI (tuyệt đối không ghép lại, không nhắc lại ý, không phản ứng lần nữa với cùng thông tin của họ): {sent}"
        )
        
    # Điều phối số lượng tin nhắn (1 hoặc 2) để nhịp điệu tự nhiên hơn
    last_me_count = 0
    found_me = False
    for who, text in reversed(ctx.dialogue):
        if who == "me":
            last_me_count += 1
            found_me = True
        elif found_me:
            break
            
    if last_me_count >= 2:
        lines.append("SỐ LƯỢNG TIN NHẮN: Lượt trước đã tách thành nhiều tin rồi, lượt này NÊN GỘP ý thành 1 tin nhắn duy nhất.")
    elif last_me_count == 1:
        lines.append("SỐ LƯỢNG TIN NHẮN: Lượt trước gửi 1 tin rồi, lượt này CÓ THỂ tách thành 2 tin nhắn (nếu có nhiều ý) để giống người thật đang gõ phím.")
        
    return "\n".join(lines)
