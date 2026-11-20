"""验证透明边缘质量 + 统计存储/耗时成本。"""
from __future__ import annotations

import subprocess
import time
from collections import Counter
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent.parent
SRC = HERE.parent / "输出-保护边修复"
OUT = HERE / "超分结果"
CMP = HERE / "对比图"
TOOLS = Path(r"E:\Entertainment\IS\is-pure-zh\工具\超分")
RR = TOOLS / "realesrgan-ncnn-vulkan.exe"


def cjk(sz=16):
    try:
        return ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", sz)
    except Exception:  # noqa: BLE001
        return ImageFont.load_default()


def edge_composite_test():
    """把 CHR 立绘放大结果合成到棋盘/彩色背景上，检查透明边缘是否出现光晕/白边。"""
    src = SRC / "CHR/CHR_0000.png"
    variants = {
        "原始 NEAREST x4": None,
        "ESRGAN-v3 x4": OUT / "CHR_0000__esrgan_v3_x4.png",
        "Lanczos x4": OUT / "CHR_0000__lanczos4.png",
    }
    # 裁一块含轮廓边缘的区域（头部右上方）
    crop = (330, 40, 130, 130)
    tiles = []
    for name, p in variants.items():
        if p is None:
            im = Image.open(src).convert("RGBA")
            im = im.resize((im.width * 4, im.height * 4), Image.NEAREST)
            f = 4
        else:
            if not p.exists():
                print(f"  [缺] {p.name}")
                continue
            im = Image.open(p).convert("RGBA")
            f = im.width // Image.open(src).width
        x, y, cw, ch = crop
        part = im.crop((x * f, y * f, (x + cw) * f, (y + ch) * f))
        # 合成到高饱和蓝底（最容易暴露白边/黑边）
        canvas = Image.new("RGBA", part.size, (0, 90, 200, 255))
        canvas.alpha_composite(part)
        canvas = canvas.convert("RGB").resize((420, 420), Image.LANCZOS)
        bar = Image.new("RGB", (420, 26), (12, 12, 12))
        ImageDraw.Draw(bar).text((6, 4), name, fill=(255, 235, 120), font=cjk(15))
        t = Image.new("RGB", (420, 446))
        t.paste(bar, (0, 0))
        t.paste(canvas, (0, 26))
        tiles.append(t)
    W = 420 * len(tiles)
    sheet = Image.new("RGB", (W, 446), (0, 0, 0))
    for i, t in enumerate(tiles):
        sheet.paste(t, (i * 420, 0))
    CMP.mkdir(parents=True, exist_ok=True)
    path = CMP / "透明边缘_叠底检查.png"
    sheet.save(path)
    print(f"  透明边缘检查 → {path.name} {sheet.size}")


def storage_and_speed():
    print("\n=== 现有超分结果体积 ===")
    rows = []
    for p in sorted(OUT.glob("*__esrgan_v3_x4.png")):
        im = Image.open(p)
        rows.append((p.name, im.size, p.stat().st_size / 1048576))
    for n, sz, mb in rows:
        print(f"  {n:<44} {str(sz):<14} {mb:6.2f} MB")
    if rows:
        avg = sum(r[2] for r in rows) / len(rows)
        print(f"  平均 {avg:.2f} MB/张")

    print("\n=== 批量耗时抽样（20 张混合样本）===")
    samples = (sorted((SRC / "BG").glob("*.png"))[:5]
               + sorted((SRC / "CHR").glob("*.png"))[:10]
               + sorted((SRC / "EV").glob("*.png"))[:5])
    t0 = time.time()
    done = 0
    for p in samples:
        outp = OUT / f"_bench_{p.stem}.png"
        subprocess.run([str(RR), "-n", "realesr-animevideov3", "-s", "4", "-g", "0",
                        "-i", str(p), "-o", str(outp)],
                       capture_output=True, text=True, timeout=600)
        if outp.exists():
            done += 1
            outp.unlink()
    dt = time.time() - t0
    print(f"  {done} 张用时 {dt:.1f}s → 平均 {dt/max(done,1):.2f}s/张")
    print(f"  推算 1886 张（BG+CHR+EV+ETC）≈ {dt/max(done,1)*1886/60:.0f} 分钟")


def main():
    edge_composite_test()
    storage_and_speed()


if __name__ == "__main__":
    main()
