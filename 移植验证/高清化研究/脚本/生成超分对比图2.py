"""规范化超分对比 v2：
  - 所有方案归一到同一显示尺寸（3 倍源尺寸）再做并排对比
  - 自动挑细节最丰富区域
  - CHR 额外做「透明边缘 + 棋盘底」检查
  - ETC 额外做文字区域检查
  - 同时输出客观指标（锐度提升、光晕、边缘过渡宽度）
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
TEST = HERE / "高清化测试"
OUT = TEST / "对比"


def font(sz: int = 18):
    try:
        return ImageFont.truetype("C:/Windows/Fonts/consola.ttf", sz)
    except Exception:  # noqa: BLE001
        return ImageFont.load_default()


def detail_window(im: Image.Image, win: int = 160) -> tuple[int, int]:
    a = np.asarray(im.convert("RGBA"), dtype=np.float32)
    alpha = a[..., 3]
    lum = a[..., 0] * 0.299 + a[..., 1] * 0.587 + a[..., 2] * 0.114
    # 只看不透明区域的细节，并给 alpha 边界加权
    gy, gx = np.gradient(lum)
    e = (np.abs(gx) + np.abs(gy)) * (alpha > 8)
    gy2, gx2 = np.gradient(alpha)
    e += 0.15 * (np.abs(gx2) + np.abs(gy2))
    ii = e.cumsum(0).cumsum(1)
    h, w = e.shape
    best, bestpos = -1.0, (0, 0)
    step = 4
    for y in range(0, max(1, h - win), step):
        for x in range(0, max(1, w - win), step):
            s = ii[y + win - 1, x + win - 1]
            if y > 0:
                s -= ii[y - 1, x + win - 1]
            if x > 0:
                s -= ii[y + win - 1, x - 1]
            if y > 0 and x > 0:
                s += ii[y - 1, x - 1]
            if s > best:
                best, bestpos = s, (x, y)
    return bestpos


def crop_region(path: Path, pos: tuple[int, int], win: int, scale: int) -> Image.Image:
    im = Image.open(path).convert("RGBA")
    x, y = pos
    return im.crop((x * scale, y * scale, (x + win) * scale, (y + win) * scale))


def normalize(img: Image.Image, size: int) -> Image.Image:
    return img.resize((size, size), Image.LANCZOS)


def tile(img: Image.Image, text: str, bg: tuple[int, int, int] = (18, 18, 18)) -> Image.Image:
    """把 RGBA 图合成到指定底色上，再加标题栏。"""
    base = Image.new("RGBA", img.size, bg + (255,))
    base.alpha_composite(img)
    canvas = Image.new("RGBA", (img.width, img.height + 28), (12, 12, 12, 255))
    canvas.paste(base, (0, 28))
    ImageDraw.Draw(canvas).text((6, 4), text, fill=(255, 240, 120, 255), font=font(17))
    return canvas


def sheet(tiles: list[Image.Image], path: Path):
    W = sum(t.width for t in tiles)
    H = max(t.height for t in tiles)
    s = Image.new("RGBA", (W, H), (0, 0, 0, 255))
    x = 0
    for t in tiles:
        s.paste(t, (x, 0))
        x += t.width
    path.parent.mkdir(parents=True, exist_ok=True)
    s.save(path)
    print(f"  → {path.name} ({s.size})")


def metrics(sr: Image.Image, src: Image.Image, factor: int, win: int) -> dict:
    """客观指标：锐度、光晕、边缘过渡宽度（越小越硬）。"""
    s = np.asarray(src.convert("RGBA"), dtype=np.float32)
    o = np.asarray(sr.convert("RGBA"), dtype=np.float32)
    # 取中间区域的亮度
    lum = o[..., 0] * 0.299 + o[..., 1] * 0.587 + o[..., 2] * 0.114
    gy, gx = np.gradient(lum)
    sharp = float((np.abs(gx) + np.abs(gy)).mean())
    # 光晕：与 3x3 中值的方向性过冲
    from scipy.ndimage import median_filter
    med = median_filter(lum, size=3)
    halo = float(np.maximum(lum - med, 0).mean() + np.maximum(med - lum, 0).mean())
    return {"sharp": sharp, "halo": halo}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    samples = [
        ("BG_0218", HERE / "输出-保护边修复/BG/BG_0218.png", [
            ("Lanczos3x", TEST / "BG_lanczos3x.png", 3)]),
        ("CHR_0000", HERE / "输出-保护边修复/CHR/CHR_0000.png", [
            ("Lanczos3x", TEST / "CHR_full_lanczos3x.png", 3)]),
        ("ETC_095", HERE / "输出-保护边修复/ETC/ETC_095.png", [
            ("Lanczos3x", TEST / "ETC_menu_lanczos3x.png", 3)]),
    ]
    # 补充：对 BG_0218 / ETC_095 也跑超分（之前跑的是 BG_0000 / ETC_000）
    print("=== 补跑代表性样本 ===")
    import subprocess
    RR = Path(r"E:\Entertainment\IS\is-pure-zh\工具\超分\realesrgan-ncnn-vulkan.exe")
    RC = Path(r"E:\Entertainment\IS\is-pure-zh\工具\超分\realcugan-ncnn-vulkan-20220728-windows\realcugan-ncnn-vulkan.exe")
    extra = {
        "BG_0218": HERE / "输出-保护边修复/BG/BG_0218.png",
        "ETC_095": HERE / "输出-保护边修复/ETC/ETC_095.png",
        "CHR_0452_bust": HERE / "输出-保护边修复/CHR/CHR_0452.png",
        "EV_0126": HERE / "输出-保护边修复/EV/EV_0126.png",
    }
    runs = [
        ("esrgan_x4anime", RR, ["-n", "realesrgan-x4plus-anime", "-g", "0"]),
        ("esrgan_v3x4", RR, ["-n", "realesr-animevideov3-x4", "-g", "0"]),
        ("cugan_up3x", RC, ["-n", "up3x-conservative", "-s", "3", "-g", "0"]),
    ]
    import time
    for key, src in extra.items():
        for tag, exe, args in runs:
            outp = TEST / f"{key}_{tag}.png"
            if outp.exists():
                continue
            t0 = time.time()
            r = subprocess.run([str(exe)] + args + ["-i", str(src), "-o", str(outp)],
                               capture_output=True, text=True, timeout=1800)
            print(f"  {key:<14} {tag:<14} {time.time()-t0:.2f}s "
                  f"{'OK' if outp.exists() else '失败 ' + (r.stderr or r.stdout)[-120:]}")
        # Lanczos 基线
        with Image.open(src) as im:
            im.resize((im.width * 3, im.height * 3), Image.LANCZOS).save(TEST / f"{key}_lanczos3x.png")

    # 逐样本生成对比图
    methods = [
        ("Lanczos3x", "lanczos3x", 3),
        ("ESRGAN-x4anime", "esrgan_x4anime", 4),
        ("ESRGAN-v3x4", "esrgan_v3x4", 4),
        ("RealCUGAN-up3x", "cugan_up3x", 3),
    ]
    for key, src in extra.items():
        win = 160 if Image.open(src).width >= 320 else 70
        pos = detail_window(Image.open(src), win)
        with Image.open(src) as im:
            raw = im.convert("RGBA").crop((pos[0], pos[1], pos[0] + win, pos[1] + win))
        tiles = [tile(normalize(raw, 480), "原始像素 (NEAREST)", (40, 40, 40))]
        tiles[0] = tile(raw.resize((480, 480), Image.NEAREST), "原始像素 (NEAREST)", (40, 40, 40))
        for label_, tag, scale in methods:
            p = TEST / f"{key}_{tag}.png"
            if not p.exists():
                continue
            crop = crop_region(p, pos, win, scale)
            tiles.append(tile(normalize(crop, 480), f"{label_} (x{scale})"))
        sheet(tiles, OUT / f"{key}_1比1对比.png")

        # CHR：透明边缘检查（叠在品红/棋盘上）
        if key.startswith("CHR"):
            tiles2 = []
            for label_, tag, scale in methods:
                p = TEST / f"{key}_{tag}.png"
                if not p.exists():
                    continue
                crop = crop_region(p, pos, win, scale)
                tiles2.append(tile(normalize(crop, 480), f"{label_} 叠色检查", (200, 0, 200)))
            sheet(tiles2, OUT / f"{key}_透明边缘检查.png")

    print(f"\n全部输出在 {OUT}")


if __name__ == "__main__":
    main()
