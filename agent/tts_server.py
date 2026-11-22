"""Máy chủ giọng đọc OmniVoice chạy trên máy (giữ mô hình trong bộ nhớ).

Chạy:  python agent/tts_server.py            (mặc định cổng 8765)
Claude gọi qua agent/say.py — OmniVoice chỉ làm đúng một việc: đọc chữ thành giọng.
"""
import argparse, io, json, sys, os, re, subprocess, threading, uuid
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
    design = os.path.join(VOICES, voice + ".design.txt")
    if not os.path.exists(wav) and os.path.exists(design):
        # Giọng thiết kế (không nhái ai): tạo 1 câu mẫu bằng mô tả, lưu lại rồi clone → lần nào cũng cùng giọng
        instruct, sample = [l.strip() for l in open(design, encoding="utf-8").read().strip().splitlines()[:2]]
        a = MODEL.generate(text=sample, instruct=instruct)[0]
        sf.write(wav, a, SR)
        open(os.path.join(VOICES, voice + ".txt"), "w", encoding="utf-8").write(sample)
    if not os.path.exists(wav):
        if voice != "default" and os.path.exists(os.path.join(VOICES, "default.wav")):
            return voice_kwargs("default", None)
        return {}  # không có giọng mẫu → OmniVoice tự chọn giọng
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


HERE = os.path.dirname(os.path.abspath(__file__))
CFG_PATH = os.path.join(HERE, "config.json")
CFG = json.load(open(CFG_PATH, encoding="utf-8")) if os.path.exists(CFG_PATH) else {}
OUT_ROOTS = [os.path.join(ROOT, "outputs")] + ([os.path.join(CFG["manstory_dir"], "projects")] if CFG.get("manstory_dir") else [])
JOBS = {}


def list_voices():
    return sorted({f.split(".")[0] for f in os.listdir(VOICES)
                   if f.endswith((".wav", ".pt", ".design.txt"))}) if os.path.isdir(VOICES) else []


def ffmpeg_exe():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        return "ffmpeg"


def speech_mp3(req):
    voice = req.get("voice")
    kw = voice_kwargs(voice, req.get("instruct"))
    used = voice if voice in list_voices() else ("default" if "default" in list_voices() else "auto")
    with LOCK:
        a = MODEL.generate(text=req["input"], speed=float(req.get("speed") or 1.0), **kw)[0].astype(np.float32)
    buf = io.BytesIO()
    sf.write(buf, a, SR, format="WAV")
    r = subprocess.run([ffmpeg_exe(), "-loglevel", "error", "-f", "wav", "-i", "pipe:0",
                        "-b:a", "192k", "-f", "mp3", "pipe:1"], input=buf.getvalue(), capture_output=True)
    if r.returncode:
        raise RuntimeError("ffmpeg lỗi: " + r.stderr.decode(errors="ignore")[:200])
    return r.stdout, used


def start_job(req):
    """Chạy Claude Code không giao diện: Claude làm agent, OmniVoice đọc."""
    jid = uuid.uuid4().hex[:8]
    topic = req["topic"].strip()
    lang = req.get("lang") or "vi"
    voice = req.get("voice") or ("en-host" if lang == "en" else "theo manstory.config.json" if lang == "auto" else CFG.get("default_voice") or "default")
    if req.get("mode") == "video" and CFG.get("manstory_dir"):
        cwd = CFG["manstory_dir"]
        prompt = (f"/manstory Chế độ tự động, làm video {'TIẾNG ANH (language en, xem references/tieng-anh.md)' if lang == 'en' else ('đúng ngôn ngữ của yêu cầu' if lang == 'auto' else 'tiếng Việt')}"
                  f" từ chủ đề sau, giọng OmniVoice local voice_id {voice}"
                  f"{', độ dài ' + req['length'] if req.get('length') else ''}: {topic}. "
                  "Chạy hết [0]–[7] không hỏi lại. Bước nào tốn credit (ảnh AI) thì bỏ qua, dùng explainer/sketch. "
                  "Cuối cùng in dòng: KET_QUA: <đường dẫn final.mp4>")
    else:
        cwd = ROOT
        prompt = (f"Làm theo skill omnivoice-tts. Ngôn ngữ: {'English' if lang == 'en' else 'tiếng Việt'}. Chủ đề: {topic}. Giọng: {voice}. "
                  f"Độ dài: {req.get('length') or 'khoảng 60 giây'}. Chạy hết không hỏi lại. "
                  "Cuối cùng in dòng: KET_QUA: <đường dẫn voice.wav>")
    JOBS[jid] = {"status": "running", "log": "", "cwd": cwd}
    cmd = [CFG.get("claude_cmd", "claude"), "-p", prompt, "--permission-mode", CFG.get("permission_mode", "acceptEdits"),
           "--allowedTools", *CFG.get("allowed_tools", ["Bash", "Read", "Write", "Edit", "Glob", "Grep", "WebSearch", "WebFetch", "Skill"])]

    def run():
        try:
            p = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                 text=True, encoding="utf-8", errors="replace", shell=(os.name == "nt"))
            for line in p.stdout:
                JOBS[jid]["log"] += line
            p.wait()
            JOBS[jid]["status"] = "done" if p.returncode == 0 else f"lỗi ({p.returncode})"
            m = re.search(r"KET_QUA:\s*(\S+)", JOBS[jid]["log"])
            if m:
                JOBS[jid]["file"] = os.path.join(cwd, m.group(1)) if not os.path.isabs(m.group(1)) else m.group(1)
        except Exception as e:
            JOBS[jid].update(status="lỗi", log=JOBS[jid]["log"] + f"\n{e}")

    threading.Thread(target=run, daemon=True).start()
    return jid


def telegram_watch():
    """Tự lấy việc gửi qua bot Telegram (/y chủ đề, /video kịch bản) → giao Claude làm video ManStory."""
    import time
    md = CFG["manstory_dir"]
    inbox = [sys.executable, os.path.join(md, ".claude", "skills", "manstory", "scripts", "telegram_inbox.py")]
    queue = []
    while True:
        try:
            if not any(j["status"] == "running" for j in JOBS.values()):
                if not queue:
                    r = subprocess.run(inbox, cwd=md, capture_output=True, text=True, encoding="utf-8", errors="replace")
                    queue += [l.strip() for l in r.stdout.splitlines() if l.strip().endswith(".md")]
                if queue:
                    f = queue.pop(0)
                    print("Telegram → việc mới:", f)
                    start_job({"mode": "video", "topic": f"việc trong file {f} (nhận từ Telegram; tự nhận biết tiếng Việt hay tiếng Anh: "
                               "tin viết tiếng Anh hoặc có chữ 'English'/'EN' → làm video tiếng Anh)", "lang": "auto"})
        except Exception as e:
            print("Telegram lỗi:", e)
        time.sleep(int(CFG.get("telegram_poll_seconds", 60)))


class H(BaseHTTPRequestHandler):
    def _send(self, code, obj):
        b = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(b)

    def _raw(self, code, data, ctype, headers=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            return self._raw(200, open(os.path.join(HERE, "app.html"), "rb").read(), "text/html; charset=utf-8")
        if self.path.startswith("/job/"):
            j = JOBS.get(self.path[5:])
            return self._send(200 if j else 404, j or {"error": "không có"})
        if self.path.startswith("/samples"):
            return self._send(200, {"data": [{"voice_id": v, "description": "giọng mẫu trong voices/"}
                                             for v in list_voices()]})
        if self.path.startswith("/file?"):
            from urllib.parse import parse_qs, urlparse
            f = os.path.abspath(parse_qs(urlparse(self.path).query)["p"][0])
            if not any(f.startswith(os.path.abspath(r)) for r in OUT_ROOTS):
                return self._send(403, {"error": "ngoài thư mục kết quả"})
            return self._raw(200, open(f, "rb").read(), "application/octet-stream")
        self._send(200, {"ok": True, "voices": list_voices(), "video": bool(CFG.get("manstory_dir"))})

    def do_POST(self):
        if self.path.endswith("/audio/speech"):  # tương thích SaydiVoice/OpenAI → ManStory dùng được
            try:
                req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                data, used = speech_mp3(req)
                return self._raw(200, data, "audio/mpeg", {"X-OV-Voice": used, "X-OV-Chars": str(len(req["input"]))})
            except Exception as e:
                return self._send(400, {"error": str(e)})
        if self.path == "/job":
            req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            return self._send(200, {"id": start_job(req)})
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
    if CFG.get("telegram_watch") and CFG.get("manstory_dir"):
        threading.Thread(target=telegram_watch, daemon=True).start()
        print("Đang nghe Telegram: gửi bot '/y <chủ đề>' là tự làm video")
    print(f"Sẵn sàng: http://127.0.0.1:{a.port}")
    ThreadingHTTPServer(("127.0.0.1", a.port), H).serve_forever()


if __name__ == "__main__":
    main()
