"""Auto-Opener service generating subtle, charming, profile-based Tinder opening lines."""
from typing import Any
import random
from ai.client import LLMClient
from ai.output_guard import build_retry_feedback, find_violations
from config.settings import get_settings
from utils.logger import logger

OPENER_SYSTEM_PROMPT = """Bạn là AI hỗ trợ Cường soạn tin nhắn ĐẦU TIÊN (Opener) trên Tinder cho một người vừa match.
Viết như một người Gen Z Việt Nam đang lướt Tinder trên điện thoại, tự nhiên, cuốn và có chút badboy/trapboy vibe.

MỤC TIÊU QUAN TRỌNG NHẤT:
Gây ấn tượng mạnh ngay từ câu đầu tiên bằng sự tự tin, bạo dạn và thả thính trực diện.
TUYỆT ĐỐI KHÔNG lặp đi lặp lại một kiểu máy móc: "chào [Tên] nha :))" hay "chào [Tên] nè :))" cho tất cả mọi người.

NGÔN NGỮ GEN Z:
- Chữ thường, ngắn gọn (5-15 từ), đời thường, tự tin.
- Từ ngữ tự nhiên: "b", "bạn", "nha", "á", "z", "r", "v", "hong", "hả", "ủa", "ơ", "ê", "vibe", "cuốn", "chill", ":))", "=))".
- Giọng điệu hơi bỡn cợt, trêu ghẹo một chút.

XƯNG HÔ:
- Có thể dùng "b", "bạn" hoặc xưng hô trống không tự nhiên.
- Ưu tiên gọi "người đẹp", "bạn xinh" để tăng tính thả thính.

QUY TẮC MỞ LỜI THEO THỨ TỰ ƯU TIÊN:
Trước khi nhắn, phải đọc profile (ảnh, bio, sở thích) để tìm một chi tiết đáng chú ý:
Tấn công trực diện > trêu ghẹo mặn mòi > khen ngầm tạo tension > thả thính bất chấp.

1. NẾU PROFILE CÓ CHI TIẾT CỤ THỂ (ảnh biển, cà phê, đồ ăn, thú cưng, bio):
- Ảnh biển: "ủa đi biển mà hong rủ tui ha :))"
- Ảnh cà phê: "quán này chill đấy, nhưng đi với tui còn chill hơn =))"
- Đồ ăn: "nhìn món này ngon ngang ngửa profile bạn á :))"
- Mèo/chó: "match vì chủ hay vì mèo đây ta, chắc là vì chủ rồi :))"
- Bio mê ngủ: "mê ngủ v có thời gian mơ thấy tui hong =))"
- Bio ít/trống: "profile bí ẩn dữ z, bắt tui tự tìm hiểu đúng k :))"
- Nhiều ảnh đẹp/chất: "ủa gu tui rớt ở đây nè :))"

2. NẾU KHÔNG CÓ CHI TIẾT RÕ RÀNG ĐỂ BẮT CHUYỆN:
Dùng opener tấn công trực diện, trêu nhẹ hoặc khen vibe:
- "tự nhiên lướt qua profile bạn cái thấy vui ngang =))"
- "người đẹp này gu tui nha :))"
- "match được bạn tự nhiên thấy ngày nay may mắn ghê :))"
- "ủa profile này làm người ta dễ tương tư nha"
- "ê nhìn b quen quen á, giống người yêu tương lai của tui :))"
- "ơ kìa, cuối cùng tui cũng match được gu mình :))"
- "vừa thấy profile là phải vô thả thính liền nè"
- "ủa sao vibe cuốn dữ z, tính làm người ta mê mệt hả :))"

CẤM:
- TUYỆT ĐỐI KHÔNG gửi câu rập khuôn: "chào [Tên] nha :))", "chào [Tên] nè :))", "hello [Tên]".
- KHÔNG dùng lời chào máy móc: "Xin chào, rất vui được làm quen với bạn", "Chào bạn, hôm nay bạn thế nào?".
- Tránh sến súa quá đà kiểu sướt mướt. Thả thính ngầu, tự tin, không bi lụy.
- Không bắt buộc câu nào cũng kết thúc bằng câu hỏi.

CHỈ TRẢ VỀ ĐÚNG 1 CÂU TIN NHẮN (không ngoặc kép, không giải thích)."""


SAFE_OPENERS = [
    "ơ match thiệt nè :))",
    "ủa profile này cuốn nha",
    "ê nhìn b quen quen á :))",
    "ơ kìa, cuối cùng cũng match :))",
    "app nay làm ăn được nè =))",
]


class OpenerService:
    """Generates clever, personalized Tinder openers tailored to match profiles."""

    def __init__(self, llm_client: LLMClient | None = None):
        self.llm_client = llm_client or LLMClient()
        self.settings = get_settings()

    async def generate_opener(self, profile: dict[str, Any]) -> str:
        name = (profile.get("name") or "").strip() or "bạn"
        bio = profile.get("bio", "")
        interests = profile.get("interests", [])
        goal = profile.get("goal", "")
        distance = profile.get("distance", "")

        interests_str = ", ".join(interests) if isinstance(interests, list) else str(interests)

        # Parse match age and determine pronouns based on user_age
        my_age = getattr(self.settings, "user_age", 24)
        match_age: int | None = None
        raw_age = profile.get("age")
        if raw_age is not None:
            try:
                digits = "".join(filter(str.isdigit, str(raw_age)))
                if digits:
                    match_age = int(digits)
            except Exception:
                pass

        if match_age is not None and match_age <= my_age - 2:
            pronoun_guide = f"Bạn nữ ({match_age} tuổi) nhỏ hơn bạn ({my_age} tuổi) -> Ưu tiên 'b', 'bạn', 'người đẹp' hoặc bỏ đại từ (chưa vội xưng anh/em ngay ở câu đầu)."
        elif match_age is not None and match_age > my_age:
            pronoun_guide = f"Bạn nữ ({match_age} tuổi) lớn hơn bạn ({my_age} tuổi) -> xưng 'mình' - gọi 'bạn' (TUYỆT ĐỐI không xưng anh - gọi em)."
        else:
            pronoun_guide = "Chưa rõ tuổi hoặc bằng tuổi -> Dùng 'b', 'bạn', 'người đẹp' khi hợp vibe hoặc bỏ đại từ."

        user_prompt = f"""THÔNG TIN PROFILE MATCH:
- Tên: {name}
- Tuổi: {match_age if match_age else 'Chưa rõ'}
- Bio: {bio or 'Không có bio'}
- Mục tiêu tìm kiếm: {goal or 'Chưa rõ'}
- Sở thích: {interests_str or 'Không có'}
- Khoảng cách: {distance or 'Chưa rõ'}
- Hướng dẫn xưng hô: {pronoun_guide}

Nhiệm vụ: Soạn đúng 1 tin mở đầu (5-15 từ) tự nhiên như người Gen Z vừa match xong nhắn liền.
Ưu tiên: Chi tiết riêng trên bio/ảnh/sở thích > trêu nhẹ > tạo tò mò > khen vibe > chào cuốn.
CẤM: Không dùng câu rập khuôn kiểu 'chào {name} nha :))' hay 'chào {name} nè :))'."""

        messages = [
            {"role": "system", "content": OPENER_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt}
        ]

        logger.info(
            f"Generating personalized opener for {name} (Age: {match_age or 'Unknown'}, Bio: '{bio[:30]}')..."
        )
        try:
            reply = await self.llm_client.chat(messages, temperature=0.9, max_tokens=80)
            clean_reply = reply.strip().strip('"').strip("'")
            problems = find_violations([clean_reply], [], is_opener=True, name=name)
            if problems:
                logger.warning(f"Opener for {name} violated rules, retrying once: {problems}")
                retry = messages + [
                    {"role": "assistant", "content": reply},
                    {"role": "user", "content": build_retry_feedback(problems, json_reply=False)},
                ]
                reply = await self.llm_client.chat(retry, temperature=0.9, max_tokens=80)
                clean_reply = reply.strip().strip('"').strip("'")
                if find_violations([clean_reply], [], is_opener=True, name=name):
                    logger.warning(f"Opener retry for {name} still invalid; using safe opener.")
                    return random.choice(SAFE_OPENERS)
            return clean_reply
        except Exception as e:
            logger.error(f"Error generating opener: {e}")
            return random.choice(SAFE_OPENERS)
