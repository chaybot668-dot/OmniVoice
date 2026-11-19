#!/usr/bin/env python3
"""Nhập khóa bot Telegram NGAY TRÊN MÁY BẠN (ẩn khi gõ) và lưu vào ~/.omnivoice/telegram.env.

  python scripts/setup_telegram.py women
  python scripts/setup_telegram.py man

Khóa không hiện trên màn hình, không đi qua chat, không nằm trong repo.
"""
import getpass
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ENV = Path.home() / ".omnivoice" / "telegram.env"


def call(token, method):
    base = os.environ.get("TELEGRAM_API_BASE", "https://api.telegram.org")
    try:
        with urllib.request.urlopen(f"{base}/bot{token}/{method}", timeout=30) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise SystemExit(f"Telegram từ chối ({e.code}). Khóa sai hoặc bot đã bị xóa.")
    except urllib.error.URLError as e:
        raise SystemExit(f"Không kết nối được Telegram ({e.reason}).")


def save(updates):
    data = {}
    if ENV.exists():
        for ln in ENV.read_text(encoding="utf-8").splitlines():
            if "=" in ln and not ln.strip().startswith("#"):
                k, v = ln.split("=", 1)
                data[k.strip()] = v.strip()
    data.update(updates)
    ENV.parent.mkdir(parents=True, exist_ok=True)
    ENV.write_text("".join(f"{k}={v}\n" for k, v in data.items()), encoding="utf-8")
    try:
        os.chmod(ENV, 0o600)
    except OSError:
        pass


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in ("women", "man"):
        raise SystemExit("Dùng: python scripts/setup_telegram.py women|man")
    ch = sys.argv[1]
    up = ch.upper()
    token = getpass.getpass(f"Dán khóa bot kênh {ch} (gõ ẩn, nhấn Enter): ").strip()
    if not token:
        raise SystemExit("Chưa nhập khóa.")
    me = call(token, "getMe")["result"]
    print(f"Khóa hợp lệ. Bot: @{me.get('username')}")
    input(f"Giờ mở Telegram, nhắn 1 tin bất kỳ cho @{me.get('username')}, rồi quay lại nhấn Enter...")
    ids = {(u.get("message") or {}).get("chat", {}).get("id")
           for u in call(token, "getUpdates").get("result", [])}
    ids.discard(None)
    if not ids:
        save({f"TELEGRAM_{up}_TOKEN": token})
        raise SystemExit("Đã lưu khóa nhưng chưa thấy chat id. Nhắn bot một tin rồi chạy lại lệnh này.")
    chat = sorted(ids)[-1]
    save({f"TELEGRAM_{up}_TOKEN": token, f"TELEGRAM_{up}_CHAT_ID": str(chat)})
    print(f"Đã lưu kênh {ch} (chat id {chat}) vào {ENV}")


if __name__ == "__main__":
    main()
