#!/usr/bin/env python3
"""Giọng "Women Story Life" (kênh Her Side of the Story) trên OmniVoice.

Ba lệnh:
  candidates  Tạo 3 giọng ứng viên (A/B/C) cùng một đoạn mẫu ~60-90 giây để nghe so sánh.
  select      Chọn 1 ứng viên và LƯU thành giọng chính thức `women_story_life`.
  narrate     Đọc một file kịch bản bằng giọng đã lưu -> WAV 48 kHz/24-bit + MP3 nghe thử.

Giọng được lưu dưới dạng VoiceClonePrompt (.pt) nên mọi tập sau đều dùng đúng một giọng.
Mặc định lưu ở ~/.omnivoice/voices/women_story_life/ (đổi bằng --voice-dir).

Ví dụ:
  python scripts/women_story_life.py candidates
  python scripts/women_story_life.py select A
  python scripts/women_story_life.py narrate episode01.txt --out out/ep01
"""

import argparse
import logging
import re
import shutil
import subprocess
import json
from pathlib import Path

import numpy as np
import soundfile as sf
import torch

from omnivoice import OmniVoice
from omnivoice.models.omnivoice import VoiceClonePrompt
from omnivoice.utils.common import fix_random_seed, get_best_device

VOICE_NAME = "women_story_life"
DEFAULT_DIR = Path.home() / ".omnivoice" / "voices" / VOICE_NAME

# OmniVoice chỉ hiểu: gender / age / pitch / whisper / accent (xem docs/voice-design.md).
# "Ấm, khàn nhẹ, thở nhẹ" KHÔNG điều khiển được bằng chữ -> 3 ứng viên khác nhau ở
# cao độ, tốc độ và seed; chọn bằng cách nghe.
CANDIDATES = {
    "A": dict(
        label="The Warm Confidante",
        instruct="female, middle-aged, moderate pitch, american accent",
        speed=0.95,
        seed=11,
    ),
    "B": dict(
        label="The Emotional Storyteller",
        instruct="female, middle-aged, low pitch, american accent",
        speed=0.92,
        seed=22,
    ),
    "C": dict(
        label="The Calm and Elegant Narrator",
        instruct="female, middle-aged, moderate pitch, american accent",
        speed=0.90,
        seed=33,
    ),
}

# Đoạn ngắn (~12 giây) dùng làm "giọng gốc" để lưu.
ANCHOR_TEXT = (
    "I was sitting at my kitchen table when my daughter finally admitted what she "
    "had done. I remember looking at her, and realizing something I had never "
    "wanted to believe. I didn't know my own child anymore."
)

# Đoạn mẫu ~70-90 giây, giống hệt nhau cho cả 3 ứng viên.
SAMPLE_TEXT = """\
I was sitting at my kitchen table when my daughter finally admitted what she had done. I remember looking at her, and realizing something I had never wanted to believe. I didn't know my own child anymore.

I spent thirty years making sure she had everything she needed. Quiet dinners, school fees, the little envelope of cash I slipped into her coat pocket when she moved away. I never kept count. A mother isn't supposed to keep count.

Then, one morning, I opened the account where I had saved for my retirement, and it was empty.

I called her. She didn't pick up. I called again, and again, and finally she answered, and her voice was so calm that it frightened me. She said she had needed it. She said I would understand someday.

I did not shout. I want you to know that. I just stood there, in my own kitchen, holding the phone, and I felt something inside me go very still.

It took me a long time to forgive her. It took me even longer to forgive myself, for believing that love alone could keep a family safe.

But I learned something that winter. Setting a boundary is not the same as closing your heart. Sometimes it is the only way to keep it open."""

# Chế độ cảm xúc A-H (prompt gốc) -> chỉ chỉnh được NHỊP ĐỌC. OmniVoice không có
# núm cảm xúc; phần còn lại phụ thuộc vào dấu câu và cách viết kịch bản.
MODE_SPEED = {
    "A": 0.93,  # Intimate confession
    "B": 0.98,  # Nostalgic reflection
    "C": 0.92,  # Quiet disappointment
    "D": 0.90,  # Betrayal and shock
    "E": 1.00,  # Confrontation
    "F": 0.90,  # Heartbreak
    "G": 0.97,  # Inner strength
    "H": 0.92,  # Wisdom and closing
}
DEFAULT_SPEED = 0.95  # ~125-140 từ/phút
PARAGRAPH_PAUSE = 0.7  # giây
MODE_TAG = re.compile(r"^\[([A-H])\]\s*")


def load_model(device=None):
    device = device or get_best_device()
    logging.info("Loading k2-fsa/OmniVoice on %s ...", device)
    dtype = torch.float32 if device == "cpu" else torch.float16
    return OmniVoice.from_pretrained("k2-fsa/OmniVoice", device_map=device, dtype=dtype)


def gen(model, text, seed, **kw):
    fix_random_seed(seed)
    return model.generate(text=text, language="en", **kw)[0]


def build_prompt(model, cand):
    """Voice design -> đoạn gốc ngắn -> VoiceClonePrompt có thể lưu và dùng lại."""
    audio = gen(model, ANCHOR_TEXT, cand["seed"],
                instruct=cand["instruct"], speed=cand["speed"])
    wav = torch.from_numpy(np.asarray(audio, dtype=np.float32)).reshape(1, -1)
    prompt = model.create_voice_clone_prompt(
        ref_audio=(wav, model.sampling_rate), ref_text=ANCHOR_TEXT
    )
    return prompt, audio


def cmd_candidates(args):
    model = load_model(args.device)
    out = Path(args.voice_dir) / "candidates"
    out.mkdir(parents=True, exist_ok=True)
    for key, cand in CANDIDATES.items():
        logging.info("Voice %s - %s", key, cand["label"])
        prompt, anchor = build_prompt(model, cand)
        prompt.save(str(out / f"voice_{key}.pt"))
        sf.write(out / f"voice_{key}_anchor.wav", anchor, model.sampling_rate)
        # Mẫu đánh giá được tạo BẰNG chính giọng đã lưu -> đúng thứ sẽ dùng khi đọc truyện.
        sample = gen(model, SAMPLE_TEXT, cand["seed"],
                     voice_clone_prompt=prompt, speed=cand["speed"])
        sf.write(out / f"voice_{key}_sample.wav", sample, model.sampling_rate)
        (out / f"voice_{key}.json").write_text(
            json.dumps(cand, indent=2), encoding="utf-8")
        logging.info("  sample: %.1fs", len(sample) / model.sampling_rate)
    print(f"\nXong. Nghe 3 file voice_*_sample.wav trong:\n  {out}\n"
          "Chọn giọng bằng: python scripts/women_story_life.py select A|B|C")


def cmd_select(args):
    src = Path(args.voice_dir) / "candidates"
    key = args.choice.upper()
    if not (src / f"voice_{key}.pt").exists():
        raise SystemExit(f"Chưa có ứng viên {key}. Chạy 'candidates' trước.")
    dst = Path(args.voice_dir)
    shutil.copy(src / f"voice_{key}.pt", dst / f"{VOICE_NAME}.pt")
    shutil.copy(src / f"voice_{key}_sample.wav", dst / f"{VOICE_NAME}_sample.wav")
    meta = dict(CANDIDATES[key], name=VOICE_NAME, brand="Her Side of the Story",
                candidate=key, anchor_text=ANCHOR_TEXT)
    (dst / f"{VOICE_NAME}.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Đã lưu giọng '{VOICE_NAME}' (ứng viên {key}) tại {dst}")


def split_chunks(paragraph, max_words=60):
    """Tách đoạn dài theo câu để mỗi lần sinh ngắn, giữ giọng ổn định."""
    sents = re.split(r"(?<=[.!?…])\s+", paragraph.strip())
    chunks, cur = [], []
    for s in sents:
        if cur and sum(len(x.split()) for x in cur) + len(s.split()) > max_words:
            chunks.append(" ".join(cur))
            cur = []
        cur.append(s)
    if cur:
        chunks.append(" ".join(cur))
    return chunks


def cmd_narrate(args):
    voice = Path(args.voice_dir) / f"{VOICE_NAME}.pt"
    if not voice.exists():
        raise SystemExit("Chưa lưu giọng. Chạy 'candidates' rồi 'select' trước.")
    prompt = VoiceClonePrompt.load(str(voice))
    meta = json.loads((voice.with_suffix(".json")).read_text(encoding="utf-8"))
    seed = meta["seed"]
    model = load_model(args.device)
    sr = model.sampling_rate
    paragraphs = [p for p in Path(args.script).read_text(encoding="utf-8").split("\n\n")
                  if p.strip()]
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    parts, report = [], []
    for i, para in enumerate(paragraphs, 1):
        m = MODE_TAG.match(para.strip())
        mode = m.group(1) if m else None
        text = MODE_TAG.sub("", para.strip())
        speed = MODE_SPEED.get(mode, DEFAULT_SPEED)
        for j, chunk in enumerate(split_chunks(text)):
            logging.info("Paragraph %d/%d chunk %d", i, len(paragraphs), j + 1)
            parts.append(gen(model, chunk, seed + i * 100 + j,
                             voice_clone_prompt=prompt, speed=speed))
            parts.append(np.zeros(int(0.25 * sr), dtype=np.float32))
        parts[-1] = np.zeros(int(PARAGRAPH_PAUSE * sr), dtype=np.float32)
        report.append(f"p{i}: mode={mode or '-'} speed={speed}")
    audio = np.concatenate(parts).astype(np.float32)
    raw = out / "raw.wav"
    sf.write(raw, audio, sr)

    words = sum(len(p.split()) for p in paragraphs)
    minutes = len(audio) / sr / 60
    final, mp3 = out / "master_48k_24bit.wav", out / "preview.mp3"
    if shutil.which("ffmpeg"):
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", str(raw),
             "-af", "loudnorm=I=-16:TP=-1:LRA=11", "-ar", "48000",
             "-c:a", "pcm_s24le", str(final)], check=True)
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", str(final),
             "-b:a", "192k", str(mp3)], check=True)
    else:
        logging.warning("Không có ffmpeg: chỉ xuất raw.wav, chưa chuẩn hoá -16 LUFS.")
    (out / "report.txt").write_text(
        f"voice: {VOICE_NAME} ({meta['candidate']} - {meta['label']})\n"
        f"duration: {minutes:.2f} min | words: {words} | wpm: {words / minutes:.0f}\n"
        + "\n".join(report) + "\n", encoding="utf-8")
    print(f"Xong: {out} ({minutes:.1f} phút, {words / minutes:.0f} wpm)")


def main():
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--voice-dir", default=str(DEFAULT_DIR))
    ap.add_argument("--device", default=None)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("candidates").set_defaults(fn=cmd_candidates)
    s = sub.add_parser("select")
    s.add_argument("choice", choices=list("ABCabc"))
    s.set_defaults(fn=cmd_select)
    n = sub.add_parser("narrate")
    n.add_argument("script", help="file .txt, các đoạn cách nhau 1 dòng trống; "
                   "đầu đoạn có thể ghi [A]..[H] để chọn nhịp theo chế độ cảm xúc")
    n.add_argument("--out", default="out/episode")
    n.set_defaults(fn=cmd_narrate)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
