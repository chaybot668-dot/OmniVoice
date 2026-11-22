"""Claude gọi lệnh này để bảo OmniVoice đọc.

  python agent/say.py --script outputs/x/script.txt --out outputs/x/voice.wav [--voice sep] [--instruct "male, low pitch"]
  python agent/say.py --text "Một câu." --out outputs/test.wav
  python agent/say.py --ping
Mỗi dòng không trống trong script = một câu đọc riêng.
"""
import argparse, json, sys, urllib.request, os

sys.stdout.reconfigure(encoding="utf-8")
p = argparse.ArgumentParser()
p.add_argument("--script"); p.add_argument("--text"); p.add_argument("--out")
p.add_argument("--voice"); p.add_argument("--instruct")
p.add_argument("--speed", type=float, default=1.0); p.add_argument("--pause", type=float, default=0.35)
p.add_argument("--num-step", type=int, default=32); p.add_argument("--per-line", action="store_true")
p.add_argument("--ping", action="store_true"); p.add_argument("--port", type=int, default=8765)
a = p.parse_args()
url = f"http://127.0.0.1:{a.port}"
try:
    if a.ping:
        print(urllib.request.urlopen(url, timeout=5).read().decode()); sys.exit(0)
    lines = open(a.script, encoding="utf-8").read().splitlines() if a.script else [a.text or ""]
    body = {"lines": lines, "out": os.path.abspath(a.out or "outputs/out.wav"), "voice": a.voice,
            "instruct": a.instruct, "speed": a.speed, "pause": a.pause,
            "num_step": a.num_step, "per_line": a.per_line}
    req = urllib.request.Request(url, json.dumps(body).encode(), {"Content-Type": "application/json"})
    r = json.loads(urllib.request.urlopen(req, timeout=3600).read())
    print(json.dumps({k: r[k] for k in ("out", "seconds")}, ensure_ascii=False))
except urllib.error.HTTPError as e:
    print("LỖI:", e.read().decode()); sys.exit(1)
except OSError as e:
    print("LỖI: máy chủ giọng chưa chạy → mở cửa sổ khác: python agent/tts_server.py", e); sys.exit(1)
