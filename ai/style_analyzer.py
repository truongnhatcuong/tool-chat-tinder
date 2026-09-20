"""Style analyzer to mirror conversational tone and pacing."""
import re
from typing import Any


class StyleAnalyzer:
    """Extracts style attributes from recent conversation messages."""

    @staticmethod
    def analyze(history: list[dict[str, str]]) -> dict[str, Any]:
        if not history:
            return {
                "message_length": "short",
                "formality": "casual",
                "emoji_usage": "medium",
                "slang": True,
                "reply_style": "direct"
            }

        total_length = 0
        incoming_count = 0
        has_emoji = False
        emoji_pattern = re.compile(r"[\U00010000-\U0010ffff]|:\)\)|:D|<3")

        for msg in history:
            if msg.get("role") == "incoming":
                content = msg.get("content", "")
                total_length += len(content)
                incoming_count += 1
                if emoji_pattern.search(content):
                    has_emoji = True

        avg_len = total_length / max(incoming_count, 1)

        return {
            "message_length": "short" if avg_len < 40 else ("medium" if avg_len < 100 else "long"),
            "formality": "casual",
            "emoji_usage": "medium" if has_emoji else "low",
            "slang": True,
            "reply_style": "direct"
        }
