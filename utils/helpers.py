"""Utility helpers for hashing, sensitive data scrubbing, and time handling."""
import hashlib
import re
from datetime import datetime, timezone


def compute_message_hash(
    conversation_id: str,
    sender: str,
    content: str,
    timestamp: str | None = None
) -> str:
    """
    Calculate deterministic SHA256 fingerprint for a message.
    Ensures duplicate messages are detected and processed only once.
    """
    clean_sender = (sender or "").strip().lower()
    clean_content = (content or "").strip()
    raw = f"{conversation_id}:{clean_sender}:{clean_content}"
    if timestamp:
        raw += f":{timestamp.strip()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def redact_sensitive_text(text: str) -> str:
    """Scrub potential credentials or sensitive tokens from user strings."""
    if not text:
        return ""
    # Redact common sensitive formats
    redacted = re.sub(r"(?i)\b(otp|mã xác thực|pass|mật khẩu)\s*[:=]?\s*\w+", "[SENSITIVE_REDACTED]", text)
    redacted = re.sub(r"\b\d{4,8}\b", "[POTENTIAL_CODE]", redacted)  # numbers that look like OTPs
    return redacted


def utc_now() -> datetime:
    """Return current UTC datetime."""
    return datetime.now(timezone.utc)


def format_iso(dt: datetime | None) -> str:
    """Format datetime to ISO string."""
    if not dt:
        return ""
    return dt.isoformat()
