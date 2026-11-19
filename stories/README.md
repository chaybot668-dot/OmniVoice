# Quy trình truyện (kênh women)

1. Kịch bản gốc -> `original_script.txt`; `prepare_story.py` tạo `story.txt` (không đổi chữ).
2. `produce_story.py` (hỏi giọng + nền tảng trước) -> MP3 + `chapters.txt` + `production_report.txt`.
3. Chủ kênh gửi mốc chương -> tạo gói YouTube từ `package.json` rồi gửi Telegram đúng kênh (`women` / `man`, không lẫn).

## Quy tắc gói YouTube (chủ kênh yêu cầu)
- Tiêu đề: khơi gợi để người xem muốn bấm, nhưng PHẢI khớp nội dung truyện (không giật tít sai). Tối đa 100 ký tự. 3-5 phương án, đề nghị 1.
- Tags: nhiều và chính xác, chỉ tag đúng nội dung (không gắn "true story" cho truyện hư cấu). Tổng tối đa 500 ký tự.
- Mô tả: có emoji; có mốc chương (bắt đầu 0:00); có CTA (like, subscribe, câu hỏi bình luận). Không mồi tương tác kiểu "comment 1 nếu...".
- Luôn giữ dòng "work of fiction" + giọng AI; nhắc kiểm tra mục nội dung tổng hợp trong YouTube Studio.
