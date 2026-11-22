"""Máy chủ giọng đọc OmniVoice chạy trên máy (giữ mô hình trong bộ nhớ).

Chạy:  python agent/tts_server.py            (mặc định cổng 8765)
Claude gọi qua agent/say.py — OmniVoice chỉ làm đúng một việc: đọc chữ thành giọng.
"""
import argparse, json, os, re, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import numpy as np, soundfile as sf, torch
from omnivoice import OmniVoice, VoiceClonePrompt

SR = 24000
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VOICES = os.path.join(ROOT, "voices")
LOCK = threading.Lock()
MODEL = None


def pick_device():
    if torch.cuda.is_available():
        return "cuda:0", torch.float16
    if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        return "mps", torch.float16
    return "cpu", torch.float32


def voice_kwargs(voice, instruct):
    """voice = tên giọng trong thư mục voices/ (x.pt, hoặc x.wav + x.txt)."""
    if instruct:
        return {"instruct": instruct}
    if not voice:
        return {}
    pt = os.path.join(VOICES, voice + ".pt")
    if os.path.exists(pt):
        return {"voice_clone_prompt": VoiceClonePrompt.load(pt)}
    wav = os.path.join(VOICES, voice + ".wav")
    if not os.path.exists(wav):
        raise FileNotFoundError(f"Không thấy giọng '{voice}' trong voices/")
    txt = os.path.join(VOICES, voice + ".txt")
    ref_text = open(txt, encoding="utf-8").read().strip() if os.path.exists(txt) else None
    prompt = MODEL.create_voice_clone_prompt(ref_audio=wav, ref_text=ref_text)
    prompt.save(pt)  # lần sau nạp nhanh
    return {"voice_clone_prompt": prompt}


def synth(req):
    lines = [l.strip() for l in req["lines"] if l and l.strip()]
    if not lines:
        raise ValueError("lines rỗng")
    kw = voice_kwargs(req.get("voice"), req.get("instruct"))
    gap = np.zeros(int(SR * float(req.get("pause", 0.35))), dtype=np.float32)
    out = req.get("out") or os.path.join(ROOT, "outputs", "out.wav")
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    stem = re.sub(r"\.\w+$", "", out)
    pieces, segs, t = [], [], 0.0
    with LOCK:
        for i, line in enumerate(lines, 1):
            a = MODEL.generate(text=line, speed=float(req.get("speed", 1.0)),
                               num_step=int(req.get("num_step", 32)), **kw)[0].astype(np.float32)
            if req.get("per_line"):
                sf.write(f"{stem}_{i:02d}.wav", a, SR)
            d = len(a) / SR
            segs.append({"i": i, "text": line, "start": round(t, 3), "end": round(t + d, 3)})
            pieces += [a, gap]
            t += d + len(gap) / SR
    sf.write(out, np.concatenate(pieces[:-1]), SR)
    with open(stem + ".timing.json", "w", encoding="utf-8") as f:
        json.dump(segs, f, ensure_ascii=False, indent=1)
    return {"out": out, "seconds": round(t - len(gap) / SR, 2), "lines": segs}


class H(BaseHTTPRequestHandler):
    def _send(self, code, obj):
        b = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        voices = sorted({os.path.splitext(f)[0] for f in os.listdir(VOICES)
                         if f.endswith((".wav", ".pt"))}) if os.path.isdir(VOICES) else []
        self._send(200, {"ok": True, "voices": voices})

    def do_POST(self):
        try:
            req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            self._send(200, synth(req))
        except Exception as e:  # trả lỗi cho Claude đọc
            self._send(400, {"error": str(e)})

    def log_message(self, *a):
        pass


def main():
    global MODEL
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--model", default="k2-fsa/OmniVoice")
    a = p.parse_args()
    dev, dt = pick_device()
    print(f"Đang nạp OmniVoice trên {dev}…")
    MODEL = OmniVoice.from_pretrained(a.model, device_map=dev, dtype=dt)
    print(f"Sẵn sàng: http://127.0.0.1:{a.port}")
    ThreadingHTTPServer(("127.0.0.1", a.port), H).serve_forever()


if __name__ == "__main__":
    main()
