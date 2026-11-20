#!/usr/bin/env python3
"""Thanh âm thanh nhảy theo giọng đọc (kiểu podcast chuyên nghiệp), NỀN TRONG SUỐT.

  python scripts/make_audio_bars.py audio.mp3 bars.mov      # ProRes 4444 + alpha (CapCut/Premiere/DaVinci)
  python scripts/make_audio_bars.py audio.mp3 bars.webm     # VP9 + alpha (nhẹ hơn)
  python scripts/make_audio_bars.py audio.mp3 bars.mp4      # nền ĐEN (dùng chế độ hòa trộn Screen/Lighten)
  python scripts/make_audio_bars.py audio.mp3 final.mp4 --scene loop.mp4   # ghép thẳng lên video nền + âm thanh

Thanh bám theo CHÍNH file âm thanh nên khớp giọng đọc.
  python scripts/make_audio_bars.py synthetic bars.webm --loop-seconds 60   # clip minh họa LẶP LIỀN MẠCH, không cần audio
 Mặc định KHÔNG kèm âm thanh (--with-audio để kèm).
Màu: --color (thân) và --accent (đầu thanh). Nền sáng: --color 1B1B1B --accent 555555.
"""
import argparse
import subprocess

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

FPS = 24
SR = 22050


def hex2rgb(h):
    h = h.lstrip("#")
    return np.array([int(h[i:i + 2], 16) for i in (0, 2, 4)], dtype=np.float32)


def read_audio(path):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.float32)


def analyse(x, nbands):
    n = len(x) // SR * FPS + FPS
    hop = SR / FPS
    win = 2048
    hann = np.hanning(win).astype(np.float32)
    freqs = np.fft.rfftfreq(win, 1 / SR)
    edges = np.geomspace(100, 5000, nbands + 1)
    L = np.zeros(n, np.float32)
    B = np.zeros((n, nbands), np.float32)
    for f in range(n):
        s = int(f * hop)
        seg = x[s:s + win]
        if len(seg) < win:
            seg = np.pad(seg, (0, win - len(seg)))
        L[f] = np.sqrt((seg[:int(hop * 1.5)] ** 2).mean()) if len(seg) else 0
        sp = np.abs(np.fft.rfft(seg * hann))
        for b in range(nbands):
            m = (freqs >= edges[b]) & (freqs < edges[b + 1])
            B[f, b] = sp[m].mean() if m.any() else 0
    L = np.log1p(L * 60)
    L = np.clip(L / (np.percentile(L, 95) + 1e-6), 0, 1.2)
    B = np.log1p(B * 40)
    B = np.clip(B / (np.percentile(B, 95, axis=0) + 1e-6), 0, 1.2)
    return L, B


def synthetic(N, nbands, seed):
    """Tín hiệu giả giống giọng nói nhưng TUẦN HOÀN theo N khung -> lặp liền mạch."""
    rng = np.random.default_rng(seed)
    env = np.zeros(N, np.float32)
    t = 0.0
    while t < N:
        w = int(rng.uniform(0.15, 0.45) * FPS) + 3
        amp = rng.uniform(0.35, 1.0)
        idx = (np.arange(w) + int(t)) % N          # vòng quanh -> không có mối nối
        env[idx] = np.maximum(env[idx], amp * np.hanning(w))
        t += w + rng.uniform(0.0, 0.18) * FPS + (rng.uniform(0.5, 1.1) * FPS if rng.random() < 0.12 else 0)
    L = np.clip(env / (np.percentile(env, 95) + 1e-6), 0, 1.15).astype(np.float32)
    ph = np.arange(N) / N * 2 * np.pi
    B = np.zeros((N, nbands), np.float32)
    for b in range(nbands):
        mod = sum(np.sin(int(rng.integers(20, 140)) * ph + rng.uniform(0, 6.28)) * rng.uniform(0.1, 0.25)
                  for _ in range(3))
        B[:, b] = np.clip(L * (0.78 + mod), 0, 1.2)
    return L, B


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("audio")
    ap.add_argument("out")
    ap.add_argument("--bars", type=int, default=49)
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--height", type=int, default=260)
    ap.add_argument("--bar-w", type=int, default=7)
    ap.add_argument("--gap", type=int, default=10)
    ap.add_argument("--color", default="F4E9D8", help="màu thân thanh (hex)")
    ap.add_argument("--accent", default="FFC978", help="màu đầu thanh (hex)")
    ap.add_argument("--glow", type=float, default=0.55, help="độ sáng viền phát sáng (0 = tắt)")
    ap.add_argument("--loop-seconds", type=int, default=60, help="chế độ synthetic: độ dài 1 vòng lặp liền mạch")
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--with-audio", action="store_true")
    ap.add_argument("--scene", help="video nền để ghép lên (lặp theo độ dài audio)")
    ap.add_argument("--bottom", type=int, default=70)
    ap.add_argument("--limit", type=float, help="chỉ làm N giây đầu")
    a = ap.parse_args()

    syn = a.audio == "synthetic"
    cols = a.bars | 1
    centre = cols // 2
    nb = centre + 1
    if syn:
        dur = float(a.loop_seconds)
        N = int(dur * FPS)
        L, B = synthetic(N, nb, a.seed)
        a.with_audio = False
        if a.scene:
            raise SystemExit("--scene cần audio thật")
    else:
        x = read_audio(a.audio)
        dur = len(x) / SR
        if a.limit:
            dur = min(dur, a.limit)
        N = int(dur * FPS)
        L, B = analyse(x[:int(dur * SR) + SR], nb)
        L, B = L[:N], B[:N]

    # mô phỏng lò xo: lên nhanh, xuống êm -> chuyển động mượt, tự nhiên
    def smooth(v, up=0.7, down=0.16):
        out = np.zeros_like(v)
        for f in range(len(v)):
            prev = out[f - 1] if f else np.zeros_like(v[0])
            out[f] = np.where(v[f] > prev, prev + (v[f] - prev) * up, prev + (v[f] - prev) * down)
        return out
    if syn:  # chạy 2 vòng rồi lấy vòng sau: trạng thái lò xo khớp ở mối nối
        Ls = smooth(np.tile(L, 2)[:, None])[N:, 0]
        Bs = smooth(np.tile(B, (2, 1)))[N:]
    else:
        Ls = smooth(L[:, None])[:, 0]
        Bs = smooth(B)

    W, H, SS = a.width, a.height, 2
    total = cols * a.bar_w + (cols - 1) * a.gap
    x0 = (W - total) // 2
    body = hex2rgb(a.color)
    accent = hex2rgb(a.accent)
    minh, maxh = a.bar_w * 1.2, H * 0.9
    # đường bao: giữa cao nhất, hai mép thấp dần (hình thấu kính gọn gàng)
    env = np.array([0.38 + 0.62 * np.cos(np.pi / 2 * abs(i - centre) / (centre + 0.5)) ** 1.2 for i in range(cols)])
    # gradient dọc cho từng thanh
    gy = np.linspace(0, 1, H * SS, dtype=np.float32)[:, None]
    master = a.out if a.out.endswith(".mov") else "/tmp/_bars_master.mov"
    p = subprocess.Popen(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{W}x{H}",
         "-r", str(FPS), "-i", "-", "-c:v", "prores_ks", "-profile:v", "4444", "-pix_fmt", "yuva444p10le",
         "-vendor", "apl0", master], stdin=subprocess.PIPE)
    wob_cycles = max(1, round(N / (2 * np.pi * 6)))  # số nguyên chu kỳ/vòng -> tuần hoàn
    for f in range(N):
        mask = Image.new("L", (W * SS, H * SS), 0)
        d = ImageDraw.Draw(mask)
        heights = []
        for i in range(cols):
            k = abs(i - centre)
            lag = int(k * 1.1)
            hist = Ls[(f - lag) % N] if syn else Ls[max(0, f - lag)]                 # giọng nảy ở giữa rồi lan ra hai bên
            v = (0.62 * hist + 0.38 * Bs[f, k]) * env[i] * (1 + 0.04 * np.sin(2 * np.pi * wob_cycles * f / N + i))
            h = minh + (maxh - minh) * min(1.0, float(v)) ** 1.1
            heights.append(h)
            xx = x0 + i * (a.bar_w + a.gap)
            y = (H - h) / 2
            d.rounded_rectangle([xx * SS, y * SS, (xx + a.bar_w) * SS, (y + h) * SS],
                                radius=a.bar_w * SS / 2, fill=255)
        m = np.asarray(mask, dtype=np.float32) / 255
        # màu: thân kem, đầu thanh ánh vàng ấm (gradient theo chiều dọc), mép ngoài mờ nhẹ
        tip = (np.abs(gy - 0.5) * 2) ** 2.2
        col = body[None, None, :] * (1 - tip[..., None]) + accent[None, None, :] * tip[..., None]
        colx = np.broadcast_to(col, (H * SS, W * SS, 3)).copy()
        rgba = np.dstack([colx, m * 255])
        img = Image.fromarray(rgba.astype(np.uint8), "RGBA")
        if a.glow > 0:
            g = img.filter(ImageFilter.GaussianBlur(7 * SS))
            ga = np.asarray(g, dtype=np.float32)
            ga[..., 3] *= a.glow
            img = Image.alpha_composite(Image.fromarray(ga.astype(np.uint8), "RGBA"), img)
        img = img.resize((W, H), Image.LANCZOS)
        p.stdin.write(np.asarray(img, dtype=np.uint8).tobytes())
    p.stdin.close()
    p.wait()

    audio_args = ["-i", a.audio, "-map", "0:v", "-map", "1:a", "-c:a", "aac", "-b:a", "256k", "-shortest"] \
        if a.with_audio else ["-an"]
    if a.scene:
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-stream_loop", "-1", "-i", a.scene, "-i", master, "-i", a.audio,
             "-filter_complex", f"[0:v][1:v]overlay=(W-w)/2:H-h-{a.bottom}:shortest=1[v]",
             "-map", "[v]", "-map", "2:a", "-t", f"{dur:.3f}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
             "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "256k", "-movflags", "+faststart", a.out], check=True)
    elif a.out.endswith(".webm"):
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", master, *audio_args[:0], "-c:v", "libvpx-vp9",
                        "-pix_fmt", "yuva420p", "-b:v", "0", "-crf", "26", "-auto-alt-ref", "0", "-an", a.out],
                       check=True)
    elif a.out.endswith(".mp4"):
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"color=c=black:s={W}x{H}:r={FPS}",
                        "-i", master, "-filter_complex", "[0:v][1:v]overlay=shortest=1[v]", "-map", "[v]",
                        "-t", f"{dur:.3f}", "-c:v", "libx264", "-crf", "16", "-pix_fmt", "yuv420p", "-an", a.out],
                       check=True)
    print(f"OK: {a.out} ({dur:.1f}s, {cols} thanh, nền trong suốt)" if not a.out.endswith(".mp4")
          else f"OK: {a.out} ({dur:.1f}s, nền đen, dùng Screen/Lighten)")


if __name__ == "__main__":
    main()
