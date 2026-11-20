#!/usr/bin/env python3
"""Báo cáo kết quả + gói YouTube qua Telegram. Hai kênh TÁCH BIỆT: women / man.

Khóa bot nằm trong file env NGOÀI repo (mặc định ~/.omnivoice/telegram.env), không bao giờ commit:
  TELEGRAM_WOMEN_TOKEN=...   TELEGRAM_WOMEN_CHAT_ID=...
  TELEGRAM_MAN_TOKEN=...     TELEGRAM_MAN_CHAT_ID=...
--channel là BẮT BUỘC, và không bao giờ dùng nhầm khóa của kênh kia.

  python scripts/report_story.py --channel women --find-chat-id            # lấy chat id sau khi nhắn bot
  python scripts/report_story.py OUT_DIR --channel women --package stories/second-phone/package.json --dry-run
  python scripts/report_story.py OUT_DIR --channel women --package stories/second-phone/package.json [--send-audio]
"""
import argparse
import json
import mimetypes
import os
import re
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path

DEFAULT_ENV = Path.home() / ".omnivoice" / "telegram.env"
CHANNELS = ("women", "man")
FULL_NAME = "HER_SIDE_OF_THE_STORY_FULL_AUDIO.mp3"
MAX_UPLOAD = 49 * 1024 * 1024  # giới hạn bot gửi file của Telegram ~50 MB


def load_env(path):
    env = {}
    p = Path(path)
    if p.exists():
        for ln in p.read_text(encoding="utf-8-sig").splitlines():
            ln = ln.strip()
            if ln and not ln.startswith("#") and "=" in ln:
                k, v = ln.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    for k in list(os.environ):
        if k.startswith("TELEGRAM_"):
            env[k] = os.environ[k]
    return env


def creds(channel, env):
    up = channel.upper()
    return env.get(f"TELEGRAM_{up}_TOKEN"), env.get(f"TELEGRAM_{up}_CHAT_ID")


def api(token, method, fields=None, files=None):
    base = os.environ.get("TELEGRAM_API_BASE", "https://api.telegram.org")
    url = f"{base}/bot{token}/{method}"
    if files:
        b = uuid.uuid4().hex
        body = b""
        for k, v in (fields or {}).items():
            body += f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
        for k, fp in files.items():
            fp = Path(fp)
            ct = mimetypes.guess_type(fp.name)[0] or "application/octet-stream"
            body += (f'--{b}\r\nContent-Disposition: form-data; name="{k}"; '
                     f'filename="{fp.name}"\r\nContent-Type: {ct}\r\n\r\n').encode()
            body += fp.read_bytes() + b"\r\n"
        body += f"--{b}--\r\n".encode()
        req = urllib.request.Request(url, data=body, headers={
            "Content-Type": f"multipart/form-data; boundary={b}"})
    else:
        req = urllib.request.Request(url, data=json.dumps(fields or {}).encode(),
                                     headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        # Không in URL (có chứa token).
        raise SystemExit(f"Telegram lỗi {e.code} khi gọi {method}: {e.read()[:200].decode(errors='ignore')}")
    except urllib.error.URLError as e:
        raise SystemExit(f"Không kết nối được Telegram ({e.reason}).")


def _smart_title(text):
    small = {"of", "the", "a", "an", "and", "at", "to", "in", "on", "for", "his", "her"}
    words = text.lower().split()
    return " ".join(w if (i and w in small) else w.capitalize() for i, w in enumerate(words))


def pretty_title(raw):
    head, _, rest = raw.partition("—")
    if not rest:
        return _smart_title(raw)
    return f"{_smart_title(head.strip())}: {_smart_title(rest.strip())}"


def yt_time(mmss):
    m, s = (int(x) for x in mmss.split(":"))
    return f"{m}:{s:02d}" if m < 60 else f"{m // 60}:{m % 60:02d}:{s:02d}"


def build_package(out, pkg):
    chapters = []
    for ln in (out / "chapters.txt").read_text(encoding="utf-8").splitlines():
        m = re.match(r"(\d+:\d+)\s+(.*)", ln.strip())
        if m:
            chapters.append(f"{yt_time(m.group(1))} {pretty_title(m.group(2))}")
    if not chapters or not chapters[0].startswith("0:00"):
        raise SystemExit("chapters.txt thiếu mốc 0:00.")
    desc = "\n\n".join([
        pkg["description_intro"], "\n".join(pkg.get("highlights", [])),
        "⏱ CHAPTERS\n" + "\n".join(chapters), "\n".join(pkg.get("cta", [])),
        pkg["disclosure"], pkg["channel_line"], " ".join(pkg["hashtags"])])
    tag_chars = len(", ".join(pkg["tags"]))
    if tag_chars > 500:
        raise SystemExit(f"Tags dài {tag_chars} ký tự, YouTube giới hạn 500. Bớt tag.")
    for t in pkg["titles"]:
        if len(t) > 100:
            raise SystemExit(f"Tiêu đề quá 100 ký tự: {t}")
    lines = ["=== YOUTUBE PACKAGE ===", "", "TITLE OPTIONS (chọn 1, đều khớp nội dung):"]
    lines += [f"  {i}. {t}  [{len(t)} ký tự]" for i, t in enumerate(pkg["titles"], 1)]
    lines += ["", "DESCRIPTION:", desc, "", f"TAGS (dán vào ô Tags, {tag_chars}/500 ký tự):", ", ".join(pkg["tags"]),
              "", "THUMBNAIL TEXT (gợi ý):"] + [f"  - {t}" for t in pkg["thumbnail_text"]]
    lines += ["", "BÌNH LUẬN GHIM (tuỳ chọn):", pkg["pinned_comment"], "",
              "TRƯỚC KHI ĐĂNG:",
              "  - Mục 'Nội dung bị thay đổi hoặc tổng hợp' (altered/synthetic content) trong YouTube Studio: "
              "giọng đọc là giọng AI. Em chưa chắc YouTube có bắt buộc bật cho truyện hư cấu hay không, "
              "an toàn nhất là kiểm tra mục này và bật nếu YouTube yêu cầu.",
              "  - Dòng 'work of fiction' trong mô tả đã có sẵn, giữ nguyên để người xem không hiểu nhầm là chuyện thật.",
              "  - Upload đúng file ghép đã nghe lại; không dùng nhạc/âm thanh không có bản quyền."]
    return "\n".join(lines) + "\n", desc


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("out", nargs="?", help="thư mục kết quả của produce_story.py")
    ap.add_argument("--channel", required=True, choices=CHANNELS)
    ap.add_argument("--package", help="package.json của truyện")
    ap.add_argument("--env-file", default=str(DEFAULT_ENV))
    ap.add_argument("--dry-run", action="store_true", help="chỉ in nội dung, không gửi")
    ap.add_argument("--send-audio", action="store_true", help="gửi cả file ghép nếu < 49 MB")
    ap.add_argument("--find-chat-id", action="store_true")
    a = ap.parse_args()

    token, chat = creds(a.channel, load_env(a.env_file))
    up = a.channel.upper()
    if a.find_chat_id:
        if not token:
            raise SystemExit(f"Thiếu TELEGRAM_{up}_TOKEN trong {a.env_file}")
        r = api(token, "getUpdates")
        ids = {(m.get("message") or {}).get("chat", {}).get("id") for m in r.get("result", [])}
        ids.discard(None)
        print("Chat id tìm thấy:", ", ".join(map(str, ids)) or "chưa có - hãy nhắn 1 tin cho bot rồi chạy lại")
        return
    if not a.out or not a.package:
        raise SystemExit("Cần thư mục kết quả và --package.")
    out = Path(a.out)
    pkg_text, _ = build_package(out, json.loads(Path(a.package).read_text(encoding="utf-8")))
    (out / "youtube_package.txt").write_text(pkg_text, encoding="utf-8")
    report = (out / "production_report.txt").read_text(encoding="utf-8")
    msg = f"[{a.channel.upper()}] Hoàn tất audio\n\n{report}\nGói YouTube: youtube_package.txt (đính kèm)"
    if a.dry_run:
        print(f"--- DRY RUN: kênh {a.channel}, sẽ gửi tới chat {'đã cấu hình' if chat else 'CHƯA cấu hình'} ---")
        print(msg + "\n\n" + pkg_text)
        return
    if not token or not chat:
        raise SystemExit(f"Thiếu TELEGRAM_{up}_TOKEN hoặc TELEGRAM_{up}_CHAT_ID trong {a.env_file}. "
                         "Không dùng khóa của kênh khác.")
    api(token, "sendMessage", {"chat_id": chat, "text": msg[:4000]})
    api(token, "sendDocument", {"chat_id": chat, "caption": "YouTube package"},
        {"document": out / "youtube_package.txt"})
    if a.send_audio:
        f = out / FULL_NAME
        if f.exists() and f.stat().st_size <= MAX_UPLOAD:
            api(token, "sendDocument", {"chat_id": chat, "caption": "Full audio"}, {"document": f})
        else:
            print("Không gửi audio: file quá lớn hoặc không có (giới hạn ~49 MB).")
    print("Đã gửi báo cáo qua Telegram.")


if __name__ == "__main__":
    main()
