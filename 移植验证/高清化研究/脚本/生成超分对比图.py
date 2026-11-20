"""生成超分对比图：自动挑选细节最丰富的区域，把各方案结果并排放大对比。"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
TEST = HERE / "高清化测试"
OUT = TEST / "对比"


def detail_window(im: Image.Image, win: int = 160) -> tuple[int, int]:
    """在图像里找细节（梯度能量）最丰富的 win×win 窗口。"""
    a = np.asarray(im.convert("LA"), dtype=np.float32)
    lum = a[..., 0]
    gy, gx = np.gradient(lum)
    e = np.abs(gx) + np.abs(gy)
    # 积分图加速
    ii = e.cumsum(0).cumsum(1)
    h, w = e.shape
    best, bestpos = -1.0, (0, 0)
    step = 8
    for y in range(0, h - win, step):
        for x in range(0, w - win, step):
            s = (ii[y + win - 1, x + win - 1]
                 - (ii[y - 1, x + win - 1] if y > 0 else 0)
                 - (ii[y + win - 1, x - 1] if x > 0 else 0)
                 + (ii[y - 1, x - 1] if (y > 0 and x > 0) else 0))
            if s > best:
                best, bestpos = s, (x, y)
    return bestpos


def crop_scaled(path: Path, pos: tuple[int, int], win: int, scale: int) -> Image.Image:
    im = Image.open(path).convert("RGBA")
    x, y = pos
    box = (x * scale, y * scale, (x + win) * scale, (y + win) * scale)
    return im.crop(box)


def label(img: Image.Image, text: str, height: int = 28) -> Image.Image:
    canvas = Image.new("RGBA", (img.width, img.height + height), (16, 16, 16, 255))
    canvas.paste(img, (0, height))
    dr = ImageDraw.Draw(canvas)
    try:
        font = ImageFont.truetype("C:/Windows/Fonts/consola.ttf", 18)
    except Exception:  # noqa: BLE001
        font = ImageFont.load_default()
    dr.text((6, 4), text, fill=(255, 255, 120, 255), font=font)
    return canvas


def build_pair(name: str, source: Path, methods: list[tuple[str, Path, int]], win: int = 160):
    """methods: [(显示名, 结果路径, 放大倍数)]"""
    pos = detail_window(Image.open(source), win)
    tiles = []
    # 原始像素（NEAREST x3）作为“现状”参考
    with Image.open(source) as im:
        x, y = pos
        raw = im.convert("RGBA").crop((x, y, x + win, y + win))
    tiles.append(label(raw.resize((win * 3, win * 3), Image.NEAREST), "原始像素 (NEAREST x3)"))
    for mname, path, scale in methods:
        if not path.exists():
            continue
        tiles.append(label(crop_scaled(path, pos, win, scale), f"{mname} (x{scale})"))
    if not tiles:
        return
    W = sum(t.width for t in tiles)
    H = max(t.height for t in tiles)
    sheet = Image.new("RGBA", (W, H), (0, 0, 0, 255))
    x = 0
    for t in tiles:
        sheet.paste(t, (x, 0))
        x += t.width
    OUT.mkdir(parents=True, exist_ok=True)
    sheet.save(OUT / f"{name}_对比.png")
    print(f"  {name}: 裁切区域 ({pos[0]},{pos[1]}) → {OUT / f'{name}_对比.png'} ({sheet.size})")


def main():
    # 1) BG
    build_pair("BG_0000", HERE / "输出-保护边修复/BG/BG_0000.png", [
        ("Lanczos3x", TEST / "BG_lanczos3x.png", 3),
        ("ESRGAN-x4anime", TEST / "BG_esrgan_x4anime.png", 4),
        ("ESRGAN-v3", TEST / "BG_esrgan_v3x4.png", 4),
        ("RealCUGAN-up3x", TEST / "BG_cugan_up3x.png", 3),
    ])
    # 2) CHR 全身
    build_pair("CHR_0000", HERE / "输出-保护边修复/CHR/CHR_0000.png", [
        ("Lanczos3x", TEST / "CHR_full_lanczos3x.png", 3),
        ("ESRGAN-x4anime", TEST / "CHR_full_esrgan_x4anime.png", 4),
        ("ESRGAN-v3", TEST / "CHR_full_esrgan_v3x4.png", 4),
        ("RealCUGAN-up3x", TEST / "CHR_full_cugan_up3x.png", 3),
    ])
    # 3) EV
    build_pair("EV_0000", HERE / "输出-保护边修复/EV/EV_0000.png", [
        ("Lanczos3x", TEST / "EV_lanczos3x.png", 3),
        ("ESRGAN-x4anime", TEST / "EV_esrgan_x4anime.png", 4),
        ("ESRGAN-v3", TEST / "EV_esrgan_v3x4.png", 4),
        ("RealCUGAN-up3x", TEST / "EV_cugan_up3x.png", 3),
    ])
    # 4) ETC 菜单（文字可读性）
    etc = sorted((HERE / "输出-保护边修复/ETC").glob("*.png"))
    menu = next((p for p in etc if Image.open(p).size == (640, 448)), None)
    if menu:
        build_pair("ETC_" + menu.stem, menu, [
            ("Lanczos3x", TEST / "ETC_menu_lanczos3x.png", 3),
            ("ESRGAN-x4anime", TEST / "ETC_menu_esrgan_x4anime.png", 4),
            ("ESRGAN-v3", TEST / "ETC_menu_esrgan_v3x4.png", 4),
            ("RealCUGAN-up3x", TEST / "ETC_menu_cugan_up3x.png", 3),
        ])


if __name__ == "__main__":
    main()
