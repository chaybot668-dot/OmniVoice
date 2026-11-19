#!/usr/bin/env python3
"""Tạo video từ 1 ảnh tĩnh: lửa lò sưởi bập bùng + giọt mưa trượt trên cửa kính, camera khóa.
Người, điện thoại, phong bì, nến, hoa, nội thất, ánh sáng tổng thể giữ nguyên.
Mọi chuyển động tuần hoàn đúng theo độ dài loop nên nối vòng liền mạch.

  # chỉ tạo loop 30 giây
  python scripts/make_loop_video.py anh.webp loop.mp4
  # tạo luôn video dài bằng file MP3 (lặp loop, ghép âm thanh)
  python scripts/make_loop_video.py anh.webp loop.mp4 --audio full.mp3 --final final_youtube.mp4
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


def put(layer, sp, hx, hy, cx, cy, amp):
    gh, gw = layer.shape
    yy, xx = int(cy), int(cx)
    y0, y1 = max(0, yy - hy), min(gh, yy + hy + 1)
    x0, x1 = max(0, xx - hx), min(gw, xx + hx + 1)
    if y0 < y1 and x0 < x1:
        layer[y0:y1, x0:x1] += amp * sp[y0 - (yy - hy):y1 - (yy - hy), x0 - (xx - hx):x1 - (xx - hx)]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("image")
    ap.add_argument("out")
    ap.add_argument("--seconds", type=int, default=30, help="độ dài 1 vòng loop")
    ap.add_argument("--width", type=int, default=1920)
    ap.add_argument("--fire", default="0.013,0.54,0.125,0.80")
    ap.add_argument("--glass", default="0.77,0.02,0.998,0.43")
    ap.add_argument("--seed", type=int, default=5)
    ap.add_argument("--fire-frames", nargs="+",
                    help="các ảnh cùng cảnh có hình ngọn lửa THẬT khác nhau; lửa sẽ được nội suy giữa các ảnh này")
    ap.add_argument("--fire-box", default="0.0,0.50,0.15,0.84", help="vùng thay lửa (tỉ lệ ảnh)")
    ap.add_argument("--audio", help="file MP3 để làm video dài bằng nó")
    ap.add_argument("--final", help="video cuối (cần --audio)")
    a = ap.parse_args()
    if bool(a.audio) != bool(a.final):
        raise SystemExit("--audio và --final phải đi cùng nhau")

    im = Image.open(a.image).convert("RGB")
    W = a.width
    H = round(W * im.height / im.width / 2) * 2
    if abs(im.width / im.height - 16 / 9) < 0.03:
        H = round(W * 9 / 16 / 2) * 2
    base = np.asarray(im.resize((W, H), Image.LANCZOS).filter(ImageFilter.UnsharpMask(1.6, 60, 2)),
                      dtype=np.float32)
    T = a.seconds
    N = T * FPS
    rng = np.random.default_rng(a.seed)
    w = 2 * np.pi
    sc = W / 1920

    def box(s):
        x0, y0, x1, y1 = (float(v) for v in s.split(","))
        return int(x0 * W), int(y0 * H), int(x1 * W), int(y1 * H)

    kf = None
    if a.fire_frames:
        import cv2
        bx0, by0, bx1, by1 = box(a.fire_box)
        scale = W / im.width
        bs = np.asarray(im, dtype=np.uint8)
        g0 = cv2.cvtColor(bs, cv2.COLOR_RGB2GRAY).astype(np.float32) / 255
        sharp = lambda pil: np.asarray(pil.resize((W, H), Image.LANCZOS).filter(
            ImageFilter.UnsharpMask(1.6, 60, 2)), dtype=np.float32)
        frames_up = [base]
        for pth in a.fire_frames:
            pk = Image.open(pth).convert("RGB").resize(im.size, Image.LANCZOS)
            gk = cv2.cvtColor(np.asarray(pk, dtype=np.uint8), cv2.COLOR_RGB2GRAY).astype(np.float32) / 255
            msk = np.zeros(g0.shape, np.uint8)
            msk[int(.38 * im.height):int(.95 * im.height), :int(.30 * im.width)] = 255
            msk[(g0 > .35) | (gk > .35)] = 0  # bỏ vùng lửa sáng, chỉ khớp khung lò/đá cẩm thạch
            wm = np.eye(2, 3, dtype=np.float32)
            try:
                cc, wm = cv2.findTransformECC(g0, gk, wm, cv2.MOTION_TRANSLATION,
                                              (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 300, 1e-7), msk, 5)
            except cv2.error:
                print(f"  cảnh báo: không căn được {pth}, dùng nguyên vị trí")
            print(f"  căn ảnh {pth}: dịch ({wm[0, 2]:.2f}, {wm[1, 2]:.2f}) px, độ khớp {cc:.3f}")
            up = sharp(pk)
            wm_up = wm.copy()
            wm_up[:, 2] *= scale
            up = cv2.warpAffine(up, wm_up, (W, H), flags=cv2.INTER_LINEAR + cv2.WARP_INVERSE_MAP,
                                borderMode=cv2.BORDER_REPLICATE)
            frames_up.append(up)
        crops = [f[by0:by1, bx0:bx1].copy() for f in frames_up]
        kh, kw = crops[0].shape[:2]
        grays = [cv2.cvtColor(np.clip(c, 0, 255).astype(np.uint8), cv2.COLOR_RGB2GRAY) for c in crops]
        flows = {}
        for i in range(len(crops)):
            for j in range(len(crops)):
                if i != j:  # flow[(i,j)]: điểm trong j -> vị trí tương ứng trong i
                    flows[(i, j)] = cv2.calcOpticalFlowFarneback(grays[j], grays[i], None, 0.5, 4, 25, 6, 7, 1.5, 0)
        feather = np.zeros((kh, kw), np.float32)
        m = int(W / 100)
        feather[m:-m, m:-m] = 1
        feather = cv2.GaussianBlur(feather, (0, 0), W / 260)[..., None]
        gridx, gridy = np.meshgrid(np.arange(kw, dtype=np.float32), np.arange(kh, dtype=np.float32))
        # lịch phát: các ảnh lửa đổi ngẫu nhiên, mỗi chuyển 0.4-0.8 giây, kết thúc đúng ảnh đầu -> loop khít
        order = [0]
        total = 0
        durs = []
        while total < N - 12:
            nxt = int(rng.integers(0, len(crops)))
            while nxt == order[-1]:
                nxt = int(rng.integers(0, len(crops)))
            d = int(rng.integers(10, 20))
            order.append(nxt)
            durs.append(d)
            total += d
        if order[-1] != order[0]:
            order.append(order[0])
            durs.append(12)
        durs = np.array(durs, dtype=float)
        durs = np.maximum(6, np.round(durs * N / durs.sum())).astype(int)
        durs[-1] += N - durs.sum()
        starts = np.concatenate([[0], np.cumsum(durs)])

        def fire_at(f):
            k = int(np.searchsorted(starts, f, side="right") - 1)
            k = min(k, len(durs) - 1)
            sa = (f - starts[k]) / durs[k]
            sa = sa * sa * (3 - 2 * sa)
            ia, ib = order[k], order[k + 1]
            fl = flows[(ia, ib)]
            f32 = lambda x: np.ascontiguousarray(x, dtype=np.float32)
            A = cv2.remap(crops[ia], f32(gridx + sa * fl[..., 0]), f32(gridy + sa * fl[..., 1]),
                          cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
            B = cv2.remap(crops[ib], f32(gridx - (1 - sa) * fl[..., 0]), f32(gridy - (1 - sa) * fl[..., 1]),
                          cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
            return A * (1 - sa) + B * sa

    # ---------- LỬA: chỉ ngọn lửa (vùng cam sáng) bị xô lệch + nhấp nháy; củi/khung lò đứng yên
    fx0, fy0, fx1, fy1 = box(a.fire)
    fire = base[fy0:fy1, fx0:fx1].copy()
    fh, fw = fire.shape[:2]
    lum = fire.mean(axis=2)
    flame = np.clip((lum - 80) / 80, 0, 1) * (fire[..., 0] > fire[..., 2] * 1.4)
    flame = np.asarray(Image.fromarray((flame * 255).astype(np.uint8)).filter(
        ImageFilter.GaussianBlur(W / 350)), dtype=np.float32) / 255
    yy_, xx_ = np.mgrid[0:fh, 0:fw].astype(np.float32)
    up = np.clip(1 - yy_ / fh, 0, 1)  # càng lên cao càng lay mạnh
    height_w = (0.25 + 0.75 * up) * flame
    # 6 sóng chạy lên, tần số thời gian nguyên (chu kỳ/loop) -> tuần hoàn, ngẫu nhiên pha/hướng
    waves = [dict(ft=int(rng.integers(T * 1, T * 4)), ky=rng.uniform(0.010, 0.026) / sc,
                  kx=rng.uniform(-0.012, 0.012) / sc, ph=rng.uniform(0, w),
                  ax=rng.uniform(1.0, 2.6) * sc, ay=rng.uniform(0.8, 2.0) * sc) for _ in range(6)]
    bands = [dict(ft=int(rng.integers(T * 2, T * 6)), ky=rng.uniform(0.006, 0.016) / sc,
                  ph=rng.uniform(0, w), a=rng.uniform(0.02, 0.035)) for _ in range(4)]
    rowi = np.arange(fh)[:, None]

    # ---------- MƯA: hạt nước có điểm sáng + bóng, trượt kiểu nhanh-chậm, để lại vệt ướt
    gx0, gy0, gx1, gy1 = box(a.glass)
    gw, gh = gx1 - gx0, gy1 - gy0
    glum = base[gy0:gy1, gx0:gx1].mean(axis=2)
    pane = np.asarray(Image.fromarray((np.clip((glum - 14) / 16, 0, 1) * 255).astype(np.uint8)).filter(
        ImageFilter.GaussianBlur(W / 300)), dtype=np.float32) / 255
    drops = [dict(x=rng.uniform(0.04, 0.96) * gw, ph=rng.uniform(0, 1), k=int(rng.choice([1, 1, 2, 2, 3])),
                  r=rng.uniform(0.0022, 0.0038) * W, wob=rng.uniform(0, w), sl=rng.uniform(0.07, 0.12))
             for _ in range(11)]
    spr = {}

    def sprite(sx, sy):
        if (sx, sy) not in spr:
            spr[(sx, sy)] = blob(sx, sy)
        return spr[(sx, sy)]

    ff = subprocess.Popen(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
         "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-crf", "17", "-preset", "slow",
         "-pix_fmt", "yuv420p", "-movflags", "+faststart", a.out], stdin=subprocess.PIPE)
    for f in range(N):
        t = f / N
        fr = base.copy()
        # lửa
        if a.fire_frames:
            blk = fire_at(f)
            fr[by0:by1, bx0:bx1] = base[by0:by1, bx0:bx1] * (1 - feather) + blk * feather
        else:
            dx = np.zeros((fh, fw), np.float32)
            dy = np.zeros((fh, fw), np.float32)
            for q in waves:
                s = np.sin(w * (q["ft"] * t) - q["ky"] * yy_ * w + q["kx"] * xx_ * w + q["ph"])
                dx += q["ax"] * s
                dy += q["ay"] * np.cos(w * (q["ft"] * t) - q["ky"] * yy_ * w + q["ph"])
            dx = dx * height_w / 3
            dy = dy * height_w / 3
            sx = np.clip(xx_ + dx, 0, fw - 1)
            sy = np.clip(yy_ + dy, 0, fh - 1)
            x0i, y0i = np.floor(sx).astype(int), np.floor(sy).astype(int)
            x1i, y1i = np.clip(x0i + 1, 0, fw - 1), np.clip(y0i + 1, 0, fh - 1)
            wx, wy = (sx - x0i)[..., None], (sy - y0i)[..., None]
            warped = (fire[y0i, x0i] * (1 - wx) * (1 - wy) + fire[y0i, x1i] * wx * (1 - wy)
                      + fire[y1i, x0i] * (1 - wx) * wy + fire[y1i, x1i] * wx * wy)
            flick = np.ones((fh, 1), np.float32)
            for b in bands:
                flick = flick + b["a"] * np.sin(w * (b["ft"] * t) - b["ky"] * yy_[:, :1] * w + b["ph"])
            flick = flick * (0.7 + 0.3 * up[:, :1]) + (1 - (0.7 + 0.3 * up[:, :1]))
            fr[fy0:fy1, fx0:fx1] = fire * (1 - flame[..., None]) + warped * flick[..., None] * flame[..., None]
        # mưa
        light = np.zeros((gh, gw), np.float32)
        dark = np.zeros((gh, gw), np.float32)
        for d in drops:
            p = (d["k"] * t + d["sl"] * np.sin(w * d["k"] * t + d["wob"]) + d["ph"]) % 1.0
            cy = p * (gh + 160) - 80
            cx = d["x"] + 2.5 * sc * np.sin(w * d["k"] * t + d["wob"])
            fade = float(np.clip(min(cy + 30, gh - cy + 6) / 40, 0, 1))
            r = d["r"]
            sp, hx, hy = sprite(r * 1.1, r * 1.6)
            put(light, sp, hx, hy, cx, cy, 0.55 * fade)               # thân giọt
            sp, hx, hy = sprite(r * 0.45, r * 0.55)
            put(light, sp, hx, hy, cx - r * 0.35, cy - r * 0.6, 1.0 * fade)  # điểm sáng
            sp, hx, hy = sprite(r * 1.0, r * 0.7)
            put(dark, sp, hx, hy, cx + r * 0.15, cy + r * 1.1, 0.30 * fade)   # bóng dưới
            sp, hx, hy = sprite(r * 0.35, r * 7)
            put(light, sp, hx, hy, cx, cy - r * 7.5, 0.20 * fade)     # vệt ướt phía trên
        glass = fr[gy0:gy1, gx0:gx1]
        tint = np.array([255, 232, 205], np.float32)
        lt = (np.clip(light, 0, 0.9) * pane)[..., None]
        dk = (np.clip(dark, 0, 0.5) * pane)[..., None]
        fr[gy0:gy1, gx0:gx1] = (glass + (tint - glass) * lt) * (1 - dk)
        ff.stdin.write(np.clip(fr, 0, 255).astype(np.uint8).tobytes())
    ff.stdin.close()
    ff.wait()
    print(f"OK loop: {a.out} ({T}s, {W}x{H}, {FPS}fps)")

    if a.audio:
        dur = float(subprocess.check_output(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", a.audio]).decode())
        print(f"Ghép video dài {dur / 60:.1f} phút theo MP3 ...")
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-stream_loop", "-1", "-i", a.out, "-i", a.audio,
             "-map", "0:v", "-map", "1:a", "-t", f"{dur:.3f}", "-c:v", "libx264", "-preset", "veryfast",
             "-crf", "21", "-tune", "stillimage", "-pix_fmt", "yuv420p", "-r", str(FPS),
             "-c:a", "aac", "-b:a", "256k", "-movflags", "+faststart", a.final], check=True)
        print(f"OK final: {a.final}")


if __name__ == "__main__":
    main()
