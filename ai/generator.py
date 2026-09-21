"""Response generator integrating prompt construction, LLM execution, and safety validation."""
from typing import Any
from ai.client import LLMClient
from ai.prompts import build_chat_prompt
from ai.classifier import IntentClassifier, IntentCategory
from ai.safety import SafetyValidator
from ai.style_analyzer import StyleAnalyzer
from ai.memory import ConversationContext
from conversations.queue import ConversationState
from utils.logger import logger
import difflib
import json
import re

def _parse_llm_json(text: str) -> dict:
    try:
        # Try finding json block
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        return json.loads(text)
    except Exception:
        return {}


_PUNCT_RE = re.compile(r"[^\wÀ-ỹ\s]", re.UNICODE)


def _normalize_for_compare(text: str) -> str:
    """Lowercase, strip punctuation/emoji, collapse whitespace for fuzzy comparison."""
    text = (text or "").strip().lower()
    text = _PUNCT_RE.sub("", text)
    return re.sub(r"\s+", " ", text).strip()


def _is_near_duplicate(candidate: str, past_texts: list[str], threshold: float = 0.85) -> bool:
    """Check whether `candidate` closely matches (or repeats) something already sent."""
    norm_candidate = _normalize_for_compare(candidate)
    if not norm_candidate:
        return False
    for past in past_texts:
        norm_past = _normalize_for_compare(past)
        if not norm_past:
            continue
        if norm_candidate == norm_past:
            return True
        ratio = difflib.SequenceMatcher(None, norm_candidate, norm_past).ratio()
        if ratio >= threshold:
            return True
    return False


class ResponseGenerator:
    """Generates context-aware, safe, and style-aligned Tinder chat replies."""

    def __init__(self, llm_client: LLMClient | None = None):
        self.llm_client = llm_client or LLMClient()

    async def generate_response(
        self,
        state: ConversationState,
        bundled_messages: list[str],
        memory: "ConversationContext | None" = None,
    ) -> tuple[list[str], bool, str, dict[str, str]]:
        """
        Generate AI reply for the accumulated incoming messages.
        Returns:
            (messages: list[str], is_safe_for_auto: bool, incoming_intent_name: str, meta: dict)
        """
        combined_new_message = " \n ".join(bundled_messages).strip()

        # 1. Classify intent
        intent = IntentClassifier.classify(combined_new_message)
        logger.info(f"Classified message intent: {intent.value} for {state.conversation_id}")
        is_safe_intent = IntentClassifier.is_safe_for_auto_reply(combined_new_message)

        # 2. Extract style
        style_meta = StyleAnalyzer.analyze(state.history)
        style_str = f"{style_meta['formality']}, {style_meta['message_length']} messages, slang={style_meta['slang']}"

        # 3. Build OpenAI-format prompt
        messages = build_chat_prompt(
            name=state.match_name,
            age=state.profile.get("age"),
            bio=state.profile.get("bio"),
            interests=state.profile.get("interests"),
            summary=state.summary,
            style=style_str,
            recent_history=state.history[-15:],
            new_message=combined_new_message,
            memory_block=memory.render() if memory else None,
        )

        # 4. Invoke LLM
        raw_reply = await self.llm_client.chat(messages)

        # 5. Parse JSON
        parsed = _parse_llm_json(raw_reply)
        action = parsed.get("action", "REPLY").upper()
        out_messages = parsed.get("messages", [])
        if isinstance(out_messages, str):
            out_messages = [out_messages]
            
        meta = {
            "intent": parsed.get("intent", ""),
            "topic": parsed.get("topic", ""),
            "pattern_used": parsed.get("pattern_used", "")
        }

        if action == "WAIT" or not out_messages:
            logger.info("Model returned WAIT or empty messages; not sending anything.")
            return [], False, intent.value, meta

        # 6. Hard repetition guard: never resend something we already told this
        # match, even if the model ignores the "already asked" instruction in
        # the prompt (that instruction is only a soft hint, not an enforced
        # rule). This directly prevents cases like asking the exact same
        # question twice in the same conversation.
        past_outgoing_texts = [
            m["content"] for m in state.history if m.get("role") == "outgoing"
        ]
        if memory is not None:
            past_outgoing_texts.extend(memory.asked_by_me)

        deduped_messages = []
        for msg in out_messages:
            if _is_near_duplicate(msg, past_outgoing_texts):
                logger.warning(
                    f"Blocked near-duplicate outgoing message for {state.conversation_id} "
                    f"(already sent something very similar before): '{msg}'"
                )
                continue
            deduped_messages.append(msg)
            past_outgoing_texts.append(msg)  # avoid duplicates within the same batch too
        out_messages = deduped_messages

        if not out_messages:
            logger.info(
                f"All generated messages for {state.conversation_id} were duplicates of "
                f"prior messages; treating as WAIT instead of resending."
            )
            return [], False, intent.value, meta

        # 7. Safety validation for all messages
        all_safe = True
        for msg in out_messages:
            is_safe_content, safety_reason = SafetyValidator.validate_reply(msg)
            if not is_safe_content:
                logger.warning(f"Safety check rejected auto-send for message '{msg}': {safety_reason}")
                all_safe = False

        # Combined auto-send eligibility
        eligible_for_auto = is_safe_intent and all_safe

        return out_messages, eligible_for_auto, intent.value, meta
