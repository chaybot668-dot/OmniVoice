#!/usr/bin/env python3
"""Tạo BÁO CÁO + gói đăng YouTube dạng file để chép nhanh, rồi (tuỳ chọn) gửi Telegram đúng kênh.

Tạo 3 thứ, giống khuôn báo cáo của chủ kênh:
  1) Tin báo cáo ngắn (chủ đề, số từ, giọng, thời lượng, file, chỗ đã chạm, việc cần duyệt)
  2) youtube-publishing-package.md  (tiêu đề, mô tả, tags, chương, ảnh bìa, bình luận ghim, checklist - có khối chép sẵn)
  3) TRANSCRIPT.txt                 (lời đọc cuối cùng)

Đầu vào trong stories/<tên>/: package.json, story.txt (hoặc --story), report_meta.json, và --chapters (chapters.txt).
  python scripts/report_package.py stories/ex-wife-dinner --chapters chapters.txt --out out_dir --dry-run
  python scripts/report_package.py stories/ex-wife-dinner --chapters chapters.txt --out out_dir --channel women --send
Khóa Telegram lấy từ ~/.omnivoice/telegram.env (xem report_story.py).
"""
import argparse
import importlib.util
import json
import re
from pathlib import Path

rs_spec = importlib.util.spec_from_file_location("rs", Path(__file__).with_name("report_story.py"))
rs = importlib.util.module_from_spec(rs_spec)
rs_spec.loader.exec_module(rs)


def chapters_list(path):
    out = []
    for ln in Path(path).read_text(encoding="utf-8-sig").splitlines():
        m = re.match(r"(\d+:\d+)\s+(.*)", ln.strip())
        if m:
            out.append(f"{rs.yt_time(m.group(1))} {rs.pretty_title(m.group(2))}")
    if not out or not out[0].startswith("0:00"):
        raise SystemExit("chapters.txt thiếu mốc 0:00.")
    return out


def transcript(story_path):
    t = Path(story_path).read_text(encoding="utf-8")
    blocks = []
    for sec in re.split(r"(?m)^## ", t)[1:]:
        head, body = sec.split("\n", 1)
        paras = [" ".join(re.sub(r"(?m)^\[[A-H]\]\s*$", "", p).split()) for p in re.split(r"\n\s*\n", body.strip())]
        blocks.append(head.strip() + "\n\n" + "\n\n".join(p for p in paras if p))
    return "\n\n".join(blocks) + "\n"


def fence(s):
    return "```\n" + s.strip() + "\n```"


def build_md(meta, pkg, chapters):
    desc = "\n\n".join([pkg["description_intro"], "\n".join(pkg.get("highlights", [])),
                        "⏱ CHAPTERS\n" + "\n".join(chapters), "\n".join(pkg.get("cta", [])),
                        pkg["disclosure"], pkg["channel_line"], " ".join(pkg["hashtags"])])
    tags = ", ".join(pkg["tags"])
    if len(tags) > 500:
        raise SystemExit(f"Tags dài {len(tags)} ký tự (tối đa 500).")
    t = pkg["titles"]
    for x in t:
        if len(x) > 100:
            raise SystemExit(f"Tiêu đề quá 100 ký tự: {x}")
    md = [f"# Gói đăng YouTube — {meta['title']}", "",
          f"Kênh: {pkg['channel_name']} · Thời lượng: {meta['duration']} · Nền tảng: YouTube", "",
          "## 1. Tiêu đề (chọn 1, đều khớp nội dung)", "",
          f"**Đề nghị:** `{t[meta.get('recommended_title', 0)]}`", ""]
    md += [f"{i}. `{x}`  _({len(x)} ký tự)_" for i, x in enumerate(t, 1)]
    md += ["", "## 2. Mô tả (chép nguyên khối)", "", fence(desc), "",
           f"## 3. Tags (dán vào ô Tags — {len(tags)}/500 ký tự)", "", fence(tags), "",
           "## 4. Chương (đã nằm trong mô tả)", "", fence("\n".join(chapters)), "",
           "## 5. Chữ ảnh bìa (gợi ý)", ""] + [f"- {x}" for x in pkg["thumbnail_text"]] + [
           "", "## 6. Bình luận ghim (tuỳ chọn)", "", fence(pkg["pinned_comment"]), "",
           "## 7. Kiểm trước khi đăng", "",
           "- [x] Truyện hư cấu dựng bằng AI, Sếp đã tích nhãn AI khi đăng (không cần kiểm chứng nguồn).",
           "- [ ] Đối tượng: **không** phải nội dung dành cho trẻ em.",
           "- [ ] Nghe lại video cuối (đầu, giữa, cuối) trước khi bấm đăng.",
           "- [ ] Nhạc/hình dùng đều thuộc quyền của Sếp (nhạc tổng hợp bằng code, ảnh logo của kênh).", ""]
    return "\n".join(md)


def build_msg(meta, words, nsec):
    lines = [f"✅ BÁO CÁO: {meta['title']}", "",
             f"• Chủ đề: {meta['topic']}",
             f"• Kịch bản: {format(words, ',').replace(',', '.')} từ, {nsec} phần, tiếng Anh Mỹ",
             f"• Giọng: {meta['voice']}",
             f"• Thời lượng MP3: {meta['duration_text']}",
             f"• File: {meta['file']}", ""]
    if meta.get("touched"):
        lines += ["✏️ Chỗ em đã chạm: " + meta["touched"], ""]
    lines += ["⚠️ Cần Sếp duyệt:"] + [f"{i}. {x}" for i, x in enumerate(meta["review"], 1)]
    lines += ["", "Đính kèm: gói YouTube, transcript."]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("story_dir")
    ap.add_argument("--chapters", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--story", help="file truyện đã dùng để đọc (mặc định story.txt trong thư mục truyện)")
    ap.add_argument("--channel", choices=rs.CHANNELS)
    ap.add_argument("--env-file", default=str(rs.DEFAULT_ENV))
    ap.add_argument("--send", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    sd = Path(a.story_dir)
    meta = json.loads((sd / "report_meta.json").read_text(encoding="utf-8"))
    pkg = json.loads((sd / "package.json").read_text(encoding="utf-8"))
    story = Path(a.story) if a.story else sd / meta.get("story_file", "story.txt")
    chapters = chapters_list(a.chapters)
    tr = transcript(story)
    words = len(re.sub(r"(?m)^.*—.*$|^(OPENING|FINAL|ENDING).*$", "", tr).split())
    nsec = len(re.findall(r"(?m)^(OPENING|PART|CHAPTER|FINAL|ENDING|OUTRO)", tr))
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "youtube-publishing-package.md").write_text(build_md(meta, pkg, chapters), encoding="utf-8")
    (out / "TRANSCRIPT.txt").write_text(tr, encoding="utf-8")
    msg = build_msg(meta, words, nsec)
    (out / "bao-cao.txt").write_text(msg + "\n", encoding="utf-8")
    print(msg)
    if a.dry_run or not a.send:
        print(f"\n(Chưa gửi. File đã tạo trong {out})")
        return
    if not a.channel:
        raise SystemExit("Cần --channel women|man để gửi.")
    token, chat = rs.creds(a.channel, rs.load_env(a.env_file))
    if not token or not chat:
        raise SystemExit(f"Thiếu TELEGRAM_{a.channel.upper()}_TOKEN/CHAT_ID. Không dùng khóa của kênh khác.")
    rs.api(token, "sendMessage", {"chat_id": chat, "text": msg[:4000]})
    for name in ("youtube-publishing-package.md", "TRANSCRIPT.txt"):
        rs.api(token, "sendDocument", {"chat_id": chat}, {"document": out / name})
    print("Đã gửi báo cáo + file qua Telegram.")


if __name__ == "__main__":
    main()
