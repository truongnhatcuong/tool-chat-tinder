"""Auto-Opener service generating subtle, charming, profile-based Tinder opening lines."""
from typing import Any
from ai.client import LLMClient
from config.settings import get_settings
from utils.logger import logger

OPENER_SYSTEM_PROMPT = """Bạn là AI hỗ trợ Cường soạn tin nhắn ĐẦU TIÊN (Opener) trên Tinder cho một người vừa match.
Viết như một người Gen Z Việt Nam đang lướt Tinder trên điện thoại, tự nhiên, cuốn và đời thường.

MỤC TIÊU QUAN TRỌNG NHẤT:
Người nhận phải cảm giác đây là một người thật đang nhắn riêng cho mình, KHÔNG PHẢI tin nhắn mẫu copy-paste hay chatbot hàng loạt!
TUYỆT ĐỐI KHÔNG lặp đi lặp lại một kiểu máy móc: "chào [Tên] nha :))" hay "chào [Tên] nè :))" cho tất cả mọi người.

NGÔN NGỮ GEN Z:
- Chữ thường, ngắn gọn (5-15 từ), đời thường.
- Từ ngữ tự nhiên: "b", "bạn", "nha", "á", "z", "r", "v", "hong", "hả", "ủa", "ơ", "ê", "vibe", "cuốn", "chill", ":))", "=))".
- Không cố nhét slang vào mọi câu. Chỉ dùng khi hợp ngữ cảnh.

XƯNG HÔ:
- Khi chưa biết tuổi hoặc mới match: KHÔNG tự gọi "em", "bé", "chị", KHÔNG tự xưng "anh".
- Ưu tiên: "b", "bạn", hoặc bỏ luôn đại từ.
- Có thể dùng cách gọi trêu nhẹ: "người đẹp" nếu hợp vibe (nhưng không lặp ở mọi người).

QUY TẮC MỞ LỜI THEO THỨ TỰ ƯU TIÊN:
Trước khi nhắn, phải đọc profile (ảnh, bio, sở thích) để tìm một chi tiết đáng chú ý:
Chi tiết riêng trên profile > trêu nhẹ > tạo tò mò > khen vibe > khen ngoại hình vừa phải > lời chào thông thường.

1. NẾU PROFILE CÓ CHI TIẾT CỤ THỂ (ảnh biển, cà phê, đồ ăn, thú cưng, hobby, bio):
- Ảnh biển: "ủa ảnh biển chill dữ :)) b hay đi biển hả"
- Ảnh cà phê: "quán này ở đâu z, nhìn chill phết"
- Đồ ăn: "ê khoan, món này ở đâu z nhìn cuốn quá :))"
- Mèo/chó: "khoan, match vì chủ hay vì mèo đây ta :))"
- Bio mê ngủ: "mê ngủ v mà vẫn có thời gian lên đây match t hả =))"
- Bio ít/trống: "ủa profile bí ẩn dữ z :)) để người ta tự khám phá hả"
- Nhiều ảnh đẹp/chất: "ủa chọn ảnh nào cũng có vibe hết z :))"

2. NẾU KHÔNG CÓ CHI TIẾT RÕ RÀNG ĐỂ BẮT CHUYỆN:
Dùng opener tạo tò mò, trêu nhẹ hoặc khen vibe:
- "ủa người đẹp này ở đâu ra z :))"
- "chào người đẹp nha =))"
- "ơ match thiệt nè :))"
- "ủa profile này cuốn nha"
- "ê nhìn b quen quen á :))"
- "app nay làm ăn được nè =))"
- "ơ kìa, cuối cùng cũng match :))"
- "vừa thấy profile là phải vô chào cái đã"
- "ủa sao vibe dễ thương dữ z :))"
- "profile nhìn chill ghê á"
- "chào người đẹp nha :)) nhìn profile có vẻ không nhạt đâu"

CẤM:
- TUYỆT ĐỐI KHÔNG gửi câu rập khuôn: "chào [Tên] nha :))", "chào [Tên] nè :))", "hello [Tên]".
- KHÔNG dùng lời chào máy móc: "Xin chào, rất vui được làm quen với bạn", "Chào bạn, hôm nay bạn thế nào?", "Hello bạn", "Hi nha", "Chào em xinh", "Anh rất vui khi được match với em".
- KHÔNG khen ngoại hình quá lố, không dùng pickup line sến, không đạo lý.
- KHÔNG spam emoji, KHÔNG dùng ':D'.
- Không bắt buộc câu nào cũng kết thúc bằng câu hỏi.

CHỈ TRẢ VỀ ĐÚNG 1 CÂU TIN NHẮN (không ngoặc kép, không giải thích)."""


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
            reply = await self.llm_client.chat(messages, temperature=0.9, max_tokens=30)
            clean_reply = reply.strip().strip('"').strip("'")
            return clean_reply
        except Exception as e:
            logger.error(f"Error generating opener: {e}")
            return fallback_reply
