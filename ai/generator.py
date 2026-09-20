"""Response generator integrating prompt construction, LLM execution, and safety validation."""
from typing import Any
from ai.client import LLMClient
from ai.prompts import build_chat_prompt
from ai.classifier import IntentClassifier, IntentCategory
from ai.safety import SafetyValidator
from ai.style_analyzer import StyleAnalyzer
from conversations.queue import ConversationState
from utils.logger import logger


class ResponseGenerator:
    """Generates context-aware, safe, and style-aligned Tinder chat replies."""

    def __init__(self, llm_client: LLMClient | None = None):
        self.llm_client = llm_client or LLMClient()

    async def generate_response(
        self,
        state: ConversationState,
        bundled_messages: list[str]
    ) -> tuple[str, bool, str]:
        """
        Generate AI reply for the accumulated incoming messages.
        Returns:
            (reply_text: str, is_safe_for_auto: bool, intent_name: str)
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
            new_message=combined_new_message
        )

        # 4. Invoke LLM
        raw_reply = await self.llm_client.chat(messages)

        # 5. Clean reply (remove outer quotes if model added them)
        clean_reply = raw_reply.strip().strip('"').strip("'")

        # 6. Safety validation
        is_safe_content, safety_reason = SafetyValidator.validate_reply(clean_reply)
        if not is_safe_content:
            logger.warning(f"Safety check rejected auto-send: {safety_reason}")

        # Combined auto-send eligibility
        eligible_for_auto = is_safe_intent and is_safe_content

        return clean_reply, eligible_for_auto, intent.value
