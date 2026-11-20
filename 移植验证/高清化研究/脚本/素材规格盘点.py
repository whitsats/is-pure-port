"""盘点待高清化素材：尺寸分布、色彩模式、透明通道、体积。"""
from __future__ import annotations

from collections import Counter
from pathlib import Path

from PIL import Image

BASE = Path(__file__).resolve().parent / "输出-保护边修复"
GROUPS = ["BG", "CHR", "EV", "ETC", "BG_thumb", "CHR_thumb", "EV_thumb", "BGM", "_总览", "_重点核对"]


def main():
    grand = 0
    print(f"{'目录':<12} {'文件':>6} {'尺寸分布':<46} {'模式':<14} {'体积MB':>8}")
    for g in GROUPS:
        d = BASE / g
        if not d.exists():
            continue
        sizes = Counter()
        modes = Counter()
        total = 0
        for p in d.glob("*.png"):
            try:
                with Image.open(p) as im:
                    sizes[im.size] += 1
                    modes[im.mode] += 1
                total += p.stat().st_size
            except Exception:  # noqa: BLE001
                pass
        grand += total
        top = ", ".join(f"{w}×{h}×{n}" for (w, h), n in sizes.most_common(4))
        mtop = ", ".join(f"{m}×{n}" for m, n in modes.most_common(3))
        print(f"{g:<12} {sum(sizes.values()):>6} {top:<46} {mtop:<14} {total/1048576:>8.1f}")
    print(f"\n合计 {grand/1048576:.1f} MB")

    # 尺寸直方图（按面积排序）
    print("\n=== 全部素材尺寸明细（按数量）===")
    allsizes = Counter()
    for g in ("BG", "CHR", "EV", "ETC"):
        d = BASE / g
        if not d.exists():
            continue
        for p in d.glob("*.png"):
            with Image.open(p) as im:
                allsizes[(g, im.size)] += 1
    for (g, (w, h)), n in sorted(allsizes.items(), key=lambda x: -x[1]):
        print(f"  {g:<5} {w:>4}×{h:<4} × {n:>5}  （面积比 640×448 = {w*h/(640*448):.2f}）")


if __name__ == "__main__":
    main()
