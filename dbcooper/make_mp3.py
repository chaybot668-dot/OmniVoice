#!/usr/bin/env python3
"""Doc tts_text.txt -> dbcooper.mp3 bang OmniVoice (GPU). Moi doan = 1 lan generate, nghe tung doan o parts/."""
import argparse, subprocess, pathlib
import numpy as np, soundfile as sf, torch
from omnivoice import OmniVoice

ap = argparse.ArgumentParser()
ap.add_argument("--text", default="tts_text.txt")
ap.add_argument("--out", default="dbcooper.mp3")
ap.add_argument("--instruct", default="male, low pitch, american accent")  # giong dan phim tai lieu
ap.add_argument("--ref_audio"); ap.add_argument("--ref_text")             # hoac clone giong
ap.add_argument("--speed", type=float, default=0.95)
ap.add_argument("--pause", type=float, default=0.7, help="giay nghi giua cac doan")
a = ap.parse_args()

paras = [p.strip() for p in pathlib.Path(a.text).read_text().split("\n\n") if p.strip()]
model = OmniVoice.from_pretrained("k2-fsa/OmniVoice", device_map="cuda:0", dtype=torch.float16)
kw = dict(speed=a.speed, num_step=32)
if a.ref_audio:
    kw["voice_clone_prompt"] = model.create_voice_clone_prompt(ref_audio=a.ref_audio, ref_text=a.ref_text)
else:
    kw["instruct"] = a.instruct

parts = pathlib.Path("parts"); parts.mkdir(exist_ok=True)
sr, gap, chunks = 24000, np.zeros(int(24000 * a.pause), dtype=np.float32), []
for i, p in enumerate(paras, 1):
    audio = model.generate(text=p, **kw)[0].astype(np.float32)
    sf.write(parts / f"p{i:02d}.wav", audio, sr)
    chunks += [audio, gap]
    print(f"[{i}/{len(paras)}] {len(audio)/sr:.1f}s")
sf.write("full.wav", np.concatenate(chunks[:-1]), sr)
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", "full.wav", "-codec:a", "libmp3lame", "-q:a", "2", a.out], check=True)
print("Xong:", a.out)
