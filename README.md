# Tinder AI Assistant - Desktop Application

Ứng dụng Desktop tự động hóa hỗ trợ quản lý hội thoại Tinder an toàn và thông minh bằng Python, Playwright, PySide6, asyncio và OpenAI-compatible LLM.

---

## 1. Yêu cầu hệ thống (Requirements)

- **Hệ điều hành:** Windows 10/11, macOS, Linux
- **Python:** 3.12+ (Đã kiểm thử và tối ưu trên Python 3.14)
- **Browser:** Chromium (quản lý bởi Playwright)
- **Cơ sở dữ liệu:** MySQL (hoặc SQLite local)

---

## 2. Cài đặt môi trường

### Bước 1: Tạo và kích hoạt Virtual Environment

**Windows:**
```powershell
python -m venv .venv
.venv\Scripts\activate
```

**macOS / Linux:**
```bash
python -m venv .venv
source .venv/bin/activate
```

### Bước 2: Cài đặt thư viện phụ thuộc

```bash
pip install -r requirements.txt
playwright install chromium
```

---

## 3. Cấu hình (.env)

Tạo file `.env` từ file mẫu `.env.example`:

```env
# AI Configuration (OpenAI-compatible)
AI_API_KEY=your_actual_ai_api_key_here
AI_BASE_URL=https://api.openai.com/v1
AI_MODEL=gpt-4o-mini

# Database Configuration (MySQL hoặc SQLite)
# Với MySQL:
DATABASE_URL=mysql+aiomysql://root:password@localhost:3306/tinder_ai
# Với SQLite local:
# DATABASE_URL=sqlite+aiosqlite:///./data/tinder_ai.db

# Safety Defaults (Bắt buộc an toàn khi khởi chạy)
DRY_RUN=true
GLOBAL_AUTO_REPLY=false
INSPECT_DOM=true
DEBUG=true
```

---

## 4. Hướng dẫn chạy ứng dụng

### Chạy ứng dụng Desktop (PySide6 GUI):
```bash
python app.py
```

### Chạy Playwright Inspector để debug DOM trực tiếp:
```bash
PWDEBUG=1 python app.py
```

---

## 5. Các chế độ hoạt động (Modes)

1. **AUTO (Mặc định - Tự động hoàn toàn)**:
   - Khi có tin nhắn đến -> Hệ thống gom tin nhắn (debounce 3-5s) -> AI phân tích ngữ cảnh, tính cách đối phương -> Soạn câu trả lời tự nhiên, duyên dáng và **TỰ ĐỘNG GỬI LUÔN** vào Tinder mà bạn **không cần phải bấm duyệt thủ công**.
   - An toàn tuyệt đối: Luôn qua màng lọc kiểm duyệt (không tự phát ngôn nhạy cảm, không lộ OTP, mật khẩu, chuyển khoản).

2. **SUGGEST (Chế độ xem trước / duyệt thủ công)**:
   - Phát hiện tin nhắn mới -> AI sinh câu trả lời đề xuất trên giao diện.
   - Bạn xem trước câu trả lời, có thể chỉnh sửa, bấm **Regenerate** để AI viết lại, hoặc bấm **Send** khi ưng ý.

3. **OFF (Tắt trả lời)**:
   - Tạm dừng trả lời match này (không sinh tin nhắn, không gửi).

### 🌟 Tính năng thông minh mới:
- **Tự động chuyển sang OFF khi đi ngủ / báo bận / hẹn nhắn lại sau**:
  - **Trường hợp 1 (Đi ngủ / Chúc ngủ ngon):** Đối phương nhắn *"ngủ ngon nha anh"*, *"em đi ngủ đây"*, *"mai nói chuyện tiếp nhé"*, *"g9"*...
    - AI gửi lại lời chúc ngủ ngon ấm áp, ngọt ngào (không hỏi thêm câu mới).
    - Match tự động chuyển sang `OFF` (hiển thị `💤 Ngủ ngon (OFF)`).
  - **Trường hợp 2 (Báo bận / Hẹn nhắn sau / Đi làm):** Đối phương nhắn *"em bận xíu"*, *"tí em nhắn lại sau nhé"*, *"lát nc sau nha"*, *"chuẩn bị vào ca rồi"*, *"hôm khác nói chuyện tiếp"*, *"rảnh nhắn sau"*...
    - AI đáp lại thông cảm, lịch sự và thoải mái (ví dụ: *"Oke em, cứ lo việc đi nhé, khi nào rảnh nhắn anh sau nè!"* - không hỏi thêm câu mới dồn dập).
    - Match tự động chuyển sang `OFF` (hiển thị `⏳ Bận / Nhắn sau (OFF)`) để không gửi thêm tin nhắn làm phiền lúc họ đang bận!
  - Nếu bạn chủ động bấm gửi một câu kết thúc / đi ngủ / báo bận, match cũng tự động đưa về `OFF`.
- **Tự động dọn dẹp khi Hủy tương hợp (Auto-Cleanup on Unmatch)**:
  - Khi bạn hoặc đối phương bấm **Hủy tương hợp (Unmatch)** trên Tinder:
  - Bot quét và phát hiện người đó không còn trên Tinder nữa -> **Tự động xóa sạch toàn bộ dữ liệu của người đó khỏi MySQL** (gồm profile, cuộc trò chuyện, tin nhắn) và **tự động xóa khỏi danh sách trên màn hình Desktop**.
  - Giữ cho database và danh sách hội thoại của bạn luôn sạch sẽ, đồng bộ 100% với Tinder!
- **Thanh công cụ Chuyển tất cả 1-Click (Batch Toolbar)**:
  - Trên danh sách Matches có 3 nút bấm nhanh: **`[🔴 Tất cả OFF]`**, **`[🟡 Tất cả SUGGEST]`**, **`[🟢 Tất cả AUTO]`**.
  - Chỉ 1 lần bấm là cập nhật đồng loạt cho toàn bộ matches trên giao diện lẫn trong cơ sở dữ liệu MySQL. Rất tiện lợi vào buổi tối khi muốn tắt hết hoặc buổi sáng khi muốn bật tự động.

---

## 6. Chạy Test Suite

Để chạy toàn bộ unit test và integration test (kiểm tra phân luồng cô lập, debounce, SHA256 chống trùng, rate limiting, safety validation):

```bash
python -m pytest -v
```

---

## 7. Đóng gói Desktop App (PyInstaller)

Sau khi hoàn tất kiểm tra DOM thật và kiểm thử an toàn:

```bash
pyinstaller --noconsole --name TinderAIAssistant app.py
```
