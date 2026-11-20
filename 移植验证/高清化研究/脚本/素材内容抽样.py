"""检查素材内容分布：alpha 覆盖率、亮度、细节量，用于挑选有代表性的样本。"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

BASE = Path(__file__).resolve().parent / "输出-保护边修复"


def stats(path: Path):
    im = Image.open(path).convert("RGBA")
    a = np.asarray(im, dtype=np.float32)
    alpha = a[..., 3]
    cov = float((alpha > 8).mean())
    lum = (a[..., 0] * 0.299 + a[..., 1] * 0.587 + a[..., 2] * 0.114)
    gy, gx = np.gradient(lum)
    detail = float((np.abs(gx) + np.abs(gy)).mean())
    return im.size, cov, float(lum.mean()), detail


def main():
    print("=== BG 抽样（找覆盖完整、有细节的）===")
    rows = []
    for p in sorted((BASE / "BG").glob("*.png")):
        sz, cov, lum, det = stats(p)
        rows.append((det, p.name, sz, cov, lum))
    for det, name, sz, cov, lum in sorted(rows, reverse=True)[:10]:
        print(f"  {name:<14} {sz} 覆盖{cov*100:5.1f}% 亮度{lum:6.1f} 细节{det:6.2f}")

    print("\n=== CHR 抽样 ===")
    rows = []
    for p in sorted((BASE / "CHR").glob("*.png"))[:400]:
        sz, cov, lum, det = stats(p)
        rows.append((det, p.name, sz, cov, lum))
    for det, name, sz, cov, lum in sorted(rows, reverse=True)[:10]:
        print(f"  {name:<14} {sz} 覆盖{cov*100:5.1f}% 亮度{lum:6.1f} 细节{det:6.2f}")

    print("\n=== ETC 640×448 抽样 ===")
    rows = []
    for p in sorted((BASE / "ETC").glob("*.png")):
        sz, cov, lum, det = stats(p)
        if sz == (640, 448):
            rows.append((det, p.name, sz, cov, lum))
    for det, name, sz, cov, lum in sorted(rows, reverse=True)[:10]:
        print(f"  {name:<14} {sz} 覆盖{cov*100:5.1f}% 亮度{lum:6.1f} 细节{det:6.2f}")

    print("\n=== EV 抽样 ===")
    rows = []
    for p in sorted((BASE / "EV").glob("*.png")):
        sz, cov, lum, det = stats(p)
        rows.append((det, p.name, sz, cov, lum))
    for det, name, sz, cov, lum in sorted(rows, reverse=True)[:6]:
        print(f"  {name:<14} {sz} 覆盖{cov*100:5.1f}% 亮度{lum:6.1f} 细节{det:6.2f}")


if __name__ == "__main__":
    main()
