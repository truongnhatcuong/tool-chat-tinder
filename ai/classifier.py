"""Message intent classifier identifying sensitive topics requiring manual approval."""
import re
from enum import Enum


class IntentCategory(str, Enum):
    NORMAL = "NORMAL"
    CASUAL = "CASUAL"
    QUESTION = "QUESTION"
    FLIRT = "FLIRT"
    GOODNIGHT = "GOODNIGHT"
    BUSY_LATER = "BUSY_LATER"
    SCHEDULE = "SCHEDULE"
    DATE_DISCUSSION = "DATE_DISCUSSION"
    MONEY = "MONEY"
    OTP = "OTP"
    PASSWORD = "PASSWORD"
    ACCOUNT = "ACCOUNT"
    PRIVATE_INFO = "PRIVATE_INFO"
    ARGUMENT = "ARGUMENT"
    IMPORTANT = "IMPORTANT"
    UNKNOWN = "UNKNOWN"


# Intents that MUST NEVER be auto-sent
UNSAFE_FOR_AUTO_REPLY = {
    IntentCategory.MONEY,
    IntentCategory.OTP,
    IntentCategory.PASSWORD,
    IntentCategory.ACCOUNT,
    IntentCategory.PRIVATE_INFO,
    IntentCategory.IMPORTANT,
    IntentCategory.SCHEDULE,
    IntentCategory.DATE_DISCUSSION
}

# Regex pattern for goodnight and conversation wrap-up messages
GOODNIGHT_CLOSING_PATTERN = re.compile(
    r"(?i)\b("
    r"chúc\s*(([a-zA-Z\s]+)\s*)?(ngủ\s*)?(ngon|ngoan)"
    r"|ngủ\s*(ngon|ngoan)(\s*(nha|nhé|nhe|nè|ạ|nho|nhen|nhá|đi))?"
    r"|(em|anh|tớ|mình|bé)\s*(chuẩn\s*bị\s*)?đi\s*ngủ\s*(đây|thôi|nha|nhé|nhe|nè|ạ|nhá|rồi)?"
    r"|đi\s*ngủ\s*(đây|thôi|nha|nhé|nhe|sớm|nhá|rồi)"
    r"|ngủ\s*sớm\s*(đi|nha|nhé|nhe|nè|ạ|nhá)"
    r"|(em|anh|tớ)\s*buồn\s*ngủ\s*(rồi|quá|ghê|lắm)"
    r"|good\s*night|g9\b|gnight\b"
    r"|mơ\s*đẹp\s*(nha|nhé|nhe|nè|ạ|nhá)?"
    r"|mai\s*(nói\s*chuyện|nhắn\s*tin|nhắn|nc|nch)\s*(tiếp|sau|nha|nhé|nhe|nhá)"
    r"|tạm\s*biệt\s*(anh|em|bạn|nha|nhé|nhe)?"
    r"|bye\s*(anh|em|bạn|nha|nhé|bye)?"
    r")\b"
)

# Regex pattern for busy / texting back later / leaving
BUSY_LATER_PATTERN = re.compile(
    r"(?i)\b("
    r"(tí|ti|xíu|xiu|lát|lat|tẹo|teo)\s*(nữa\s*)?(em|anh|tớ|mình|bạn)?\s*(nhắn|nt|rep|reply|nói\s*chuyện|nc|nch)\s*(lại\s*)?(sau|nhé|nha|nhe|ạ|nhá)"
    r"|(em|anh|tớ|mình|bạn)\s*(nhắn|nt|rep|reply|nói\s*chuyện|nc|nch)\s*(lại\s*)?(sau|sau\s*nhé|sau\s*nha|sau\s*nhe|sau\s*ạ|sau\s*nhá)"
    r"|(em|anh|tớ|mình)\s*(đang|hơi|có\s*chút|có\s*việc)?\s*bận\s*(rồi|quá|tí|xíu|chút|việc|đây|nha|nhé|ạ|lắm)"
    r"|đang\s*bận\s*(việc|tí|xíu|quá|lắm|rồi|nha|nhé|ạ)"
    r"|có\s*việc\s*(bận|gấp|phải\s*đi|ra\s*ngoài)"
    r"|((em|anh|tớ|mình|bạn)\s*)?(chuẩn\s*bị\s*)?(đi\s*làm|vào\s*làm|vào\s*ca|đi\s*học|phải\s*đi)\s*(đây|rồi|đã|nha|nhé|ạ|nhá)"
    r"|(rảnh|lúc\s*khác|hôm\s*khác|bữa\s*khác)\s*(nói\s*chuyện|nhắn|nc|nch|inbox)\s*(tiếp|sau|nha|nhé|nhe|nhá)"
    r"|ra\s*ngoài\s*(tí|xíu|chút|đã)\s*(nha|nhé|nhe|ạ)"
    r"|offline\s*đây|out\s*đây"
    r")\b"
)


class IntentClassifier:
    """Classifies incoming message intent using fast regex heuristics and keyword analysis."""

    @classmethod
    def is_goodnight(cls, text: str) -> bool:
        """Check if message indicates bedtime, goodnight, or wrapping up conversation."""
        t = text.lower().strip()
        # Exclude questions like "ngủ chưa", "sao chưa ngủ"
        if re.search(r"(?i)\b(chưa\s*ngủ|ngủ\s*(chưa|k|không|ch|hả|sao)|đang\s*ngủ)\b", t):
            return False
        return bool(GOODNIGHT_CLOSING_PATTERN.search(t))

    @classmethod
    def is_busy_or_closing(cls, text: str) -> bool:
        """Check if message indicates being busy, having to leave, or texting back later."""
        t = text.lower().strip()
        # Exclude questions like "có bận không?", "sao bận thế?" or negation "không bận"
        if re.search(r"(?i)\b(bận\s*(không|k|ko|hả|à|chăng|sao)|có\s*bận\s*(không|k|ko|hả|à)|sao\s*bận|không\s*bận|k\s*bận)\b", t):
            return False
        return bool(BUSY_LATER_PATTERN.search(t))

    @classmethod
    def is_conversation_closing(cls, text: str) -> tuple[bool, str]:
        """Check if message wraps up or pauses the conversation. Returns (is_closing, category)."""
        if cls.is_goodnight(text):
            return True, "GOODNIGHT"
        if cls.is_busy_or_closing(text):
            return True, "BUSY_LATER"
        return False, ""

    @classmethod
    def classify(cls, message_text: str) -> IntentCategory:
        text = message_text.lower().strip()

        # 1. Critical security / financial / credential checks
        if re.search(r"(?i)\b(otp|mã xác nhận|mã xác thực|verify code)\b", text):
            return IntentCategory.OTP
        if re.search(r"(?i)\b(pass|mật khẩu|password|token)\b", text):
            return IntentCategory.PASSWORD
        if re.search(r"(?i)\b(tiền|chuyển khoản|bank|stk|số tài khoản|vay|mượn|donate|nạp)\b", text):
            return IntentCategory.MONEY
        if re.search(r"(?i)\b(tài khoản|account|login|username)\b", text):
            return IntentCategory.ACCOUNT
        if re.search(r"(?i)\b(cccd|cmnd|căn cước|địa chỉ nhà|số điện thoại|sđt|zalo)\b", text):
            return IntentCategory.PRIVATE_INFO

        # 2. Goodnight / Bedtime
        if cls.is_goodnight(text):
            return IntentCategory.GOODNIGHT

        # 3. Busy / Texting back later / Leaving
        if cls.is_busy_or_closing(text):
            return IntentCategory.BUSY_LATER

        # 4. Scheduling and Dates (requires human confirmation)
        if re.search(r"(?i)\b(mấy giờ|ngày mai|hôm nay|cuối tuần|hẹn|gặp nhau|đi chơi|cafe nhé|uống nước)\b", text):
            return IntentCategory.DATE_DISCUSSION

        # 4. Flirt / Questions / Casual
        if "?" in text or re.search(r"(?i)\b(ở đâu|làm gì|bao nhiêu|như thế nào|sao lại|ai)\b", text):
            return IntentCategory.QUESTION
        if re.search(r"(?i)\b(xinh|dễ thương|cute|thích|nhớ|yêu|đẹp trai)\b", text):
            return IntentCategory.FLIRT
        if re.search(r"(?i)\b(chào|hi|hello|ê|hế lô|alo)\b", text):
            return IntentCategory.CASUAL

        return IntentCategory.NORMAL

    @classmethod
    def is_safe_for_auto_reply(cls, message_text: str) -> bool:
        """Return False if incoming message contains intents that must be manually handled."""
        intent = cls.classify(message_text)
        return intent not in UNSAFE_FOR_AUTO_REPLY
