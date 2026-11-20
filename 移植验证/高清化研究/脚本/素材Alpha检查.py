"""检查素材 alpha 结构：BG 的不透明区域在哪、CHR/ETC 的覆盖形态。"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

BASE = Path(__file__).resolve().parent / "输出-保护边修复"
OUT = Path(__file__).resolve().parent / "高清化测试"


def checker(w: int, h: int, s: int = 16) -> Image.Image:
    im = Image.new("RGB", (w, h), (60, 60, 60))
    dr = ImageDraw.Draw(im)
    for y in range(0, h, s):
        for x in range(0, w, s):
            if ((x // s) + (y // s)) % 2 == 0:
                dr.rectangle([x, y, x + s - 1, y + s - 1], fill=(90, 90, 90))
    return im


def compose(path: Path, scale: float = 1.0) -> Image.Image:
    im = Image.open(path).convert("RGBA")
    w, h = im.size
    bg = checker(w, h)
    bg.paste(im, (0, 0), im)
    if scale != 1.0:
        bg = bg.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    return bg


def alpha_profile(path: Path) -> str:
    im = Image.open(path).convert("RGBA")
    a = np.asarray(im)[..., 3]
    rows = (a > 8).mean(axis=1)   # 每行不透明比例
    cols = (a > 8).mean(axis=0)
    ys = np.where(rows > 0.05)[0]
    xs = np.where(cols > 0.05)[0]
    if len(ys) == 0 or len(xs) == 0:
        return "全透明"
    return (f"不透明 bbox x={xs[0]}..{xs[-1]} y={ys[0]}..{ys[-1]} "
            f"({xs[-1]-xs[0]+1}×{ys[-1]-ys[0]+1})")


def main():
    OUT.mkdir(exist_ok=True)
    picks = [
        ("BG_0218", BASE / "BG/BG_0218.png"),
        ("BG_0000", BASE / "BG/BG_0000.png"),
        ("CHR_0452_bust", BASE / "CHR/CHR_0452.png"),
        ("ETC_095", BASE / "ETC/ETC_095.png"),
        ("ETC_089", BASE / "ETC/ETC_089.png"),
        ("EV_0126", BASE / "EV/EV_0126.png"),
    ]
    tiles = []
    for name, p in picks:
        if not p.exists():
            continue
        print(f"{name:<16} {Image.open(p).size}  {alpha_profile(p)}")
        im = compose(p)
        tiles.append((name, im))

    # 拼成一张对照表（每格缩放到 640 宽）
    cell_w = 640
    cells = []
    for name, im in tiles:
        h = int(im.height * cell_w / im.width)
        cells.append((name, im.resize((cell_w, h), Image.LANCZOS)))
    total_h = sum(c[1].height + 26 for c in cells)
    sheet = Image.new("RGB", (cell_w, total_h), (20, 20, 20))
    dr = ImageDraw.Draw(sheet)
    y = 0
    for name, im in cells:
        dr.text((6, y + 5), name, fill=(255, 255, 120))
        sheet.paste(im, (0, y + 26))
        y += im.height + 26
    sheet.save(OUT / "素材内容概览.png")
    print(f"\n已保存 {OUT / '素材内容概览.png'} ({sheet.size})")


if __name__ == "__main__":
    main()
