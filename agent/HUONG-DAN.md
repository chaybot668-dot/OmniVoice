# OmniVoice Agent — Windows + NVIDIA (vd RTX 4060 Ti 16GB)

## Cài 1 lần
1. Cài **Python 3.11** (python.org, tick "Add python.exe to PATH"), **Node.js LTS**, **Git**.
2. `npm i -g @anthropic-ai/claude-code` rồi gõ `claude` một lần để đăng nhập.
3. Tải repo OmniVoice (nhánh `claude/brave-mendel-bggnu8`), nháy đúp **install.bat** (~10–15 phút).
4. Sửa `agent\config.json`: `manstory_dir` = thư mục repo manstory trên máy (để chế độ Video).
5. Giọng mặc định: `voices\default.wav` (3–10 giây, nói rõ, ít tạp âm) + `voices\default.txt` (lời trong đoạn đó).
   Thêm giọng khác: `voices\<ten>.wav` + `.txt`. Không có giọng mẫu → OmniVoice tự chọn giọng.

## Dùng
Nháy đúp **start.bat** → trình duyệt mở `http://127.0.0.1:8765` (lần đầu tải mô hình vài GB; trang trắng thì chờ rồi F5).
Nhập chủ đề → chọn **Chỉ giọng đọc** hoặc **Video ManStory** → Chạy.

## ManStory
`manstory.config.json` → `"voice_provider": "omnivoice"`: mọi giọng đọc ManStory gọi OmniVoice trên máy (start.bat phải đang chạy).
Muốn quay lại SaydiVoice: đổi thành `"saydivoice"`.

## Tiếng Anh + tự động hoàn toàn
- Giọng tiếng Anh `en-host` (nam trẻ, giọng Mỹ, giọng **thiết kế**, không nhái ai): lần đầu dùng tự tạo `voices\en-host.wav`,
  các lần sau cùng một giọng. Không ưng → xóa `voices\en-host.wav/.txt/.pt` để tạo giọng khác, hoặc sửa dòng 1 của `en-host.design.txt`.
- `agent\config.json`: `"manstory_dir": "C:/Users/TGC/manstory"`, `"telegram_watch": true` → nhắn bot Telegram `/y <chủ đề>` là tự làm video.
- Khóa của ManStory để trong file `C:\Users\TGC\manstory\.env`:
  `TELEGRAM_BOT_TOKEN=...`, `TELEGRAM_CHAT_ID=...`, `PIXABAY_API_KEY=...`
