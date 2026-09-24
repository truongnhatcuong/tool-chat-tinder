"""Response generator.

Flow per reply:
    memory/history/facts
      -> LLM generates structured JSON
      -> Pydantic validates it            (ai.schemas)
      -> RapidFuzz duplicate check        (ai.quality)
      -> conversation quality check       (ai.quality + ai.output_guard)
      -> PASS: return messages
      -> FAIL: regenerate with the failure reasons (up to `ai.max_regenerations`),
               then stay silent (WAIT) rather than send a bad reply.
"""
from typing import Any

from ai.classifier import IntentCategory, IntentClassifier
from ai.client import LLMClient
from ai.fallback_replies import build_rescue_feedback, fallback_candidates, pick_fallback
from ai.memory import ConversationContext
from ai.output_guard import build_retry_feedback
from ai.prompts import build_chat_prompt
from ai.quality import (
    QualityContext,
    build_closed_topic,
    build_guidance,
    check_reply,
    reply_asks,
    reply_question_texts,
)
from ai.question_detector import is_question
from ai.safety import SafetyValidator
from ai.schemas import AIReply, parse_ai_reply
from ai.style_analyzer import StyleAnalyzer
from ai.topic_closure import detect_closure
from config.settings import get_settings
from conversations.queue import ConversationState
from utils.logger import logger


_WAIT_PROBLEM = (
    "model trả WAIT nhưng họ vừa nhắn tin mới và đang chờ; phải trả lời bằng một câu ngắn tự nhiên "
    "(phản hồi/trêu/chia sẻ hoặc hỏi 1 câu mới), không được WAIT"
)


def _evaluate(reply: AIReply | None, parse_error: str | None, ctx: QualityContext, allow_wait: bool) -> list[str]:
    """Failure reasons for one model draft ([] == PASS)."""
    if parse_error:
        return [parse_error]
    if reply.action == "WAIT":
        return [] if allow_wait else [_WAIT_PROBLEM]
    return check_reply(reply, ctx)


def _dedupe_keep_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def build_quality_context(
    state: ConversationState,
    bundled_messages: list[str],
    memory: "ConversationContext | None",
) -> QualityContext:
    """Collect who-said-what and what we already asked, strictly per conversation."""
    if memory is not None:
        their = [m["content"] for m in memory.recent if m.get("who") == "họ"]
        mine = [m["content"] for m in memory.recent if m.get("who") == "tôi"]
    else:
        their, mine = [], []
    # state.history is the in-memory mirror; merge so nothing is missed.
    their = _dedupe_keep_order(their + [m["content"] for m in state.history if m.get("role") == "incoming"])
    mine = _dedupe_keep_order(mine + [m["content"] for m in state.history if m.get("role") == "outgoing"])
    their = their + list(bundled_messages)   # newest last

    facts = memory.facts if memory is not None else []
    known = [f.split("]", 1)[1].strip() for f in facts if f.startswith("[họ]") and "]" in f]

    asked_questions = _dedupe_keep_order(
        (memory.questions_asked if memory is not None else []) + (memory.asked_by_me if memory is not None else [])
    )
    last_styles = list(memory.last_reply_styles) if memory is not None else []
    last_asked = list(memory.last_reply_asked) if memory is not None else []
    if not last_asked:
        # Conversations from before styles were persisted: derive from real sent messages.
        last_asked = [is_question(t) for t in mine[-3:]]

    # chronological dialogue (them/me) so we can tell which of their facts we already reacted to
    if memory is not None and memory.recent:
        dialogue = [("me" if m.get("who") == "tôi" else "them", m["content"]) for m in memory.recent]
    else:
        dialogue = [("me" if m.get("role") == "outgoing" else "them", m["content"]) for m in state.history]
    recent_sent = [t for who, t in dialogue if who == "me"][-3:]

    # Did their NEWEST message close/deny the topic we just raised?
    counter = memory.reply_counter if memory is not None else 0
    closure = detect_closure(list(bundled_messages))
    closed_now = build_closed_topic(closure, dialogue, list(bundled_messages), counter)
    persisted = list(memory.closed_topics) if memory is not None else []
    closed_topics = persisted + ([closed_now] if closed_now else [])

    latest = bundled_messages[-1] if bundled_messages else ""
    return QualityContext(
        their_texts=their,
        known_texts=known,
        my_sent=mine + asked_questions,
        asked_questions=asked_questions,
        asked_keys=list(memory.asked_intents) if memory is not None else [],
        last_styles=last_styles,
        last_asked=last_asked,
        their_active=len(latest.split()) >= 4,
        recent_sent=recent_sent,
        new_texts=list(bundled_messages),
        dialogue=dialogue,
        closed_topics=closed_topics,
        closure_now=closure.phrase if closure else "",
        closed_now=closed_now,
    )
    return ctx


def _build_meta(
    reply: AIReply | None,
    regenerations: int,
    ctx: QualityContext | None = None,
    fallback: str = "",
    gave_up: bool = False,
) -> dict[str, Any]:
    if reply is None:
        return {
            "intent": "", "topic": "", "pattern_used": "", "reply_style": "react",
            "asks_question": False, "question_key": "", "question_texts": [],
            "regenerations": regenerations, "closed_topic": ctx.closed_now if ctx else None,
            "fallback": fallback, "gave_up": gave_up,
        }
    ctx = ctx or QualityContext()
    asks = reply_asks(reply, ctx)
    return {
        "fallback": fallback,
        "gave_up": gave_up,
        "intent": reply.intent,
        "topic": reply.topic,
        "pattern_used": reply.pattern_used,
        "reply_style": "question" if asks and reply.reply_style in ("react", "share") else reply.reply_style,
        "asks_question": asks,
        "question_key": reply.question_key,
        "question_texts": reply_question_texts(reply, ctx),
        "regenerations": regenerations,
        "closed_topic": ctx.closed_now,
    }


class ResponseGenerator:
    """Generates context-aware, safe, and style-aligned Tinder chat replies."""

    def __init__(self, llm_client: LLMClient | None = None):
        self.llm_client = llm_client or LLMClient()

    async def _rescue(
        self,
        messages: list[dict[str, str]],
        last_raw: str,
        problems: list[str],
        ctx: QualityContext,
        conversation_id: str,
    ) -> tuple[AIReply | None, str]:
        """One last model call demanding a completely different reply, then the fallback bank."""
        try:
            instruction = build_rescue_feedback(problems, ctx.recent_sent, fallback_candidates(ctx))
            raw = await self.llm_client.chat(
                messages + [
                    {"role": "assistant", "content": last_raw},
                    {"role": "user", "content": instruction},
                ]
            )
            reply, error = parse_ai_reply(raw)
            if error:
                rescue_problems = [error]
            elif reply.action == "WAIT":
                rescue_problems = ["model trả WAIT dù họ đang chờ trả lời"]
            else:
                rescue_problems = check_reply(reply, ctx)
            if not rescue_problems:
                return reply, "rescue"
            logger.warning(f"Rescue draft rejected for {conversation_id}: {rescue_problems}")
        except Exception as e:
            logger.warning(f"Rescue call failed for {conversation_id}: {e}")

        picked = pick_fallback(ctx)
        return (picked, "bank") if picked is not None else (None, "")

    async def generate_response(
        self,
        state: ConversationState,
        bundled_messages: list[str],
        memory: "ConversationContext | None" = None,
    ) -> tuple[list[str], bool, str, dict[str, Any]]:
        """
        Generate AI reply for the accumulated incoming messages.
        Returns:
            (messages: list[str], is_safe_for_auto: bool, incoming_intent_name: str, meta: dict)
        `meta` also carries reply_style / asks_question / question_key / question_texts
        so the caller can persist them once the reply is actually sent.
        """
        combined_new_message = " \n ".join(bundled_messages).strip()

        # 1. Classify intent
        intent = IntentClassifier.classify(combined_new_message)
        logger.info(f"Classified message intent: {intent.value} for {state.conversation_id}")
        is_safe_intent = IntentClassifier.is_safe_for_auto_reply(combined_new_message)

        # 2. Extract style
        style_meta = StyleAnalyzer.analyze(state.history)
        style_str = f"{style_meta['formality']}, {style_meta['message_length']} messages, slang={style_meta['slang']}"

        # 3. Quality context + rhythm guidance, then the OpenAI-format prompt
        ctx = build_quality_context(state, bundled_messages, memory)
        # WAIT is only legitimate when they are saying goodnight / busy: otherwise they are
        # waiting for an answer and staying silent would leave them hanging.
        is_closing, _closing_type = IntentClassifier.is_conversation_closing(combined_new_message)
        allow_wait = is_closing or intent in (IntentCategory.GOODNIGHT, IntentCategory.BUSY_LATER)
        guidance = build_guidance(ctx)
        if memory is not None:
            memory.guidance = guidance
        messages = build_chat_prompt(
            name=state.match_name,
            age=state.profile.get("age"),
            bio=state.profile.get("bio"),
            interests=state.profile.get("interests"),
            summary=state.summary,
            style=style_str,
            recent_history=state.history[-5:],
            new_message=combined_new_message,
            memory_block=memory.render() if memory else None,
            guidance=guidance,
        )

        # 4. Generate -> validate -> check -> regenerate with the failure reasons
        max_regen = max(0, int(get_settings().ai.max_regenerations))
        attempt_messages = messages
        reply: AIReply | None = None
        all_problems: list[str] = []
        raw_reply = ""
        passed = False
        attempt = 0
        for attempt in range(max_regen + 1):
            raw_reply = await self.llm_client.chat(attempt_messages)
            reply, parse_error = parse_ai_reply(raw_reply)           # Pydantic
            problems = _evaluate(reply, parse_error, ctx, allow_wait)             # RapidFuzz + quality
            if not problems:
                passed = True
                break

            logger.warning(
                f"Reply for {state.conversation_id} failed quality check "
                f"(attempt {attempt + 1}/{max_regen + 1}): {problems}"
            )
            all_problems += problems
            attempt_messages = messages + [
                {"role": "assistant", "content": raw_reply},
                {"role": "user", "content": build_retry_feedback(problems, json_reply=True)},
            ]

        fallback = ""
        if not passed:
            # Staying silent leaves them hanging: escalate (rescue prompt, then a bank of
            # neutral lines that still pass every check) before giving up.
            reply, fallback = await self._rescue(messages, raw_reply, all_problems, ctx, state.conversation_id)
            if reply is None:
                logger.warning(f"No acceptable reply for {state.conversation_id}; will retry later.")
                return [], False, intent.value, _build_meta(None, attempt, ctx, gave_up=True)
            logger.info(f"Reply for {state.conversation_id} produced by '{fallback}' fallback: {reply.messages}")

        meta = _build_meta(reply, attempt, ctx, fallback=fallback)
        out_messages = reply.messages
        if reply.action == "WAIT" or not out_messages:
            logger.info("Model returned WAIT or empty messages; not sending anything.")
            return [], False, intent.value, meta

        # 5. Safety validation for all messages
        all_safe = True
        for msg in out_messages:
            is_safe_content, safety_reason = SafetyValidator.validate_reply(msg)
            if not is_safe_content:
                logger.warning(f"Safety check rejected auto-send for message '{msg}': {safety_reason}")
                all_safe = False

        # Combined auto-send eligibility
        eligible_for_auto = is_safe_intent and all_safe

        return out_messages, eligible_for_auto, intent.value, meta
