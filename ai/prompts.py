from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def load_my_profile() -> str:
    """Load user's personal background from thong_tin.md if it exists."""
    for filename in ["thong_tin.md", "thông tin.md", "profile.md"]:
        path = BASE_DIR / filename
        if path.exists():
            try:
                content = path.read_text(encoding="utf-8").strip()
                if content:
                    return content
            except Exception:
                pass
    return ""


def load_questions() -> str:
    """Load friendly questions from cau_hoi.md if it exists."""
    path = BASE_DIR / "cau_hoi.md"
    if path.exists():
        try:
            content = path.read_text(encoding="utf-8").strip()
            if content:
                return content
        except Exception:
            pass
    return ""


def load_system_prompt() -> str:
    """Load the core system prompt directly from system_prompt.md."""
    path = BASE_DIR / "system_prompt.md"
    if path.exists():
        try:
            content = path.read_text(encoding="utf-8").strip()
            if content:
                return content
        except Exception:
            pass
    return ""


TINDER_SYSTEM_PROMPT = load_system_prompt()


def build_chat_prompt(
    name: str,
    age: int | None,
    bio: str | None,
    interests: list[str] | str | None,
    summary: str | None,
    style: str | None,
    recent_history: list[dict[str, str]],
    new_message: str,
    memory_block: str | None = None,
    guidance: str | None = None,
) -> list[dict[str, str]]:
    """Assemble system and user messages for OpenAI-compatible chat completions."""
    interests_str = ", ".join(interests) if isinstance(interests, list) else (interests or "None")
    
    # Format history
    history_lines = []
    for msg in recent_history:
        sender = msg.get("sender", "User")
        if sender == "You":
            sender = "TÔI (bạn)"
        content = msg.get("content", "")
        history_lines.append(f"{sender}: {content}")
    history_str = "\n".join(history_lines) if history_lines else "None"

    # Age is profile context, not permission to force anh/em. Mirror the actual
    # conversation: only use anh/em after the match has explicitly established it.
    age_context = f", profile ghi {age} tuổi" if age is not None else ""
    pronoun_instruction = (
        "ưu tiên giữ đúng đại từ trong lịch sử chat; nếu họ dùng 'tui/b' thì giữ "
        "'tui/b', nếu dùng 'mình/bạn' thì giữ 'mình/bạn', nếu chưa rõ thì dùng "
        f"'mình/bạn', 'tui/b' nhẹ hoặc bỏ đại từ{age_context}; tuyệt đối không tự "
        "xưng anh/gọi em chỉ dựa vào tuổi, chỉ dùng anh/em khi họ đã chủ động xác lập"
    )

    total_msgs = len(recent_history)
    if total_msgs <= 2:
        stage = "NEW_MATCH"
    elif total_msgs <= 6:
        stage = "WARM_UP"
    elif total_msgs <= 20:
        stage = "ACTIVE_CHAT"
    else:
        stage = "DEEP_CHAT"

    my_profile = load_my_profile()
    my_profile_section = f"\nTHÔNG TIN VỀ TÔI (CHỦ TÀI KHOẢN - DÙNG ĐỂ GIỚI THIỆU CHÍNH XÁC KHI ĐƯỢC HỎI):\n{my_profile}\n" if my_profile else ""
    my_questions = load_questions()
    questions_section = f"\nDANH SÁCH CÂU HỎI THAM KHẢO (DÙNG ĐỂ KHƠI GỢI KHI CẦN THIẾT):\n{my_questions}\n" if my_questions else ""

    current_system_prompt = load_system_prompt()
    guidance_section = f"\nGỢI Ý NHỊP TRẢ LỜI LƯỢT NÀY:\n{guidance}\n" if guidance else ""

    if memory_block:
        context_text = f"""{memory_block}
{my_profile_section}{questions_section}
MATCH PROFILE:
- Tên: {name or 'Unknown'}
- Tuổi: {age or 'Chưa rõ'}
- Gợi ý xưng hô (chỉ dùng khi phần CÁCH XƯNG HÔ ở trên chưa rõ): {pronoun_instruction}
- Bio (chỉ tham khảo): {bio or 'Không có bio'}
- Sở thích (chỉ tham khảo, đừng hỏi về nó): {interests_str}

NHIỆM VỤ: Trả về kết quả dưới dạng JSON theo đúng cấu trúc ở mục "OUTPUT CONTRACT" trong System Prompt. Ngắn (3-15 từ/tin), phản hồi đúng TIN MỚI NHẤT của họ, đúng chủ đề hiện tại, giữ đúng cách xưng hô đang dùng, KHÔNG hỏi lại bất kỳ câu nào trong danh sách "đã hỏi rồi", KHÔNG bịa thông tin. Phản hồi đúng ý họ trước, có thể trêu/chia sẻ/khen nhẹ. KHÔNG hỏi sau mọi lượt: chỉ hỏi (đúng 1 câu) khi thật sự cần mở rộng chuyện; mỗi 2-3 lượt phải có ít nhất 1 lượt không hỏi, tối đa 2 lượt hỏi liền; nếu họ đã kể nhiều về một chủ đề thì không hỏi lại chủ đề đó. Không hiểu câu họ nói thì hỏi làm rõ, không đoán."""
        return [
            {"role": "system", "content": current_system_prompt},
            {"role": "user", "content": context_text},
        ]

    context_text = f"""CONVERSATION_STAGE: {stage}
LAST_SENDER: match (họ vừa nhắn)
{my_profile_section}{questions_section}
MATCH PROFILE:
- Tên: {name or 'Unknown'}
- Tuổi: {age or 'Chưa rõ'}
- Hướng dẫn xưng hô: {pronoun_instruction}
- Bio: {bio or 'Không có bio'}
- Sở thích (chỉ tham khảo, đừng hỏi về nó): {interests_str}
- Tóm tắt cuộc trò chuyện: {summary or 'Mới bắt đầu'}
- Phong cách: {style or 'Tự nhiên, thân thiện'}

LỊCH SỬ TIN NHẮN GẦN ĐÂY:
{history_str}

TIN NHẮN MỚI NHẤT TỪ {name or 'BẠN ẤY'}:
"{new_message}"
{guidance_section}
NHIỆM VỤ: Trả về kết quả dưới dạng JSON theo đúng cấu trúc ở mục "OUTPUT CONTRACT". Ngắn (3-15 từ/tin), phản hồi đúng nội dung họ vừa nhắn, không bịa thông tin. Phản hồi đúng ý trước, có thể trêu/chia sẻ/khen nhẹ; chỉ hỏi (đúng 1 câu) khi thật sự cần mở rộng chuyện, không hỏi sau mọi lượt (mỗi 2-3 lượt có ít nhất 1 lượt không hỏi, tối đa 2 lượt hỏi liền). Không hỏi lại chủ đề họ đã kể nhiều; không chốt bằng 'ghê z'. Thỉnh thoảng (không liên tục) khi vibe tốt có thể khen nhẹ vibe/cách nói chuyện/ảnh (không bắt buộc kèm câu hỏi). Không hỏi random, không hỏi lại điều đã biết, không đặt 2 câu hỏi. Xưng hô: {pronoun_instruction}."""

    return [
        {"role": "system", "content": current_system_prompt},
        {"role": "user", "content": context_text}
    ]
