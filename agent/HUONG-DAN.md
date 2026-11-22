# Hướng dẫn chạy trên máy (1 lần)

1. Cài Python 3.10+, Claude Code (`npm i -g @anthropic-ai/claude-code`).
2. Trong thư mục repo:
   - NVIDIA: `pip install torch==2.8.0+cu128 torchaudio==2.8.0+cu128 --extra-index-url https://download.pytorch.org/whl/cu128`
   - Mac / CPU: `pip install torch==2.8.0 torchaudio==2.8.0`
   - Rồi: `pip install -e .`
3. (Tuỳ chọn) Giọng riêng: bỏ `voices/sep.wav` (3–10 giây, nói rõ) + `voices/sep.txt` (lời trong đoạn đó).

# Dùng hằng ngày
- Cửa sổ 1: `python agent/tts_server.py` (lần đầu tải mô hình vài GB, chờ chữ "Sẵn sàng").
- Cửa sổ 2: `claude` → gõ chủ đề, vd: *"Làm bài đọc 60 giây về thói quen tiết kiệm, giọng sep"*.
- Kết quả ở `outputs/<ngày>-<tên>/`: `voice.wav`, `script.md`, `sources.md`, `voice.timing.json`.
