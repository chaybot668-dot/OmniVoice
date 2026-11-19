#!/usr/bin/env python3
"""Chuyển kịch bản gốc (mỗi câu một dòng) thành story.txt để đọc.

KHÔNG sửa chữ nào. Chỉ (1) gộp các dòng ngắn liền nhau thành đoạn ~35-85 từ để đọc liền mạch
(đọc từng câu rời sẽ máy móc và có quá nhiều khoảng lặng), (2) gắn nhãn cảm xúc A-H cho từng phần.

  python scripts/prepare_story.py stories/second-phone/original_script.txt stories/second-phone/story.txt
"""
import re
import sys
from pathlib import Path

# Chế độ cảm xúc mặc định cho từng phần (chỉ chỉnh nhịp đọc). Theo thứ tự phần trong kịch bản.
SECTION_MODES = ["A", "C", "C", "D", "C", "D", "C", "G", "H"]
MIN_W, MAX_W = 35, 85


def group(lines):
    paras, cur = [], []
    for ln in lines:
        cur.append(ln)
        n = sum(len(x.split()) for x in cur)
        ends = ln.rstrip()[-1] in '.!?"”'
        lead_in = ln.rstrip().endswith(":")  # câu dẫn vào lời thoại: giữ chung với dòng sau
        if not lead_in and ((n >= MIN_W and ends) or n >= MAX_W):
            paras.append(" ".join(cur))
            cur = []
    if cur:
        if paras and sum(len(x.split()) for x in cur) < 15:
            paras[-1] += " " + " ".join(cur)
        else:
            paras.append(" ".join(cur))
    return paras


def main(src, dst):
    text = Path(src).read_text(encoding="utf-8")
    out = []
    for k, block in enumerate(re.split(r"(?m)^## ", text)[1:]):
        title, body = block.split("\n", 1)
        lines = [l.strip() for l in body.split("\n") if l.strip()]
        mode = SECTION_MODES[k] if k < len(SECTION_MODES) else "A"
        out.append(f"## {title.strip()}\n")
        out += [f"[{mode}]\n{p}\n" for p in group(lines)]
    Path(dst).write_text("\n".join(out), encoding="utf-8")
    # Kiểm tra không mất/không thêm chữ nào.
    a = " ".join(re.sub(r"(?m)^(#.*|\[[A-H]\])$", "", text).split())
    b = " ".join(re.sub(r"(?m)^(#.*|\[[A-H]\])$", "", Path(dst).read_text(encoding="utf-8")).split())
    assert a.split() == b.split(), "Chữ bị thay đổi!"
    print(f"OK: {dst} (chữ giữ nguyên, {len(b.split())} từ)")


if __name__ == "__main__":
    main(*sys.argv[1:3])
