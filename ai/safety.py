"""Safety validation engine preventing dangerous, sensitive, or hallucinated auto-replies."""
import re
from utils.logger import logger


class SafetyViolation(Exception):
    """Raised when generated response violates security or privacy constraints."""
    pass


class SafetyValidator:
    """Validates AI generated replies before allowing automatic transmission."""

    SENSITIVE_OUTPUT_PATTERNS = [
        re.compile(r"(?i)\b(mật khẩu|password|pass|token|secret)\b"),
        re.compile(r"(?i)\b(otp|mã xác thực|mã otp)\b"),
        re.compile(r"(?i)\b(stk|số tài khoản|chuyển khoản|bank account|\d{9,16})\b"),
        re.compile(r"(?i)\b(cccd|cmnd|căn cước công dân)\b"),
        re.compile(r"(?i)\b(mai \d+h qua đón|hôm nay \d+h qua đón|anh qua đón em nhé)\b"),  # unconfirmed pickup commitment
    ]

    @classmethod
    def validate_reply(cls, reply_text: str) -> tuple[bool, str]:
        """
        Validate generated text.
        Returns (is_safe: bool, reason: str).
        """
        clean_text = reply_text.strip()
        if not clean_text:
            return False, "Empty reply generated."

        # Check for forbidden sensitive patterns
        for pattern in cls.SENSITIVE_OUTPUT_PATTERNS:
            match = pattern.search(clean_text)
            if match:
                reason = f"Response triggered safety filter on pattern: '{match.group(0)}'"
                logger.warning(reason)
                return False, reason

        # Check for overly long or spammy response
        if len(clean_text) > 350:
            return False, "Response length exceeded 350 characters (too verbose for chat)."

        return True, "Safe"
