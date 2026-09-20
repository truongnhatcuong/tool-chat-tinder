"""Auto-Opener service generating subtle, charming, profile-based Tinder opening lines."""
from typing import Any
from ai.client import LLMClient
from config.settings import get_settings
from utils.logger import logger

OPENER_SYSTEM_PROMPT = """Bạn soạn hộ tôi tin nhắn ĐẦU TIÊN trên Tinder cho một người vừa match. Viết như một người đang lướt Tinder trên điện thoại, KHÔNG như AI hay pickup line.

PHONG CÁCH: người Việt trẻ, chữ thường, cực ngắn, tự nhiên. Có thể :)) =)) kk, không lạm dụng.

TIN ĐẦU TIÊN: 2-8 từ. Chỉ cần phá băng. Ví dụ đúng phong cách:
"hello b :))" / "chào nha =))" / "ủa match r nè :))" / "hello hello" / "chào b nha" / "ê chào nha :))"
Mỗi lần viết KHÁC nhau, đừng lặp một mẫu.

TUYỆT ĐỐI KHÔNG:
- Khen ngoại hình/nụ cười ('nụ cười tươi', 'nhìn xịn'), pickup line, 'phải ghé qua chào liền', 'định mệnh', 'profile khiến tò mò'.
- Hỏi bất cứ câu nào (không phỏng vấn, không hỏi sở thích/đi chơi/tìm người yêu).
- Gọi tên kèm 'nha :D' kiểu chăm sóc khách hàng, không dùng ':D'.
- Suy diễn điểm chung ('giống nhau ghê', 'trùng hợp ghê') khi không có dữ liệu.
- Dùng bio chung chung (tìm ny, thích đi chơi, nghe nhạc, ăn uống, du lịch, vui vẻ...). Bio chỉ được nhắc khi có chi tiết CỰC cụ thể, nổi bật (nuôi 4 con mèo, nghiện Valorant, học tiếng Hàn, fan MU...), và khi đó nhắc rất nhẹ, vd 'ủa b cũng chơi valo à :))'. Nghi ngờ thì bỏ qua bio, chỉ chào.
- Bịa thông tin về tôi.

Nguyên tắc vàng: thiếu context thì ÍT hơn > NHIỀU hơn.
Chỉ trả về ĐÚNG 1 tin nhắn, không ngoặc kép, không giải thích."""


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

        if match_age is not None:
            if match_age <= my_age - 2:
                pronoun_guide = f"Bạn nữ ({match_age} tuổi) nhỏ tuổi hơn bạn ({my_age} tuổi) -> Hãy xưng 'anh' - gọi 'em' hoặc gọi tên '{name}'."
                fallback_reply = "hello b :))"
            elif match_age > my_age:
                pronoun_guide = f"Bạn nữ ({match_age} tuổi) lớn hơn bạn ({my_age} tuổi) -> Hãy xưng 'mình' - gọi 'bạn' hoặc gọi tên '{name}' (TUYỆT ĐỐI không xưng anh - gọi em)."
                fallback_reply = "hello b :))"
            else:
                pronoun_guide = f"Bạn nữ ({match_age} tuổi) sàn sàn bằng tuổi bạn ({my_age} tuổi) -> Hãy xưng 'mình' - gọi 'bạn' hoặc gọi tên '{name}'."
                fallback_reply = "hello b :))"
        else:
            pronoun_guide = f"Chưa rõ tuổi bạn nữ -> Mặc định xưng hô lịch sự: 'mình' - gọi 'bạn' hoặc gọi tên '{name}' (TUYỆT ĐỐI không tự ý gọi em hay xưng anh khi chưa biết tuổi)."
            fallback_reply = "hello b :))"

        user_prompt = f"""THÔNG TIN PROFILE MATCH:
- Tên: {name}
- Tuổi bạn nữ: {match_age if match_age else 'Chưa rõ'}
- Tuổi của bạn (chủ tài khoản): {my_age} tuổi
- Hướng dẫn xưng hô: {pronoun_guide}
- Giới thiệu bản thân (Bio): {bio or 'Không có bio'}
- Mục tiêu tìm kiếm: {goal or 'Chưa rõ'}
- Sở thích: {interests_str or 'Không có'}
- Khoảng cách / Địa điểm: {distance or 'Chưa rõ'}

Viết đúng 1 tin chào đầu tiên, 2-8 từ, không khen, không hỏi, không pickup line. Xưng hô (nếu cần): {pronoun_guide}"""

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
