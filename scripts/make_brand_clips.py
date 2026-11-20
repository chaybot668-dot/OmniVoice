#!/usr/bin/env python3
"""Intro và outro cho kênh HER SIDE OF THE STORY (1920x1080, 24 fps, có âm thanh gốc tổng hợp bằng code).

  python scripts/make_brand_clips.py out_dir
  python scripts/make_brand_clips.py out_dir --logo stories/brand/logo.webp --intro-seconds 5 --outro-seconds 12

Xuất:
  intro.mp4            logo hiện dần + câu khẩu hiệu, ngắn (mặc định 5 giây) để người xem vào truyện nhanh
  outro.mp4            cảm ơn + Subscribe + khẩu hiệu, bố cục giữa
  outro_endscreen.mp4  cùng nội dung nhưng chừa nửa phải cho phần tử "End screen" của YouTube
Font: Dancing Script, Lora (SIL OFL, dùng thương mại được) trong scripts/fonts.  Cần: numpy, scipy, Pillow, ffmpeg.
"""
import argparse
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont
from scipy import signal

W, H, FPS, SR = 1920, 1080, 24, 48000
FONTS = Path(__file__).with_name("fonts")
GOLD = (222, 178, 92)
PINK = (242, 140, 166)
CREAM = (250, 242, 232)


def font(name, size, var="Bold"):
    f = ImageFont.truetype(str(FONTS / name), size)
    try:
        f.set_variation_by_name(var)
    except Exception:
        pass
    return f


def circle_logo(path, size):
    im = Image.open(path).convert("RGBA")
    cx, cy, r = 496, 485, 482  # vòng vàng của logo gốc
    im = im.crop((cx - r, cy - r, cx + r, cy + r)).resize((size, size), Image.LANCZOS)
    mask = Image.new("L", (size * 4, size * 4), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, size * 4 - 1, size * 4 - 1], fill=255)
    im.putalpha(mask.resize((size, size), Image.LANCZOS))
    return im


def background():
    y, x = np.mgrid[0:H, 0:W].astype(np.float32)
    d = np.sqrt(((x - W / 2) / (W / 2)) ** 2 + ((y - H * 0.45) / (H * 0.62)) ** 2)
    v = np.clip(1 - d * 0.78, 0, 1) ** 1.4
    top = np.array([18, 11, 12], np.float32)
    glow = np.array([58, 30, 28], np.float32)
    img = top[None, None, :] + (glow - top)[None, None, :] * v[..., None]
    return Image.fromarray(img.astype(np.uint8), "RGB").convert("RGBA")


def sprite(r, color, a):
    n = int(r * 6)
    s = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    ImageDraw.Draw(s).ellipse([n / 2 - r, n / 2 - r, n / 2 + r, n / 2 + r], fill=color + (int(255 * a),))
    return s.filter(ImageFilter.GaussianBlur(r * 0.55))


def particles(rng, count=34):
    return [dict(x=rng.uniform(0, W), y=rng.uniform(0, H), r=rng.uniform(4, 15), sp=rng.uniform(8, 26),
                 ph=rng.uniform(0, 6.28), a=rng.uniform(0.25, 0.55)) for _ in range(count)]


def text_layer(lines, color, fnt, width=W, line_gap=1.15):
    """Ảnh RGBA chứa các dòng chữ căn giữa theo chiều ngang (mỗi dòng 1 màu)."""
    boxes = [fnt.getbbox(t) for t, _ in lines]
    hs = [b[3] - b[1] for b in boxes]
    total = int(sum(hs) * line_gap) + 20
    im = Image.new("RGBA", (width, total), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    y = 0
    for (t, c), b, h in zip(lines, boxes, hs):
        d.text(((width - (b[2] - b[0])) / 2 - b[0], y - b[1]), t, font=fnt, fill=c + (255,))
        y += int(h * line_gap)
    return im


def ease(t):
    t = min(1, max(0, t))
    return t * t * (3 - 2 * t)


def paste(base, layer, x, y, alpha=1.0):
    if alpha <= 0:
        return
    if alpha < 1:
        layer = layer.copy()
        a = layer.getchannel("A").point(lambda v: int(v * alpha))
        layer.putalpha(a)
    base.alpha_composite(layer, (int(x), int(y)))


def render_video(path, frames, make_frame, audio_path):
    p = subprocess.Popen(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS),
         "-i", "-", "-i", str(audio_path), "-c:v", "libx264", "-preset", "slow", "-crf", "17", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-b:a", "256k", "-shortest", "-movflags", "+faststart", str(path)], stdin=subprocess.PIPE)
    for f in range(frames):
        p.stdin.write(np.asarray(make_frame(f / FPS).convert("RGB"), dtype=np.uint8).tobytes())
    p.stdin.close()
    p.wait()


# ---------------- âm thanh ----------------
def hz(m):
    return 440.0 * 2 ** ((m - 69) / 12)


def piano_note(m, dur, vel, rng):
    n = int(dur * SR)
    t = np.arange(n, dtype=np.float32) / SR
    f = hz(m)
    v = np.zeros(n, np.float32)
    for k in range(1, 11):
        v += k ** -1.15 * np.exp(-0.16 * k) * np.exp(-t / (2.4 / (1 + 0.45 * k))) * np.sin(2 * np.pi * f * k * (1 + 0.0004 * k * k) * t)
    return v * np.minimum(1, t / 0.006) * vel * 0.4


def pad_chord(ms, dur, att, rel, rng):
    n = int(dur * SR)
    t = np.arange(n, dtype=np.float32) / SR
    p = np.zeros(n, np.float32)
    for m in ms:
        for det in (-0.0012, 0.0, 0.0012):
            for k, a in ((1, 1.0), (2, 0.3), (3, 0.1)):
                p += a * np.sin(2 * np.pi * hz(m) * (1 + det) * k * t + rng.uniform(0, 6.28)).astype(np.float32)
    env = np.minimum(1, t / att) ** 1.5 * np.clip((dur - t) / rel, 0, 1)
    return p * env.astype(np.float32) / (len(ms) * 3) * 0.55


def make_audio(path, dur, notes, pad_ms, seed):
    rng = np.random.default_rng(seed)
    N = int((dur + 3) * SR)
    x = np.zeros(N, np.float32)
    pd = pad_chord(pad_ms, dur + 1, 1.6, 2.5, rng)
    x[:len(pd)] += pd
    for t0, m, d, v in notes:
        nt = piano_note(m, d, v, rng)
        i = int(t0 * SR)
        x[i:i + len(nt)] += nt[:max(0, N - i)]
    sos = signal.butter(2, 3500, "low", fs=SR, output="sos")
    x = signal.sosfilt(sos, x).astype(np.float32)
    nir = int(2.6 * SR)
    tir = np.arange(nir) / SR
    ir = (rng.standard_normal(nir) * np.exp(-6.9 * tir / 2.6)).astype(np.float32)
    ir = signal.sosfilt(sos, ir).astype(np.float32)
    wet = signal.fftconvolve(x, ir / np.sqrt((ir ** 2).sum()) * 0.9)[:N].astype(np.float32)
    mono = x * 0.65 + wet * 0.55
    d = int(0.012 * SR)
    st = np.stack([mono, np.concatenate([np.zeros(d, np.float32), mono[:-d]])], axis=1)
    n = int(dur * SR)
    st = st[:n]
    fi, fo = int(0.4 * SR), int(1.4 * SR)
    st[:fi] *= (np.sin(np.linspace(0, np.pi / 2, fi)) ** 2)[:, None]
    st[-fo:] *= (np.cos(np.linspace(0, np.pi / 2, fo)) ** 2)[:, None]
    p = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-f", "f32le", "-ar", str(SR), "-ac", "2", "-i", "-", "-af",
                        "loudnorm=I=-18:TP=-1.5:LRA=7:print_format=json", "-f", "null", "-"],
                       input=st.astype(np.float32).tobytes(), capture_output=True)
    import json
    import re
    li = float(json.loads(re.findall(r"\{[^{}]*\}", p.stderr.decode(), re.S)[-1])["input_i"])
    st *= 10 ** ((-18 - li) / 20)
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "f32le", "-ar", str(SR), "-ac", "2", "-i", "-",
                    "-af", "alimiter=limit=0.84:level=disabled", "-c:a", "pcm_s24le", str(path)],
                   input=st.astype(np.float32).tobytes(), check=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("out_dir")
    ap.add_argument("--logo", default=str(Path(__file__).resolve().parents[1] / "stories/brand/logo.webp"))
    ap.add_argument("--intro-seconds", type=float, default=5.0)
    ap.add_argument("--outro-seconds", type=float, default=12.0)
    a = ap.parse_args()
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(3)
    bg = background()
    parts = particles(rng)
    sprites = {}

    def base(t):
        im = bg.copy()
        for p_ in parts:
            y = (p_["y"] - p_["sp"] * t) % (H + 40) - 20
            al = p_["a"] * (0.55 + 0.45 * np.sin(p_["ph"] + t * 1.3))
            key = (round(p_["r"]), round(al, 1))
            if key not in sprites:
                sprites[key] = sprite(p_["r"], GOLD, al)
            sp = sprites[key]
            im.alpha_composite(sp, (int(p_["x"] - sp.width / 2), int(y - sp.height / 2)))
        return im

    f_tag = font("DancingScript.ttf", 66)
    f_big = font("DancingScript.ttf", 112)
    f_btn = font("Lora.ttf", 46, "Bold")
    f_small = font("DancingScript.ttf", 54, "SemiBold")
    tag1 = text_layer([("Every Woman Has a Story.", CREAM), ("Not Every Story Gets Told.", PINK)], CREAM, f_tag)

    # ================= INTRO =================
    di = a.intro_seconds
    logo_big = circle_logo(a.logo, 700)

    def intro_frame(t):
        im = base(t)
        s = 0.90 + 0.10 * ease(t / 2.4)
        sz = int(700 * s)
        lg = logo_big.resize((sz, sz), Image.LANCZOS)
        glow = Image.new("RGBA", (sz + 260, sz + 260), (0, 0, 0, 0))
        ImageDraw.Draw(glow).ellipse([100, 100, sz + 160, sz + 160], fill=GOLD + (int(70 + 28 * np.sin(t * 2.2)),))
        glow = glow.filter(ImageFilter.GaussianBlur(60))
        al = ease((t - 0.2) / 1.2)
        paste(im, glow, W / 2 - glow.width / 2, 430 - glow.height / 2, al)
        paste(im, lg, W / 2 - sz / 2, 430 - sz / 2, al)
        # đường vàng + khẩu hiệu
        ta = ease((t - 2.0) / 1.0)
        if ta > 0:
            d = ImageDraw.Draw(im)
            half = int(260 * ease((t - 1.8) / 1.2))
            d.line([(W / 2 - half, 842), (W / 2 + half, 842)], fill=GOLD + (200,), width=3)
        paste(im, tag1, 0, 860, ta)
        fade = 1 - ease((t - (di - 0.7)) / 0.7)
        if fade < 1:
            im = Image.blend(Image.new("RGBA", im.size, (0, 0, 0, 255)), im, fade)
        return im

    make_audio(out / "_intro.wav", di,
               [(1.2, 74, 3.5, 0.55), (2.2, 69, 3.0, 0.5), (3.0, 62, 2.5, 0.45)], [50, 57, 62, 65], 1)
    render_video(out / "intro.mp4", int(di * FPS), intro_frame, out / "_intro.wav")

    # ================= OUTRO =================
    do = a.outro_seconds
    thanks_c = text_layer([("Thank you for listening.", CREAM)], CREAM, f_big)
    heart_small = text_layer([("for more heartfelt stories", PINK)], PINK, f_small)

    def button():
        w_, h_ = 560, 112
        b = Image.new("RGBA", (w_, h_), (0, 0, 0, 0))
        d = ImageDraw.Draw(b)
        d.rounded_rectangle([0, 0, w_ - 1, h_ - 1], radius=h_ // 2, fill=PINK + (255,))
        t = "SUBSCRIBE"
        bb = f_btn.getbbox(t)
        d.text(((w_ - (bb[2] - bb[0])) / 2 - bb[0] + 28, (h_ - (bb[3] - bb[1])) / 2 - bb[1] - 2), t, font=f_btn, fill=(40, 18, 24, 255))
        # trái tim
        cx, cy = 118, h_ // 2 + 2
        d.ellipse([cx - 22, cy - 22, cx, cy], fill=(40, 18, 24, 255))
        d.ellipse([cx, cy - 22, cx + 22, cy], fill=(40, 18, 24, 255))
        d.polygon([(cx - 21, cy - 7), (cx + 21, cy - 7), (cx, cy + 24)], fill=(40, 18, 24, 255))
        return b
    btn = button()

    def outro_frame_factory(endscreen):
        logo = circle_logo(a.logo, 480 if endscreen else 520)
        cx = 480 if endscreen else W // 2
        tw = 900 if endscreen else W

        def fr(t):
            im = base(t)
            la = ease((t - 0.1) / 1.0)
            sz = logo.width
            glow = Image.new("RGBA", (sz + 220, sz + 220), (0, 0, 0, 0))
            ImageDraw.Draw(glow).ellipse([80, 80, sz + 140, sz + 140], fill=GOLD + (int(55 + 20 * np.sin(t * 2.0)),))
            glow = glow.filter(ImageFilter.GaussianBlur(50))
            ly = 310 if endscreen else 300
            paste(im, glow, cx - glow.width / 2, ly - glow.height / 2, la)
            paste(im, logo, cx - sz / 2, ly - sz / 2, la)
            tl = text_layer([("Thank you for listening.", CREAM)], CREAM, f_big if not endscreen else font("DancingScript.ttf", 84), width=tw)
            paste(im, tl, cx - tw / 2, 575 if not endscreen else 580, ease((t - 0.8) / 0.9))
            tg = text_layer([("Every Woman Has a Story.", CREAM), ("Not Every Story Gets Told.", PINK)], CREAM,
                            font("DancingScript.ttf", 60 if not endscreen else 52), width=tw)
            paste(im, tg, cx - tw / 2, 705 if not endscreen else 705, ease((t - 1.8) / 0.9))
            ba = ease((t - 3.2) / 0.8)
            pulse = 1 + 0.025 * np.sin(max(0, t - 4.0) * 3.4)
            b2 = btn.resize((int(btn.width * pulse * (0.8 if endscreen else 1)), int(btn.height * pulse * (0.8 if endscreen else 1))), Image.LANCZOS)
            by = 900 if not endscreen else 915
            paste(im, b2, cx - b2.width / 2, by, ba)
            if endscreen:
                # chừa nửa phải cho phần tử video của YouTube; khung nhạt cho cân bố cục
                d = ImageDraw.Draw(im)
                ea = ease((t - 2.0) / 1.0)
                if ea > 0:
                    d.rounded_rectangle([1010, 250, 1750, 666], radius=22, outline=GOLD + (int(120 * ea),), width=2)
            fade = 1 - ease((t - (do - 1.2)) / 1.2)
            if fade < 1:
                im = Image.blend(Image.new("RGBA", im.size, (0, 0, 0, 255)), im, fade)
            return im
        return fr

    make_audio(out / "_outro.wav", do,
               [(0.9, 77, 4.0, 0.5), (2.6, 74, 4.0, 0.45), (4.4, 69, 4.5, 0.45), (6.4, 65, 5.0, 0.4), (8.4, 62, 6.0, 0.4)],
               [50, 53, 57, 62], 2)
    render_video(out / "outro.mp4", int(do * FPS), outro_frame_factory(False), out / "_outro.wav")
    render_video(out / "outro_endscreen.mp4", int(do * FPS), outro_frame_factory(True), out / "_outro.wav")
    for f in ("_intro.wav", "_outro.wav"):
        (out / f).unlink()
    print(f"OK: {out}/intro.mp4, outro.mp4, outro_endscreen.mp4")


if __name__ == "__main__":
    main()
