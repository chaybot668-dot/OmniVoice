#!/usr/bin/env python3
"""Nhạc nền cinematic ambient cho kênh HER SIDE OF THE STORY, TỔNG HỢP HOÀN TOÀN BẰNG CODE.

Sáng tác gốc (không mẫu có sẵn, không giai điệu có sẵn), 5 giai đoạn cảm xúc theo đúng prompt:
  1 Mở đầu (piano nhẹ) -> 2 Nghi ngờ/bí mật (dây trầm, căng nhẹ) -> 3 Phản bội/đau lòng (cello sâu)
  -> 4 Phơi bày/đối đầu (dây dâng dần, kiềm chế) -> 5 Chấp nhận/mạnh mẽ (piano ấm, hóa giải).
72 BPM, 4/4, D thứ. Piano thưa ở quãng trung-trầm, cắt cao, khoét nhẹ vùng giọng nói để nhường lời đọc.

  python scripts/make_music.py out_dir                    # 1 bản ~6,7 phút
  python scripts/make_music.py out_dir --minutes 30       # lặp liền mạch (chồng đuôi/đầu) thành 30 phút
Xuất: WAV PCM 24-bit/48 kHz + MP3 320 kbps, khoảng -20 LUFS (để dưới giọng đọc), true peak <= -1 dBTP.
Cần: numpy, scipy, ffmpeg.
"""
import argparse
import json
import re
import subprocess
from pathlib import Path

import numpy as np
from scipy import signal

SR = 48000
BPM = 72
BEAT = 60 / BPM
BAR = 4 * BEAT
CH = {  # cao độ MIDI của từng hợp âm (đoạn trầm)
    "Dm": [50, 53, 57], "Bb": [46, 50, 53], "Gm": [43, 46, 50], "A": [45, 49, 52], "F": [41, 45, 48],
    "Eb": [39, 43, 46], "Dm7": [50, 53, 57, 60], "Bbmaj7": [46, 50, 53, 57], "Asus": [45, 50, 52],
}
STAGES = [
    ["Dm", "Bbmaj7", "Gm", "Dm", "Bbmaj7", "Asus"],
    ["Dm", "Gm", "Bb", "A", "Dm", "Gm"],
    ["Gm", "Eb", "Bb", "F", "Gm", "A"],
    ["Dm", "A", "Bb", "Gm", "A", "A"],
    ["Bb", "F", "Gm", "Dm7", "Bb", "Dm"],
]
BARS_PER_CHORD = 4
# mức từng lớp theo giai đoạn: pad, piano, cello, strings, pulse
LEVELS = np.array([
    [0.85, 1.00, 0.00, 0.00, 0.00],
    [0.95, 0.70, 0.22, 0.35, 0.30],
    [0.95, 0.90, 0.80, 0.30, 0.00],
    [1.00, 0.50, 0.60, 0.75, 0.45],
    [0.90, 1.00, 0.40, 0.30, 0.00],
])


def hz(m):
    return 440.0 * 2 ** ((m - 69) / 12)


def env_adsr(n, att, rel, sr=SR):
    t = np.arange(n) / sr
    e = np.minimum(1, t / att) ** 1.5
    tail = np.minimum(1, (n / sr - t) / rel)
    return (e * np.clip(tail, 0, 1)).astype(np.float32)


def lp(x, fc, order=2):
    sos = signal.butter(order, fc, "low", fs=SR, output="sos")
    return signal.sosfilt(sos, x).astype(np.float32)


def add(buf, start, x):
    i = int(start * SR)
    j = min(len(buf), i + len(x))
    if j > i:
        buf[i:j] += x[:j - i]


def render(seed=5):
    rng = np.random.default_rng(seed)
    nchords = sum(len(s) for s in STAGES)
    total = nchords * BARS_PER_CHORD * BAR
    N = int((total + 14) * SR)
    pad = np.zeros(N, np.float32)
    piano = np.zeros(N, np.float32)
    cello = np.zeros(N, np.float32)
    strings = np.zeros(N, np.float32)
    pulse = np.zeros(N, np.float32)
    seg = BARS_PER_CHORD * BAR
    ci = 0
    for si, stage in enumerate(STAGES):
        for name in stage:
            t0 = ci * seg
            notes = CH[name]
            n = int((seg + 6) * SR)
            t = np.arange(n, dtype=np.float32) / SR
            # --- pad: tam âm ấm, lệch cao độ nhẹ, chậm vào/ra
            p = np.zeros(n, np.float32)
            for m, wgt in [(n_ + 12, 1.0) for n_ in notes] + [(notes[0], 0.45)]:
                for det in (-0.0012, 0.0, 0.0012):
                    f = hz(m) * (1 + det)
                    for k, a in ((1, 1.0), (2, 0.35), (3, 0.12)):
                        p += wgt * a * np.sin(2 * np.pi * f * k * t + rng.uniform(0, 6.28)).astype(np.float32)
            p *= env_adsr(n, 2.8, 3.5) / (len(notes) * 4)
            add(pad, t0, p)
            # --- cello: nốt dài ở gam trầm, rung nhẹ
            c = np.zeros(n, np.float32)
            f0 = hz(notes[0])
            vib = 1 + 0.0035 * np.sin(2 * np.pi * 5.2 * t) * np.minimum(1, t / 2.5)
            ph = 2 * np.pi * np.cumsum(f0 * vib) / SR
            for k in range(1, 15):
                c += (1.0 / k) * np.sin(k * ph).astype(np.float32)
            c *= env_adsr(n, 1.4, 3.0) * 0.12
            add(cello, t0, c)
            # --- dây: 3 nốt hợp âm cao hơn một quãng tám, dâng chậm
            s = np.zeros(n, np.float32)
            for m in notes[:3]:
                for det in (-0.004, 0.0, 0.004):
                    f = hz(m + 12) * (1 + det)
                    for k in range(1, 9):
                        s += (1.0 / k) * np.sin(2 * np.pi * f * k * t + rng.uniform(0, 6.28)).astype(np.float32)
            sw = np.minimum(1, t / 6.5) ** 2 * np.clip((seg + 5.5 - t) / 5.5, 0, 1)
            s *= sw.astype(np.float32) * 0.045
            add(strings, t0, s)
            # --- piano nỉ: thưa, quãng trung-trầm, không trùng mẫu
            density = [0.62, 0.45, 0.55, 0.30, 0.60][si]
            beats = BARS_PER_CHORD * 4
            last = None
            for b in range(0, beats, 2):
                if rng.random() > density:
                    continue
                cand = [m + 12 * o for m in notes for o in (1, 2) if 55 <= m + 12 * o <= 79]
                m = int(rng.choice([c_ for c_ in cand if c_ != last]))
                last = m
                dur = rng.uniform(3.5, 6.0)
                nn = int(dur * SR)
                tt = np.arange(nn, dtype=np.float32) / SR
                f = hz(m)
                v = np.zeros(nn, np.float32)
                for k in range(1, 11):
                    inh = k * (1 + 0.0004 * k * k)
                    a = k ** -1.15 * np.exp(-0.16 * k)
                    tau = 2.4 / (1 + 0.45 * k)
                    v += a * np.exp(-tt / tau) * np.sin(2 * np.pi * f * inh * tt)
                v *= np.minimum(1, tt / 0.006) * rng.uniform(0.5, 0.85) * 0.42
                add(piano, t0 + b * BEAT + rng.uniform(0, 0.05), v)
            # --- nhịp trầm rất nhẹ (chỉ ở giai đoạn có)
            if LEVELS[si, 4] > 0:
                for b in range(0, beats, 2):
                    tt = np.arange(int(0.9 * SR), dtype=np.float32) / SR
                    k_ = np.sin(2 * np.pi * 49 * tt * (1 - 0.25 * tt)) * np.exp(-tt / 0.28) * 0.22
                    add(pulse, t0 + b * BEAT, k_.astype(np.float32))
            ci += 1
    piano = lp(piano, 2800)
    cello = lp(cello, 850)
    strings = lp(strings, 1800)
    pad = signal.sosfilt(signal.butter(2, 95, 'high', fs=SR, output='sos'), lp(pad, 1500)).astype(np.float32)
    pulse = lp(pulse, 120)
    # mức từng lớp theo thời gian (chuyển giai đoạn mượt 12 giây)
    sl = 20 * BAR * 4 / 4  # độ dài 1 giai đoạn (24 bar)
    sl = 6 * BARS_PER_CHORD * BAR
    tx = np.arange(N) / SR
    knots_t, knots = [0], [LEVELS[0]]
    for i in range(1, 5):
        knots_t += [i * sl - 6, i * sl + 6]
        knots += [LEVELS[i - 1], LEVELS[i]]
    knots_t.append(N / SR)
    knots.append(LEVELS[4])
    knots = np.array(knots)
    lev = [np.interp(tx, knots_t, knots[:, j]).astype(np.float32) for j in range(5)]
    # stereo: pad/dây mở rộng bằng trễ rất ngắn, piano giữa, cello hơi lệch
    def pan(x, l, r):
        return x * l, x * r
    L = np.zeros(N, np.float32)
    R = np.zeros(N, np.float32)
    for x, lv, gl, gr, delay in ((pad, lev[0], 0.9, 0.9, 0.011), (strings, lev[3], 0.85, 0.85, 0.017)):
        d = int(delay * SR)
        xs = x * lv
        L += xs * gl
        R[d:] += xs[:-d] * gr
    for x, lv, gl, gr in ((piano, lev[1], 0.95, 0.80), (cello, lev[2], 0.80, 0.95), (pulse, lev[4], 0.7, 0.7)):
        L += x * lv * gl
        R += x * lv * gr
    # hồi âm phòng lớn
    rt = 3.4
    nir = int(rt * SR)
    tir = np.arange(nir) / SR
    out = []
    for ch in (L, R):
        ir = rng.standard_normal(nir).astype(np.float32) * np.exp(-6.9 * tir / rt).astype(np.float32)
        ir = lp(ir, 3500)
        ir[:int(0.02 * SR)] *= np.linspace(0, 1, int(0.02 * SR), dtype=np.float32)
        wet = signal.fftconvolve(ch, ir / np.sqrt((ir ** 2).sum()) * 0.9, mode="full")[:N].astype(np.float32)
        out.append(ch * 0.62 + wet * 0.55)
    L, R = out
    # EQ: bỏ rất trầm/rất cao, khoét nhẹ 1,5-3,5 kHz cho giọng đọc
    hp = signal.butter(2, 38, "high", fs=SR, output="sos")
    lpf = signal.butter(2, 8000, "low", fs=SR, output="sos")
    w0 = 2.4e3 / SR * 2 * np.pi
    A = 10 ** (-3.5 / 40)
    alpha = np.sin(w0) / (2 * 0.8)
    b = np.array([1 + alpha * A, -2 * np.cos(w0), 1 - alpha * A])
    a_ = np.array([1 + alpha / A, -2 * np.cos(w0), 1 - alpha / A])
    notch = signal.tf2sos(b / a_[0], a_ / a_[0])
    stereo = []
    for ch in (L, R):
        for sos in (hp, lpf, notch):
            ch = signal.sosfilt(sos, ch)
        stereo.append(ch.astype(np.float32))
    x = np.stack(stereo, axis=1)
    keep = int(total * SR + 8 * SR)  # đuôi hồi âm 8 s
    x = x[:keep]
    FADE = int(8 * SR)
    x[:FADE] *= (np.sin(np.linspace(0, np.pi / 2, FADE)) ** 2)[:, None].astype(np.float32)
    x[-FADE:] *= (np.cos(np.linspace(0, np.pi / 2, FADE)) ** 2)[:, None].astype(np.float32)
    return x


def extend(x, minutes):
    FADE = int(8 * SR)
    target = int(minutes * 60 * SR)
    step = len(x) - FADE  # chồng đuôi lên đầu -> chuyển liền mạch
    n = int(np.ceil((target - len(x)) / step)) + 1
    out = np.zeros((step * (n - 1) + len(x), 2), np.float32)
    for i in range(n):
        out[i * step:i * step + len(x)] += x
    out = out[:target]
    out[-FADE:] *= (np.cos(np.linspace(0, np.pi / 2, FADE)) ** 2)[:, None]
    return out


def ff(*args):
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *args], check=True)


def measure(path):
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-af",
                        "loudnorm=I=-20:TP=-1:LRA=11:print_format=json", "-f", "null", "-"],
                       capture_output=True, text=True)
    j = json.loads(re.findall(r"\{[^{}]*\}", r.stderr, re.S)[-1])
    return float(j["input_i"]), float(j["input_tp"]), float(j["input_lra"])


def main():
    import soundfile as sf
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("out_dir")
    ap.add_argument("--minutes", type=float, help="lặp liền mạch tới độ dài này")
    ap.add_argument("--target-lufs", type=float, default=-20.0)
    ap.add_argument("--seed", type=int, default=5)
    a = ap.parse_args()
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    x = render(a.seed)
    if a.minutes:
        x = extend(x, a.minutes)
    raw = out / "_raw.wav"
    sf.write(raw, x, SR, subtype="FLOAT")
    loud, tp, lra = measure(raw)
    gain = a.target_lufs - loud
    name = "HER_SIDE_OF_THE_STORY_theme" + (f"_{int(a.minutes)}min" if a.minutes else "")
    chain = f"volume={gain:.2f}dB,alimiter=limit=0.84:level=disabled"
    ff("-i", str(raw), "-af", chain, "-c:a", "pcm_s24le", "-ar", "48000", str(out / f"{name}.wav"))
    ff("-i", str(out / f"{name}.wav"), "-b:a", "320k", "-ar", "48000", str(out / f"{name}.mp3"))
    raw.unlink()
    li, tpk, lr = measure(out / f"{name}.mp3")
    dur = len(x) / SR
    rep = (f"{name}: {dur / 60:.2f} phút | WAV PCM 24-bit/48 kHz + MP3 320 kbps | "
           f"{li:.1f} LUFS | true peak {tpk:.1f} dBTP | LRA {lr:.1f} LU\n"
           "Nhạc tổng hợp bằng code (không mẫu, không giai điệu có sẵn). Chưa được nghe thử bởi người.\n")
    (out / f"{name}_report.txt").write_text(rep, encoding="utf-8")
    print(rep)


if __name__ == "__main__":
    main()
