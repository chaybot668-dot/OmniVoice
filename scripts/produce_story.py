#!/usr/bin/env python3
"""Sản xuất audiobook nhiều chương từ stories/<tên>/story.txt bằng giọng đã lưu.

Quy tắc bắt buộc (giống `narrate`): phải chọn GIỌNG và NỀN TẢNG trước khi tạo audio.
Quy tắc thời lượng: tổng 30-60 phút, 4.500-6.000 từ. Ngoài khoảng đó -> KHÔNG xuất MP3.

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

FULL_NAME = "HER_SIDE_OF_THE_STORY_FULL_AUDIO.mp3"
MIN_WORDS, MAX_WORDS = 4500, 6000
MIN_MIN, MAX_MIN = 20.0, 60.0  # mục tiêu 30-35 phút; dưới 30 chỉ CẢNH BÁO và báo đúng thời lượng thật (quy tắc V2.0)
CHUNK_GAP = 0.4  # giây, giữa các câu trong cùng đoạn (0.3-0.5)
PARA_GAP = 0.9  # giây, giữa các đoạn (0.7-1.2)
CHAPTER_GAP = 0.8  # giây, giữa các chương trong file ghép
TARGET_LUFS, TARGET_TP = -16.0, -1.0


def chapter_files(chapters):
    names = []
    for i, c in enumerate(chapters, 1):
        t = re.sub(r"^CHAPTER\s+\d+\s*[—-]\s*", "", c["title"], flags=re.I)
        slug = "_".join(re.findall(r"[A-Za-z0-9]+", t.replace("'", ""))).title()
        names.append(f"{i:02d}_{slug}.mp3")
    return names


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


def _norm(text):
    text = re.sub(r"[^a-z0-9' ]+", " ", text.lower().replace("-", " ").replace("’", "'"))
    return text.split()


def find_repeats(words):
    """Cụm 2-8 từ lặp liền nhau (vd 'I looked at him I looked at him')."""
    hits = []
    for n in range(2, 9):
        for i in range(len(words) - 2 * n + 1):
            if words[i:i + n] == words[i + n:i + 2 * n]:
                hits.append(" ".join(words[i:i + n]))
    return hits


def qc_check(model, audio, sr, text, speed, min_sim=0.82):
    """Kiểm 1 câu: nhận dạng lại bằng Whisper rồi so với kịch bản + tìm lặp/cắt/vỡ tiếng."""
    import difflib
    flags = []
    exp = _norm(text)
    asr = model.transcribe((np.asarray(audio, dtype=np.float32), sr))
    got = _norm(asr)
    sim = difflib.SequenceMatcher(None, exp, got).ratio() if exp else 1.0
    if sim < min_sim:
        flags.append(f"lệch lời ({sim:.2f})")
    if len(got) > len(exp) * 1.25 + 2:
        flags.append("thừa chữ (có thể lặp)")
    if len(got) < len(exp) * 0.75 - 2:
        flags.append("thiếu chữ (có thể bị cắt)")
    extra = [r for r in find_repeats(got) if r not in " ".join(exp)]
    if extra:
        flags.append("lặp cụm: " + "; ".join(sorted(set(extra))[:3]))
    dur = len(audio) / sr
    per_word = dur / max(1, len(exp))
    if per_word > 1.0 or per_word < 0.22:
        flags.append(f"tốc độ bất thường ({per_word:.2f} s/từ)")
    a = np.abs(np.asarray(audio, dtype=np.float32))
    if a.size and (a >= 0.999).mean() > 0.002:
        flags.append("vỡ tiếng (clipping)")
    frame = int(0.05 * sr)
    if a.size > frame * 4:
        rms = np.sqrt((a[:a.size // frame * frame].reshape(-1, frame) ** 2).mean(axis=1))
        quiet = rms < 0.003
        run = best = 0
        for q in quiet[int(0.3 / 0.05):-int(0.3 / 0.05)]:
            run = run + 1 if q else 0
            best = max(best, run)
        if best * 0.05 > 1.3:
            flags.append(f"khoảng lặng giữa câu {best * 0.05:.1f}s")
    return dict(ok=not flags, sim=sim, flags=flags, asr=asr)


def render_chapter(w, model, prompt, seed, idx, ch, sr, work, scale, qc=False, seed_off=0, qlog=None):
    cache = work / f"ch{idx:02d}_s{scale:.2f}_o{seed_off}.wav"
    if cache.exists():
        logging.info("Chương %d: dùng bản đã đọc (%s)", idx, cache)
        return sf.read(cache, dtype="float32")[0], 0
    parts, fails = [], 0
    for i, (mode, text) in enumerate(ch["paras"], 1):
        speed = w.MODE_SPEED.get(mode, w.DEFAULT_SPEED) * scale
        chunks = w.split_chunks(text)
        for j, chunk in enumerate(chunks):
            logging.info("Chương %d - đoạn %d/%d - câu %d/%d", idx, i, len(ch["paras"]),
                         j + 1, len(chunks))
            best = None
            for att in range(3 if qc else 1):
                sd = seed + seed_off * 100003 + idx * 1000 + i * 10 + j + att * 7919
                au = np.asarray(w.gen(model, chunk, sd, voice_clone_prompt=prompt, speed=speed),
                                dtype=np.float32).reshape(-1)
                if not qc:
                    best = (au, None)
                    break
                res = qc_check(model, au, sr, chunk, speed)
                if best is None or (res["ok"], res["sim"]) > (best[1]["ok"], best[1]["sim"]):
                    best = (au, res)
                if res["ok"]:
                    break
                logging.info("   QC lỗi lần %d: %s -> đọc lại", att + 1, "; ".join(res["flags"]))
            au, res = best
            if res is not None:
                if not res["ok"]:
                    fails += 1
                if qlog is not None:
                    qlog.append(f"ch{idx} đoạn{i} câu{j + 1}: {'OK' if res['ok'] else 'LỖI'} "
                                f"sim={res['sim']:.2f} {'; '.join(res['flags'])}\n    chữ: {chunk[:90]}")
            parts.append(au)
            gap = PARA_GAP if j == len(chunks) - 1 else CHUNK_GAP
            parts.append(np.zeros(int(gap * sr), dtype=np.float32))
    audio = np.concatenate(parts[:-1])  # bỏ khoảng lặng cuối chương
    if fails == 0:
        sf.write(cache, audio, sr)  # chỉ lưu cache khi chương đạt QC; chương lỗi sẽ đọc lại
    else:
        sf.write(work / f"ch{idx:02d}_FAIL.wav", audio, sr)
    return audio, fails


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
       "-ac", "2", "-b:a", "320k", str(dst))


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
    ap.add_argument("--speed-scale", type=float, default=1.0,
                    help="nhân tốc độ đọc (vd 0.9 = chậm 10%%) để chỉnh số từ/phút và tổng thời lượng")
    ap.add_argument("--single", action="store_true", help="chỉ xuất 1 file MP3 liền mạch (không xuất từng chương)")
    ap.add_argument("--no-qc", action="store_true", help="bỏ bước kiểm lỗi lặp/cắt/lệch lời bằng Whisper")
    ap.add_argument("--seed-offset", type=int, default=0,
                    help="đổi bộ số ngẫu nhiên để đọc lại các chương chưa đạt QC")
    ap.add_argument("--device")
    a = ap.parse_args()
    if not shutil.which("ffmpeg"):
        raise SystemExit("Cần ffmpeg để xuất MP3 và đo âm lượng.")

    chapters = parse_story(a.story, w)
    FILES = chapter_files(chapters)
    words = sum(count_words(c) for c in chapters)
    print(f"Số từ lời đọc: {words} (cho phép {MIN_WORDS}-{MAX_WORDS})")
    if not (MIN_WORDS <= words <= MAX_WORDS):
        print(f"CẢNH BÁO: số từ ngoài {MIN_WORDS}-{MAX_WORDS}. Luật cứng là thời lượng thực đo 30-60 phút.")
    if a.only and not 1 <= a.only <= len(FILES):
        raise SystemExit(f"--only phải từ 1 đến {len(FILES)}.")

    # QUY TẮC: hỏi giọng + nền tảng TRƯỚC khi tạo bất kỳ audio nào.
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

    qc = not a.no_qc
    if qc:
        model.load_asr_model()  # Whisper, tải lần đầu ~1,6 GB
    todo = [a.only] if a.only else range(1, len(FILES) + 1)
    audio, qlog, total_fails = {}, [], 0
    for i in todo:
        audio[i], nf = render_chapter(w, model, prompt, meta["seed"], i, chapters[i - 1], sr, work,
                                      a.speed_scale, qc, a.seed_offset, qlog)
        total_fails += nf
    if qc:
        head = f"QC Whisper: {len(qlog)} câu kiểm, {total_fails} câu LỖI sau 3 lần đọc\n"
        (out / "qc_report.txt").write_text(head + "\n".join(qlog) + "\n", encoding="utf-8")
        print(head.strip() + f" (chi tiết: {out / 'qc_report.txt'})")
        if total_fails:
            raise SystemExit("Còn câu chưa đạt QC nên KHÔNG xuất MP3. Chạy lại với --seed-offset "
                             f"{a.seed_offset + 1} (các chương đã đạt được giữ nguyên, chỉ đọc lại chương lỗi).")
    cpath = lambda i: work / f"ch{i:02d}_s{a.speed_scale:.2f}_o{a.seed_offset}.wav"

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
        wav = cpath(i)
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
    if total_min < 30:
        print("CẢNH BÁO: dưới mục tiêu 30 phút. Quy tắc V2.0: báo đúng thời lượng thật, KHÔNG thêm nội dung lặp để kéo dài.")
    if not (MIN_MIN <= total_min <= MAX_MIN):
        raise SystemExit("Thời lượng ngoài 30-60 phút: KHÔNG xuất MP3. "
                         + ("Mở rộng truyện." if total_min < MIN_MIN else "Cắt bớt truyện."))

    lines, report = [], []
    offset = 0.0
    for i in idx_list:
        dur = len(audio[i]) / sr
        lines.append(f"{mmss(offset)} {chapters[i - 1]['title']}")
        offset += dur + CHAPTER_GAP
        wav = cpath(i)
        if not a.single:
            to_mp3(wav, out / FILES[i - 1], gain)
    to_mp3(full_wav, out / FULL_NAME, gain)
    (out / "chapters.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (out / "transcript.txt").write_text(
        "\n\n".join(f"{c['title']}\n\n" + "\n\n".join(t for _, t in c["paras"])
                    for c in chapters) + "\n", encoding="utf-8")

    for f in ([FULL_NAME] if a.single else FILES + [FULL_NAME]):
        d, rate, ch, kbps = probe(out / f)
        li, tp = measure(out / f)
        report.append(f"{f}: {mmss(d)} | {kbps} kbps | {rate} Hz | {ch} ch | "
                      f"{li:.1f} LUFS | peak {tp:.1f} dBTP")
    (out / "production_report.txt").write_text(
        f"voice: {name} | platform: {platform}\n"
        f"words: {words} | duration: {total_min:.1f} min | wpm: {words / total_min:.0f}\n"
        "kiểm nghe bằng tai: CHƯA THỰC HIỆN (cần người nghe); đã đo âm lượng/đỉnh trên file MP3; QC Whisper: "
        + ("tắt" if a.no_qc else f"bật, {total_fails} câu lỗi") + "\n"
        f"target: {TARGET_LUFS} LUFS, true peak <= {TARGET_TP} dBTP "
        "(đo lại trên chính file MP3)\n" + "\n".join(report) + "\n", encoding="utf-8")
    print(f"Xong. {out}\n" + "\n".join(report))


if __name__ == "__main__":
    main()
