"""生成验证用总览图（contact sheet），便于快速人工核对。

输出：
  输出-保护边修复/_总览/CHR_pageNN.png   每页 96 张（12x8），按条目号排序
  输出-保护边修复/_总览/BG_pageNN.png    每页 40 张（8x5）
  输出-保护边修复/_总览/EV_pageNN.png    每页 40 张（8x5）
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent))
import 输出保护边修复素材 as new  # noqa: E402

OUT = new.OUT_ROOT
SHEET = OUT / "_总览"
CELL = 120
COLS, ROWS = 12, 8


def collect(kind: str) -> list[Path]:
    d = OUT / kind
    files = sorted(d.glob(f"{kind}_[0-9]*.png"))
    return [p for p in files if "thumb" not in p.name]


def build_kind(kind: str, cell: int = CELL, cols: int = COLS, rows: int = ROWS) -> int:
    files = collect(kind)
    if not files:
        print(f"{kind}: 无文件")
        return 0
    per = cols * rows
    SHEET.mkdir(exist_ok=True)
    n_pages = 0
    for page_start in range(0, len(files), per):
        chunk = files[page_start : page_start + per]
        sheet = Image.new("RGB", (cols * cell, rows * cell), (32, 36, 44))
        dr = ImageDraw.Draw(sheet)
        for n, path in enumerate(chunk):
            try:
                im = Image.open(path).convert("RGBA")
            except Exception:  # noqa: BLE001
                continue
            # 等比缩进 cell-14 的框内，居中
            box = cell - 16
            im.thumbnail((box, box), Image.Resampling.LANCZOS)
            cx = (n % cols) * cell
            cy = (n // cols) * cell
            # 灰底衬托半透明
            bg = Image.new("RGBA", (cell, cell), (210, 210, 214, 255))
            bg.alpha_composite(im, ((cell - im.width) // 2, 2))
            sheet.paste(bg.convert("RGB"), (cx, cy))
            dr.text((cx + 2, cy + cell - 12), path.stem.split("_")[-1], fill=(255, 255, 0))
        out = SHEET / f"{kind}_page{n_pages:02d}.png"
        sheet.save(out)
        n_pages += 1
    print(f"{kind}: {len(files)} 张 -> {n_pages} 页 ({SHEET})")
    return n_pages


if __name__ == "__main__":
    for kind in ("CHR", "BG", "EV"):
        build_kind(kind)
