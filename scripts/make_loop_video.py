#!/usr/bin/env python3
"""Tạo video LOOP liền mạch từ 1 ảnh tĩnh: lửa lò sưởi chuyển động nhẹ + giọt mưa trượt trên cửa kính.
Mọi thứ khác (người, điện thoại, phong bì, nến, hoa, nội thất, ánh sáng tổng thể) giữ nguyên, camera khóa cố định.

Mọi chuyển động đều có chu kỳ bằng đúng độ dài video nên frame cuối nối khít frame đầu.

  python scripts/make_loop_video.py anh.png loop.mp4 [--seconds 15] [--width 1920]
Vùng lửa/cửa sổ tính theo tỉ lệ ảnh; chỉnh bằng --fire x0,y0,x1,y1 và --glass x0,y0,x1,y1 (0-1).
"""
import argparse
import subprocess

import numpy as np
from PIL import Image, ImageFilter

FPS = 24


def blob(sx, sy):
    hx, hy = int(sx * 3) + 1, int(sy * 3) + 1
    y, x = np.mgrid[-hy:hy + 1, -hx:hx + 1].astype(np.float32)
    return np.exp(-(x * x) / (2 * sx * sx) - (y * y) / (2 * sy * sy)), hx, hy


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("image")
    ap.add_argument("out")
    ap.add_argument("--seconds", type=int, default=15)
    ap.add_argument("--width", type=int, default=1920)
    ap.add_argument("--fire", default="0.013,0.54,0.125,0.80")
    ap.add_argument("--glass", default="0.77,0.02,0.998,0.43")
    ap.add_argument("--seed", type=int, default=3)
    a = ap.parse_args()

    im = Image.open(a.image).convert("RGB")
    W = a.width
    H = round(W * im.height / im.width / 2) * 2
    if abs(im.width / im.height - 16 / 9) < 0.03:  # gần 16:9 -> ép đúng 1080p (lệch <1%)
        H = round(W * 9 / 16 / 2) * 2
    base = im.resize((W, H), Image.LANCZOS).filter(ImageFilter.UnsharpMask(1.6, 60, 2))
    base = np.asarray(base, dtype=np.float32)
    T = a.seconds
    N = T * FPS
    rng = np.random.default_rng(a.seed)

    def box(s):
        x0, y0, x1, y1 = (float(v) for v in s.split(","))
        return int(x0 * W), int(y0 * H), int(x1 * W), int(y1 * H)

    fx0, fy0, fx1, fy1 = box(a.fire)
    gx0, gy0, gx1, gy1 = box(a.glass)
    fire = base[fy0:fy1, fx0:fx1].copy()
    fh, fw = fire.shape[:2]
    # mặt nạ ngọn lửa = vùng sáng, màu cam; viền mềm
    lum = fire.mean(axis=2)
    warm = (fire[..., 0] > fire[..., 2] * 1.4)
    fmask = np.clip((lum - 90) / 90, 0, 1) * warm
    fmask = np.asarray(Image.fromarray((fmask * 255).astype(np.uint8)).filter(
        ImageFilter.GaussianBlur(W / 400)), dtype=np.float32)[..., None] / 255
    ys = np.arange(fh, dtype=np.float32)[:, None]
    xs = np.arange(fw, dtype=np.float32)[None, :]

    # các giọt mưa: x, pha, số vòng trượt trong video (nguyên => lặp khít), bán kính
    gw, gh = gx1 - gx0, gy1 - gy0
    drops = []
    for i in range(14):
        drops.append(dict(x=rng.uniform(0.04, 0.96) * gw, ph=rng.uniform(0, 1),
                          k=int(rng.choice([1, 1, 2])), r=rng.uniform(0.0012, 0.0022) * W,
                          wob=rng.uniform(0, 6.28)))
    sprites = {}
    # giọt chỉ hiện trên kính, không đè lên khung cửa tối
    glum = base[gy0:gy1, gx0:gx1].mean(axis=2)
    pane = np.clip((glum - 28) / 30, 0, 1)
    pane = np.asarray(Image.fromarray((pane * 255).astype(np.uint8)).filter(
        ImageFilter.GaussianBlur(W / 300)), dtype=np.float32) / 255

    ff = subprocess.Popen(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
         "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-crf", "17", "-preset", "slow",
         "-pix_fmt", "yuv420p", "-movflags", "+faststart", a.out], stdin=subprocess.PIPE)
    for f in range(N):
        t = f / N  # 0..1, tuần hoàn
        fr = base.copy()
        # --- lửa: dao động ngang rất nhẹ theo sóng chạy lên + nhấp nháy sáng, tất cả tuần hoàn
        w = 2 * np.pi
        shift = (1.2 * np.sin(w * (ys / 22.0 - 3 * t)) + 0.7 * np.sin(w * (ys / 11.0 - 5 * t + 0.3))) * (W / 1920)
        shift = shift * (ys / fh)  # chân lửa đứng yên, đỉnh lửa lay
        sx = np.clip(xs + shift, 0, fw - 1)
        x0i = np.floor(sx).astype(int)
        x1i = np.clip(x0i + 1, 0, fw - 1)
        wx = (sx - x0i)[..., None]
        rows = np.arange(fh)[:, None]
        warped = fire[rows, x0i] * (1 - wx) + fire[rows, x1i] * wx
        flick = 1 + 0.05 * np.sin(w * 3 * t) + 0.03 * np.sin(w * 7 * t + 1.3) + 0.02 * np.sin(w * 11 * t + 0.4)
        newfire = warped * flick
        fr[fy0:fy1, fx0:fx1] = fire * (1 - fmask) + newfire * fmask
        # --- mưa: giọt sáng nhẹ + vệt mờ phía trên, trượt xuống chậm, lặp khít
        layer = np.zeros((gh, gw), dtype=np.float32)
        for d in drops:
            p = (d["k"] * t + d["ph"]) % 1.0
            cy = p * (gh + 120) - 60
            cx = d["x"] + 3 * np.sin(w * (t * d["k"]) + d["wob"])
            fade = np.clip(min(cy + 40, gh - cy + 10) / 50, 0, 1)
            r = d["r"]
            # hạt nước nhỏ hơi dài theo chiều dọc + vệt mảnh phía trên
            for (sx_, sy_, dy, amp) in ((r, r * 1.5, 0, 0.60), (r * 0.45, r * 9, -r * 9, 0.16)):
                key = (sx_, sy_)
                if key not in sprites:
                    sprites[key] = blob(sx_, sy_)
                sp, hx, hy = sprites[key]
                yy, xx = int(cy + dy), int(cx)
                y0, y1 = max(0, yy - hy), min(gh, yy + hy + 1)
                x0, x1 = max(0, xx - hx), min(gw, xx + hx + 1)
                if y0 < y1 and x0 < x1:
                    layer[y0:y1, x0:x1] += amp * fade * sp[y0 - (yy - hy):y1 - (yy - hy), x0 - (xx - hx):x1 - (xx - hx)]
        glass = fr[gy0:gy1, gx0:gx1]
        tint = np.array([255, 225, 190], dtype=np.float32)
        fr[gy0:gy1, gx0:gx1] = glass + (tint - glass) * (np.clip(layer, 0, 0.6) * pane)[..., None]
        ff.stdin.write(np.clip(fr, 0, 255).astype(np.uint8).tobytes())
    ff.stdin.close()
    ff.wait()
    print(f"OK: {a.out} ({T}s, {W}x{H}, {FPS}fps)")


if __name__ == "__main__":
    main()
