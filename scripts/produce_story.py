#!/usr/bin/env python3
"""Sản xuất audiobook nhiều chương từ stories/<tên>/story.txt bằng giọng đã lưu.

Quy tắc bắt buộc (giống `narrate`): phải chọn GIỌNG và NỀN TẢNG trước khi tạo audio.
Quy tắc thời lượng: tổng 30-45 phút, 4.500-6.000 từ. Ngoài khoảng đó -> KHÔNG xuất MP3.

Định dạng story.txt:
  ## 1. Tên chương
  [A]            <- (tuỳ chọn) chế độ cảm xúc A-H, chỉ chỉnh nhịp đọc
  Đoạn văn...    <- các đoạn cách nhau 1 dòng trống

Ví dụ:
  python scripts/produce_story.py stories/second-phone/story.txt --out D:\\voices\\out\\second-phone ^
      --voice-dir D:\\voices\\women_story_life --only 1          # thử chương 1 trước
  python scripts/produce_story.py stories/second-phone/story.txt --out D:\\voices\\out\\second-phone ^
      --voice-dir D:\\voices\\women_story_life                  # cả truyện (hỏi giọng + nền tảng)
Chạy lại sau khi bị ngắt: các chương đã đọc xong được giữ trong <out>/work nên không đọc lại.
"""

import argparse
import importlib.util
import json
import logging
import re
import shutil
import subprocess
from argparse import Namespace
from pathlib import Path

import numpy as np
import soundfile as sf

FILES = [
    "01_The_Phone_That_Shouldnt_Be_There.mp3",
    "02_The_Man_Who_Always_Had_An_Explanation.mp3",
    "03_The_Woman_Behind_The_Letter_M.mp3",
    "04_The_Messages_That_Changed_Everything.mp3",
    "05_The_Woman_Who_Believed_His_Story.mp3",
    "06_What_The_Phone_Was_Really_Hiding.mp3",
    "07_The_Last_Lie.mp3",
    "08_The_Day_I_Stopped_Looking_For_Answers.mp3",
]
FULL_NAME = "HER_SIDE_OF_THE_STORY_FULL_AUDIO.mp3"
MIN_WORDS, MAX_WORDS = 4500, 6000
MIN_MIN, MAX_MIN = 30.0, 45.0
CHUNK_GAP = 0.4  # giây, giữa các câu trong cùng đoạn (0.3-0.5)
PARA_GAP = 0.9  # giây, giữa các đoạn (0.7-1.2)
CHAPTER_GAP = 0.8  # giây, giữa các chương trong file ghép
TARGET_LUFS, TARGET_TP = -16.0, -1.0


def load_base():
    spec = importlib.util.spec_from_file_location(
        "wsl", Path(__file__).with_name("women_story_life.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def parse_story(path, w):
    chapters = []
    for block in re.split(r"(?m)^## ", Path(path).read_text(encoding="utf-8"))[1:]:
        title, body = block.split("\n", 1)
        paras = []
        for p in re.split(r"\n\s*\n", body.strip()):
            p = p.strip()
            m = w.MODE_TAG.match(p)
            text = " ".join(w.MODE_TAG.sub("", p).split())
            if text:
                paras.append((m.group(1) if m else None, text))
        chapters.append(dict(title=title.strip(), paras=paras))
    return chapters


def count_words(ch):
    return sum(len(t.split()) for _, t in ch["paras"])


def render_chapter(w, model, prompt, seed, idx, ch, sr, work):
    cache = work / f"ch{idx:02d}.wav"
    if cache.exists():
        logging.info("Chương %d: dùng bản đã đọc (%s)", idx, cache)
        return sf.read(cache, dtype="float32")[0]
    parts = []
    for i, (mode, text) in enumerate(ch["paras"], 1):
        speed = w.MODE_SPEED.get(mode, w.DEFAULT_SPEED)
        chunks = w.split_chunks(text)
        for j, chunk in enumerate(chunks):
            logging.info("Chương %d - đoạn %d/%d - câu %d/%d", idx, i, len(ch["paras"]),
                         j + 1, len(chunks))
            parts.append(np.asarray(w.gen(model, chunk, seed + idx * 1000 + i * 10 + j,
                                          voice_clone_prompt=prompt, speed=speed),
                                    dtype=np.float32).reshape(-1))
            gap = PARA_GAP if j == len(chunks) - 1 else CHUNK_GAP
            parts.append(np.zeros(int(gap * sr), dtype=np.float32))
    audio = np.concatenate(parts[:-1])  # bỏ khoảng lặng cuối chương
    sf.write(cache, audio, sr)
    return audio


def ff(*args):
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *args], check=True)


def measure(path):
    r = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-af",
         f"loudnorm=I={TARGET_LUFS}:TP={TARGET_TP}:LRA=11:print_format=json",
         "-f", "null", "-"], capture_output=True, text=True)
    j = json.loads(re.findall(r"\{[^{}]*\}", r.stderr, re.S)[-1])
    return float(j["input_i"]), float(j["input_tp"])


def probe(path):
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries",
         "stream=sample_rate,channels,bit_rate:format=duration", "-of", "json", str(path)],
        capture_output=True, text=True, check=True)
    j = json.loads(r.stdout)
    s = j["streams"][0]
    return float(j["format"]["duration"]), int(s["sample_rate"]), int(s["channels"]), \
        int(s.get("bit_rate", 0)) // 1000


def to_mp3(src_wav, dst, gain_db):
    ff("-i", str(src_wav), "-af",
       f"aresample=44100,volume={gain_db:.3f}dB,alimiter=limit=0.891:level=disabled",
       "-ac", "2", "-b:a", "192k", str(dst))


def mmss(sec):
    return f"{int(sec // 60):02d}:{int(sec % 60):02d}"


def main():
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("story")
    ap.add_argument("--out", required=True)
    w = load_base()
    ap.add_argument("--voice-dir", default=str(w.DEFAULT_DIR))
    ap.add_argument("--voices-root")
    ap.add_argument("--voice", help="tên giọng (bỏ trống = hỏi)")
    ap.add_argument("--platform", help="YouTube | TikTok | Facebook (bỏ trống = hỏi)")
    ap.add_argument("--yes", action="store_true", help="bỏ xác nhận cuối (vẫn cần --voice, --platform)")
    ap.add_argument("--only", type=int, help="chỉ đọc thử chương này, không ghép, không kiểm thời lượng")
    ap.add_argument("--device")
    a = ap.parse_args()
    if not shutil.which("ffmpeg"):
        raise SystemExit("Cần ffmpeg để xuất MP3 và đo âm lượng.")

    chapters = parse_story(a.story, w)
    if len(chapters) != len(FILES):
        raise SystemExit(f"Truyện phải có đúng {len(FILES)} chương, đang có {len(chapters)}.")
    words = sum(count_words(c) for c in chapters)
    print(f"Số từ lời đọc: {words} (cho phép {MIN_WORDS}-{MAX_WORDS})")
    if not a.only and not (MIN_WORDS <= words <= MAX_WORDS):
        raise SystemExit("Số từ ngoài khoảng cho phép: sửa truyện rồi chạy lại.")
    if a.only and not 1 <= a.only <= len(FILES):
        raise SystemExit(f"--only phải từ 1 đến {len(FILES)}.")

    # QUY TẮC: hỏi giọng + nền tảng TRƯỚC khi tạo bất kỳ audio nào.
    a.voices_root = a.voices_root
    name, platform, vdir = w.ask_voice_and_platform(Namespace(
        voices_root=a.voices_root, voice_dir=a.voice_dir, voice=a.voice,
        platform=a.platform, yes=a.yes))
    voice = vdir / f"{name}.pt"
    meta = json.loads(voice.with_suffix(".json").read_text(encoding="utf-8"))
    prompt = w.VoiceClonePrompt.load(str(voice))
    out = Path(a.out)
    work = out / "work"
    work.mkdir(parents=True, exist_ok=True)
    model = w.load_model(a.device)
    sr = model.sampling_rate

    todo = [a.only] if a.only else range(1, len(FILES) + 1)
    audio = {i: render_chapter(w, model, prompt, meta["seed"], i, chapters[i - 1], sr, work)
             for i in todo}

    def export(idx_list, with_full):
        # Chuẩn hoá bằng MỘT mức gain chung để âm lượng các chương đồng đều.
        gap = np.zeros(int(CHAPTER_GAP * sr), dtype=np.float32)
        full = []
        for k, i in enumerate(idx_list):
            full += ([gap] if k else []) + [audio[i]]
        full = np.concatenate(full)
        full_wav = work / "full.wav"
        sf.write(full_wav, full, sr)
        loud, _ = measure(full_wav)
        return full_wav, TARGET_LUFS - loud

    if a.only:
        i = a.only
        wav = work / f"ch{i:02d}.wav"
        loud, _ = measure(wav)
        dst = out / FILES[i - 1]
        to_mp3(wav, dst, TARGET_LUFS - loud)
        print(f"Xong chương {i}: {dst} ({mmss(len(audio[i]) / sr)}, "
              f"{count_words(chapters[i - 1]) / (len(audio[i]) / sr / 60):.0f} wpm)")
        return

    idx_list = list(range(1, len(FILES) + 1))
    full_wav, gain = export(idx_list, True)
    total_min = len(sf.read(full_wav, dtype="float32")[0]) / sr / 60
    print(f"Thời lượng thực đo: {total_min:.1f} phút (cho phép {MIN_MIN:.0f}-{MAX_MIN:.0f})")
    if not (MIN_MIN <= total_min <= MAX_MIN):
        raise SystemExit("Thời lượng ngoài 30-45 phút: KHÔNG xuất MP3. "
                         + ("Mở rộng truyện." if total_min < MIN_MIN else "Cắt bớt truyện."))

    lines, report = [], []
    offset = 0.0
    for i in idx_list:
        dur = len(audio[i]) / sr
        lines.append(f"{mmss(offset)} {chapters[i - 1]['title']}")
        offset += dur + CHAPTER_GAP
        wav = work / f"ch{i:02d}.wav"
        to_mp3(wav, out / FILES[i - 1], gain)
    to_mp3(full_wav, out / FULL_NAME, gain)
    (out / "chapters.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (out / "transcript.txt").write_text(
        "\n\n".join(f"{c['title']}\n\n" + "\n\n".join(t for _, t in c["paras"])
                    for c in chapters) + "\n", encoding="utf-8")

    for f in FILES + [FULL_NAME]:
        d, rate, ch, kbps = probe(out / f)
        li, tp = measure(out / f)
        report.append(f"{f}: {mmss(d)} | {kbps} kbps | {rate} Hz | {ch} ch | "
                      f"{li:.1f} LUFS | peak {tp:.1f} dBTP")
    (out / "production_report.txt").write_text(
        f"voice: {name} | platform: {platform}\n"
        f"words: {words} | duration: {total_min:.1f} min | wpm: {words / total_min:.0f}\n"
        f"target: {TARGET_LUFS} LUFS, true peak <= {TARGET_TP} dBTP "
        "(đo lại trên chính file MP3)\n" + "\n".join(report) + "\n", encoding="utf-8")
    print(f"Xong. {out}\n" + "\n".join(report))


if __name__ == "__main__":
    main()
