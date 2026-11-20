#!/usr/bin/env python3
"""Ghép nhạc nền với giọng đọc: nhạc luôn NẰM DƯỚI giọng, tự hạ khi có người nói, chừa chỗ cho lời.

  python scripts/mix_story_music.py voice.mp3 music.wav final.mp3
  python scripts/mix_story_music.py voice.mp3 music.wav final.mp3 --wav --under 15 --duck 7

Quy trình: khoét tần số của nhạc ở vùng giọng nói (EQ) -> đặt nhạc thấp hơn giọng --under dB (lúc im) -> tự hạ thêm --duck dB
khi có giọng (nhạy với từng câu, trả lại từ từ để không "bơm") -> nhạc nhỏ dần vào/ra -> chuẩn hóa -16 LUFS, true peak <= -1 dBTP.
Xuất MP3 320 kbps 44,1 kHz stereo (và WAV 24-bit/48 kHz nếu --wav) + báo cáo kiểm tra tỉ lệ giọng/nhạc.
Nhạc ngắn hơn giọng sẽ được lặp liền mạch.  Cần: numpy, scipy, ffmpeg.
"""
import argparse
import json
import re
import subprocess

import numpy as np
from scipy import signal

SR = 48000


def load(path):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-ac", "2", "-ar", str(SR), "-f", "f32le", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.float32).reshape(-1, 2).copy()


def lufs(x):
    p = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-f", "f32le", "-ar", str(SR), "-ac", "2", "-i", "-",
                        "-af", "loudnorm=I=-16:TP=-1:LRA=11:print_format=json", "-f", "null", "-"],
                       input=x.astype(np.float32).tobytes(), capture_output=True)
    j = json.loads(re.findall(r"\{[^{}]*\}", p.stderr.decode(), re.S)[-1])
    return float(j["input_i"]), float(j["input_tp"])


def peaking(f0, gain_db, q):
    w0 = 2 * np.pi * f0 / SR
    A = 10 ** (gain_db / 40)
    al = np.sin(w0) / (2 * q)
    b = np.array([1 + al * A, -2 * np.cos(w0), 1 - al * A])
    a = np.array([1 + al / A, -2 * np.cos(w0), 1 - al / A])
    return signal.tf2sos(b / a[0], a / a[0])


def carve(x):
    """EQ cho nhạc nền: bỏ trầm sâu, khoét thân giọng (~300 Hz) và độ rõ (2-4 kHz), cắt cao nhẹ."""
    chain = [signal.butter(2, 90, "high", fs=SR, output="sos"), peaking(300, -3.0, 0.7),
             peaking(1100, -1.5, 0.8), peaking(2800, -5.0, 0.7), signal.butter(2, 6500, "low", fs=SR, output="sos")]
    y = x.copy()
    for sos in chain:
        y = signal.sosfilt(sos, y, axis=0)
    return y.astype(np.float32)


def speech_gate(v):
    """1 khi có giọng nói, 0 khi im (theo từng khung 10 ms, làm mượt)."""
    m = v.mean(axis=1)
    sos = signal.butter(2, [120, 3500], "band", fs=SR, output="sos")
    b = signal.sosfilt(sos, m)
    hop = SR // 100
    n = len(b) // hop
    rms = np.sqrt((b[:n * hop].reshape(n, hop) ** 2).mean(axis=1)) + 1e-9
    db = 20 * np.log10(rms)
    thr = np.percentile(db, 98) - 32
    on = (db > thr).astype(np.float32)
    on = np.convolve(on, np.ones(35), "same").clip(0, 1)  # giữ 0,35 s qua các kẽ từ
    out = np.zeros(n, np.float32)
    for i in range(n):  # xuống nhanh (0,12 s), lên chậm (0,9 s)
        prev = out[i - 1] if i else 0.0
        k = 1 - np.exp(-0.01 / (0.12 if on[i] > prev else 0.9))
        out[i] = prev + (on[i] - prev) * k
    return np.interp(np.arange(len(v)) / hop, np.arange(n), out).astype(np.float32), on


def loop_to(m, n):
    fade = int(8 * SR)
    if len(m) >= n:
        return m[:n]
    step = len(m) - fade
    out = np.zeros((step * int(np.ceil((n - len(m)) / step) + 1) + fade, 2), np.float32)
    for i in range(int(np.ceil((n - len(m)) / step)) + 1):
        out[i * step:i * step + len(m)] += m * np.concatenate(
            [np.sin(np.linspace(0, np.pi / 2, fade)) ** 2 if i else np.ones(fade),
             np.ones(len(m) - 2 * fade),
             np.cos(np.linspace(0, np.pi / 2, fade)) ** 2])[:, None]
    return out[:n]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("voice")
    ap.add_argument("music")
    ap.add_argument("out")
    ap.add_argument("--under", type=float, default=14.0, help="nhạc thấp hơn giọng bao nhiêu dB khi im (mặc định 14)")
    ap.add_argument("--duck", type=float, default=6.0, help="hạ thêm bao nhiêu dB khi có giọng (mặc định 6)")
    ap.add_argument("--music-start", type=float, default=0.0, help="bắt đầu lấy nhạc từ giây thứ mấy")
    ap.add_argument("--wav", action="store_true", help="xuất thêm WAV 24-bit/48 kHz")
    a = ap.parse_args()

    v = load(a.voice)
    m = load(a.music)[int(a.music_start * SR):]
    n = len(v)
    m = loop_to(m, n)
    vl, _ = lufs(v)
    m = carve(m)
    ml, _ = lufs(m)
    gate, on = speech_gate(v)
    duck_db = -a.duck * gate
    gain_db = (vl - a.under) - ml + duck_db           # dB theo từng mẫu
    mg = m * (10 ** (gain_db / 20))[:, None].astype(np.float32)
    # nhạc vào chậm 3 s, ra 10 s cuối
    fi, fo = int(3 * SR), int(min(10 * SR, n // 3))
    mg[:fi] *= (np.sin(np.linspace(0, np.pi / 2, fi)) ** 2)[:, None]
    mg[-fo:] *= (np.cos(np.linspace(0, np.pi / 2, fo)) ** 2)[:, None]
    mix = v + mg
    ml2, _ = lufs(mix)
    mix *= 10 ** ((-16.0 - ml2) / 20)
    # báo cáo trước khi xuất
    sp = gate > 0.6
    vs = mix * 0  # chỉ để rõ ý
    vscale = 10 ** ((-16.0 - ml2) / 20)
    vr = np.sqrt((v[sp] ** 2).mean()) * vscale
    mr = np.sqrt((mg[sp] ** 2).mean()) * vscale
    pause = gate < 0.1
    mpause = np.sqrt((mg[pause] ** 2).mean()) * vscale if pause.any() else float("nan")
    def band(x, lo, hi):
        sos = signal.butter(4, [lo, hi], "band", fs=SR, output="sos")
        return np.sqrt((signal.sosfilt(sos, x[sp][:SR * 60], axis=0) ** 2).mean() + 1e-12)
    ratio_all = 20 * np.log10(vr / mr)
    ratio_pres = 20 * np.log10(band(v * vscale, 1500, 4000) / band(mg, 1500, 4000))
    ff = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "f32le", "-ar", str(SR), "-ac", "2", "-i", "-"]
    af = "alimiter=limit=0.84:level=disabled"
    data = mix.astype(np.float32).tobytes()
    subprocess.run([*ff, "-af", af + ",aresample=44100", "-b:a", "320k", a.out], input=data, check=True)
    if a.wav:
        subprocess.run([*ff, "-af", af, "-c:a", "pcm_s24le", a.out.rsplit(".", 1)[0] + ".wav"], input=data, check=True)
    fl, ftp = lufs(load(a.out))
    print(f"Kết quả: {n / SR / 60:.2f} phút | {fl:.1f} LUFS | true peak {ftp:.1f} dBTP")
    print(f"Tỉ lệ giọng/nhạc khi có giọng: {ratio_all:.1f} dB (toàn dải), {ratio_pres:.1f} dB (vùng 1,5-4 kHz) | "
          f"nhạc lúc im thấp hơn giọng {20 * np.log10(vr / mpause):.1f} dB" if not np.isnan(mpause) else
          f"Tỉ lệ giọng/nhạc khi có giọng: {ratio_all:.1f} dB")


if __name__ == "__main__":
    main()
