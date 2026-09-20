"""Tests validating the intent classifier, safety validator, and prompt builder."""
import pytest
from ai.classifier import IntentClassifier, IntentCategory
from ai.safety import SafetyValidator
from ai.prompts import build_chat_prompt
from utils.helpers import compute_message_hash, redact_sensitive_text


def test_intent_classifier_security_flags():
    # Sensitive messages must be flagged as unsafe for auto reply
    assert IntentClassifier.classify("gửi anh mã OTP đi em") == IntentCategory.OTP
    assert IntentClassifier.is_safe_for_auto_reply("gửi anh mã OTP đi em") is False

    assert IntentClassifier.classify("cho em pass tài khoản") == IntentCategory.PASSWORD
    assert IntentClassifier.is_safe_for_auto_reply("cho em pass tài khoản") is False

    assert IntentClassifier.classify("anh bắn tiền qua stk này nhé") == IntentCategory.MONEY
    assert IntentClassifier.is_safe_for_auto_reply("anh bắn tiền qua stk này nhé") is False

    assert IntentClassifier.classify("cho em số CCCD để check") == IntentCategory.PRIVATE_INFO
    assert IntentClassifier.is_safe_for_auto_reply("cho em số CCCD để check") is False

    assert IntentClassifier.classify("mai mấy giờ anh qua đón em") == IntentCategory.DATE_DISCUSSION
    assert IntentClassifier.is_safe_for_auto_reply("mai mấy giờ anh qua đón em") is False

    # Safe casual messages
    assert IntentClassifier.is_safe_for_auto_reply("chào anh, dạo này sao rồi") is True
    assert IntentClassifier.is_safe_for_auto_reply("thấy anh mê code ghê :))") is True


def test_goodnight_intent_classification():
    """Verify detection of bedtime, goodnight, and wrap-up messages."""
    # Vietnamese goodnight / bedtime phrases
    assert IntentClassifier.classify("em đi ngủ đây, anh ngủ ngon nhé") == IntentCategory.GOODNIGHT
    assert IntentClassifier.classify("chúc anh ngủ ngon nha <3") == IntentCategory.GOODNIGHT
    assert IntentClassifier.classify("ngủ ngon nhé anh") == IntentCategory.GOODNIGHT
    assert IntentClassifier.classify("ngủ ngoan nha") == IntentCategory.GOODNIGHT
    assert IntentClassifier.classify("thôi muộn rồi đi ngủ thôi") == IntentCategory.GOODNIGHT
    assert IntentClassifier.classify("buồn ngủ quá rồi mai nc tiếp nha") == IntentCategory.GOODNIGHT
    assert IntentClassifier.classify("mai nói chuyện tiếp nhé") == IntentCategory.GOODNIGHT
    assert IntentClassifier.classify("tạm biệt anh nhé") == IntentCategory.GOODNIGHT
    assert IntentClassifier.classify("bye anh nha") == IntentCategory.GOODNIGHT

    # English / Slang
    assert IntentClassifier.classify("g9 anh") == IntentCategory.GOODNIGHT
    assert IntentClassifier.classify("good night nè") == IntentCategory.GOODNIGHT

    # Helper method
    assert IntentClassifier.is_goodnight("em đi ngủ đây") is True
    assert IntentClassifier.is_goodnight("chúc ngủ ngon mơ đẹp") is True

    # Negative cases (should NOT be classified as GOODNIGHT)
    assert IntentClassifier.classify("anh ngủ chưa?") != IntentCategory.GOODNIGHT
    assert IntentClassifier.is_goodnight("anh ngủ chưa?") is False
    assert IntentClassifier.is_goodnight("sao giờ này chưa ngủ?") is False

    # Goodnight must be safe for auto reply (so AI can send a sweet sign-off message)
    assert IntentClassifier.is_safe_for_auto_reply("em đi ngủ đây anh ngủ ngon nhé") is True


def test_busy_later_intent_classification():
    """Verify detection of busy, leaving, or texting back later messages."""
    assert IntentClassifier.classify("tí em nhắn lại sau nhé") == IntentCategory.BUSY_LATER
    assert IntentClassifier.classify("xíu em nhắn sau nha") == IntentCategory.BUSY_LATER
    assert IntentClassifier.classify("lát em nhắn sau nhé") == IntentCategory.BUSY_LATER
    assert IntentClassifier.classify("em đang bận tí") == IntentCategory.BUSY_LATER
    assert IntentClassifier.classify("em bận rồi, tí nc sau nha") == IntentCategory.BUSY_LATER
    assert IntentClassifier.classify("em đi làm đây, rảnh nhắn sau nhé") == IntentCategory.BUSY_LATER
    assert IntentClassifier.classify("chuẩn bị vào ca rồi") == IntentCategory.BUSY_LATER
    assert IntentClassifier.classify("hôm khác nói chuyện tiếp nhé") == IntentCategory.BUSY_LATER
    assert IntentClassifier.classify("thôi em out đây") == IntentCategory.BUSY_LATER

    # Helper method
    assert IntentClassifier.is_busy_or_closing("lát nữa em rep sau nha") is True
    assert IntentClassifier.is_busy_or_closing("đang bận việc quá") is True

    # is_conversation_closing
    closing1, type1 = IntentClassifier.is_conversation_closing("ngủ ngon nha anh")
    assert closing1 is True and type1 == "GOODNIGHT"

    closing2, type2 = IntentClassifier.is_conversation_closing("tí nhắn sau nhé")
    assert closing2 is True and type2 == "BUSY_LATER"

    # Negative cases (questions or negations)
    assert IntentClassifier.is_busy_or_closing("anh có bận không?") is False
    assert IntentClassifier.is_busy_or_closing("sao bận thế?") is False
    assert IntentClassifier.is_busy_or_closing("em không bận đâu") is False

    # Safe for auto reply
    assert IntentClassifier.is_safe_for_auto_reply("em bận tí lát nhắn lại sau nha") is True


def test_safety_validator_rejects_unsafe_replies():
    # Attempting to send sensitive info must fail validation
    safe, _ = SafetyValidator.validate_reply("chào em, dạo này em hay đi quán cafe nào?")
    assert safe is True

    unsafe_otp, reason1 = SafetyValidator.validate_reply("Mã OTP của anh là 123456")
    assert unsafe_otp is False
    assert "safety filter" in reason1

    unsafe_stk, reason2 = SafetyValidator.validate_reply("Chuyển khoản qua stk 19034567888 nhé")
    assert unsafe_stk is False

    unsafe_commitment, reason3 = SafetyValidator.validate_reply("mai 7h qua đón em đi chơi nhé")
    assert unsafe_commitment is False


def test_prompt_builder_structure():
    messages = build_chat_prompt(
        name="Lan",
        age=24,
        bio="Thích cafe",
        interests=["Coffee", "Travel"],
        summary="Talking about coffee shops",
        style="casual",
        recent_history=[
            {"role": "incoming", "sender": "Lan", "content": "ê anh"},
            {"role": "outgoing", "sender": "You", "content": "anh đây :))"}
        ],
        new_message="chiều rảnh không"
    )

    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"
    assert "Lan" in messages[1]["content"]
    assert "chiều rảnh không" in messages[1]["content"]


def test_sensitive_text_redaction():
    text = "mật khẩu là 123456 và pass là secret99"
    redacted = redact_sensitive_text(text)
    assert "[SENSITIVE_REDACTED]" in redacted
    assert "123456" not in redacted
