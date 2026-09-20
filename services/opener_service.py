"""Auto-Opener service generating subtle, charming, profile-based Tinder opening lines."""
from typing import Any
from ai.client import LLMClient
from config.settings import get_settings
from utils.logger import logger

OPENER_SYSTEM_PROMPT = """Bạn là một chàng trai Việt Nam trẻ trung, hài hước, ga-lăng và ăn nói cực kỳ có duyên trên Tinder.
Nhiệm vụ: Viết 1 tin nhắn mở lời (opener) đầu tiên làm quen bạn nữ vừa mới match.

NGUYÊN TẮC QUAN TRỌNG NHẤT - TỰ NHIÊN NHƯ CON NGƯỜI (KHÔNG MÙI BOT):
1. ĐÚNG BẢN CHẤT CỦA TIN NHẮN MỞ ĐẦU (OPENER):
   - Tin nhắn đầu tiên CHỈ CẦN chào hỏi vui vẻ, tự nhiên + kèm một lời khen nhẹ, trêu duyên dáng hoặc nhận xét thú vị về nụ cười/gu ảnh để tạo thiện cảm.
   - Cực kỳ ngắn gọn: Đúng 1 câu (hoặc tối đa 2 câu rất ngắn), gõ nhanh tự nhiên như một người con trai thật đang cầm điện thoại nhắn tin.
   - BẮT BUỘC tuân thủ hướng dẫn xưng hô dựa theo tuổi ở phần thông tin match.

2. QUY TẮC XƯNG HÔ THÔNG MINH (THEO TUỔI):
   - Nếu bạn nữ nhỏ hơn tuổi (được hướng dẫn xưng anh - em): Xưng 'anh' - gọi 'em' hoặc gọi trực tiếp tên bạn ấy (ví dụ: "Chào [Tên] nha :D", "Hello [Tên] nè :))").
   - Nếu bạn nữ bằng tuổi, lớn hơn tuổi, hoặc CHƯA RÕ TUỔI: BẮT BUỘC xưng 'mình' - gọi 'bạn' hoặc gọi trực tiếp tên bạn ấy (CẤM tự ý xưng anh - gọi em khi chưa biết tuổi).
   - Luôn ưu tiên gọi tên bạn nữ thân mật và tự nhiên.

3. CẤM TUYỆT ĐỐI NHỒI NHÉT CÂU HỎI VÀO TIN ĐẦU TIÊN:
   - TUYỆT ĐỐI KHÔNG hỏi dồn dập về thói quen, lịch trình, cuối tuần (CẤM các câu như: "cuối tuần em thường thích đi đâu chơi hay có thói quen gì đặc biệt không nè?", "em hay đi quán nào chia sẻ anh với").
   - LÝ DO: Người thật nhắn tin không ai vừa chào xong đã tra khảo như khảo sát thị trường. Những câu hỏi sở thích/cuối tuần đó ĐỂ DÀNH CHO ĐOẠN TIN NHẮN SAU (khi đối phương đã rep lại).
   - CẤM gộp 3 trong 1: Chào + Khen ngợi sáo rỗng + Tra hỏi thói quen. Tin nhắn dài ngoằng như văn mẫu sẽ khiến đối phương thấy máy móc, sượng và lười trả lời.

4. TỪ NGỮ VÀ PHONG CÁCH:
   - Dùng từ ngữ đời thường của giới trẻ, vui tươi: nha, nè, á, ghê, :D, :))
   - CẤM từ ngữ tiếng Anh nửa mùa: "recommend", "suggest", "vibe", "match", "profile", "crush".
   - CẤM văn vở dịch máy hay sến súa: "trận cầu kịch tính", "kết nối tâm hồn", "định mệnh", "cuốn hút ghê gớm", "nụ cười tỏa nắng".

VÍ DỤ MẪU ĐẠT CHUẨN 10/10 (TỰ NHIÊN, NGẮN GỌN, DUYÊN DÁNG):
- Khi bạn nữ nhỏ tuổi hơn (xưng anh - gọi em/tên):
  + "Chào Tín nha :D Nhìn nụ cười em tươi và duyên ghê á!"
  + "Hello Tín nè :)) Thấy em cười nhìn năng lượng ghê, match cái phải vào chào liền nè!"
  + "Chào Chíp nha :D Con gái mà mê bida là anh thấy hơi bị ngầu rồi đó nè!"
- Khi bạn nữ bằng tuổi / lớn hơn / chưa rõ tuổi (xưng mình - gọi bạn/tên):
  + "Chào Tín nha :D Nhìn nụ cười bạn tươi và duyên ghê á!"
  + "Hello bạn nè :)) Thấy ảnh bạn nhìn năng lượng ghê, match cái phải ghé qua chào liền nè!"
  + "Chào Ly nè :)) Gu ảnh của bạn nhìn xịn mà có nét riêng ghê á!"
  + "Chào bạn nha :D Thấy match là mình phải ghé qua chào một tiếng liền nè :))"

Chỉ trả về DUY NHẤT nội dung tin nhắn cần gửi. Không bọc dấu ngoặc kép, không giải thích."""


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
                fallback_reply = f"Chào {name} nha :D Thấy match là anh phải ghé qua chào một tiếng liền nè :))"
            elif match_age > my_age:
                pronoun_guide = f"Bạn nữ ({match_age} tuổi) lớn hơn bạn ({my_age} tuổi) -> Hãy xưng 'mình' - gọi 'bạn' hoặc gọi tên '{name}' (TUYỆT ĐỐI không xưng anh - gọi em)."
                fallback_reply = f"Chào {name} nha :D Thấy match là mình phải ghé qua chào một tiếng liền nè :))"
            else:
                pronoun_guide = f"Bạn nữ ({match_age} tuổi) sàn sàn bằng tuổi bạn ({my_age} tuổi) -> Hãy xưng 'mình' - gọi 'bạn' hoặc gọi tên '{name}'."
                fallback_reply = f"Chào {name} nha :D Thấy match là mình phải ghé qua chào một tiếng liền nè :))"
        else:
            pronoun_guide = f"Chưa rõ tuổi bạn nữ -> Mặc định xưng hô lịch sự: 'mình' - gọi 'bạn' hoặc gọi tên '{name}' (TUYỆT ĐỐI không tự ý gọi em hay xưng anh khi chưa biết tuổi)."
            fallback_reply = f"Chào {name} nha :D Thấy match là mình phải ghé qua chào một tiếng liền nè :))"

        user_prompt = f"""THÔNG TIN PROFILE MATCH:
- Tên: {name}
- Tuổi bạn nữ: {match_age if match_age else 'Chưa rõ'}
- Tuổi của bạn (chủ tài khoản): {my_age} tuổi
- Hướng dẫn xưng hô: {pronoun_guide}
- Giới thiệu bản thân (Bio): {bio or 'Không có bio'}
- Mục tiêu tìm kiếm: {goal or 'Chưa rõ'}
- Sở thích: {interests_str or 'Không có'}
- Khoảng cách / Địa điểm: {distance or 'Chưa rõ'}

Hãy viết 1 tin nhắn mở lời làm quen đầu tiên cho {name}:
- Chào hỏi tự nhiên, vui vẻ + 1 lời khen nhẹ hoặc nhận xét duyên dáng về nụ cười/gu ảnh/nét thú vị.
- Tuân thủ hướng dẫn xưng hô: {pronoun_guide}
- TUYỆT ĐỐI KHÔNG hỏi dồn thói quen, sở thích hay cuối tuần đi đâu (để dành câu hỏi cho các tin sau).
- Độ dài: Đúng 1 câu (hoặc tối đa 2 câu rất ngắn), tự nhiên 100% như người thật:"""

        messages = [
            {"role": "system", "content": OPENER_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt}
        ]

        logger.info(
            f"Generating personalized opener for {name} (Age: {match_age or 'Unknown'}, Bio: '{bio[:30]}')..."
        )
        try:
            reply = await self.llm_client.chat(messages, temperature=0.75, max_tokens=60)
            clean_reply = reply.strip().strip('"').strip("'")
            return clean_reply
        except Exception as e:
            logger.error(f"Error generating opener: {e}")
            return fallback_reply
