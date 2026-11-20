"""紧凑 2-3 联对比图（1:1 像素），用于逐张肉眼判定。"""
from __future__ import annotations

import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent.parent
SRC = HERE.parent / "输出-保护边修复"
OUT = HERE / "超分结果"
CMP = HERE / "对比图"
TOOLS = Path(r"E:\Entertainment\IS\is-pure-zh\工具\超分")
RR = TOOLS / "realesrgan-ncnn-vulkan.exe"
RC = TOOLS / "realcugan-ncnn-vulkan-20220728-windows" / "realcugan-ncnn-vulkan.exe"


def cjk_font(sz=16):
    for p in ("C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simhei.ttf",
              "C:/Windows/Fonts/msyhbd.ttc"):
        try:
            return ImageFont.truetype(p, sz)
        except Exception:  # noqa: BLE001
            continue
    return ImageFont.load_default()


def ensure(tag: str, kind: str, args, src: Path) -> Path | None:
    outp = OUT / f"{src.stem}__{tag}.png"
    if outp.exists():
        return outp
    if kind == "pil":
        filt, factor = args
        with Image.open(src) as im:
            im.convert("RGBA").resize((im.width * factor, im.height * factor),
                                      getattr(Image, filt)).save(outp)
    else:
        exe = RR if kind == "rr" else RC
        subprocess.run([str(exe)] + args + ["-i", str(src), "-o", str(outp)],
                       capture_output=True, text=True, timeout=3600)
    return outp if outp.exists() else None


def tile(img: Image.Image, w: int, h: int, text: str, bg=(38, 38, 38)) -> Image.Image:
    canvas = Image.new("RGBA", (w, h + 26), bg + (255,))
    canvas.alpha_composite(img, (0, 26))
    ImageDraw.Draw(canvas).text((6, 4), text, fill=(255, 235, 120), font=cjk_font(16))
    return canvas


def pair(name: str, src: Path, entries: list[tuple[str, str, list]], crop=None,
         out_size=512):
    """entries: [(显示名, tag, kind/args)]；crop 为源图裁切 (x,y,w,h)"""
    tiles = []
    for disp, tag, spec in entries:
        if tag == "source":
            im = Image.open(src).convert("RGBA")
            if crop:
                x, y, cw, ch = crop
                im = im.crop((x, y, x + cw, y + ch))
            factor = max(1, out_size // max(im.width, im.height))
            im = im.resize((im.width * factor, im.height * factor), Image.NEAREST)
        else:
            kind, args = spec
            p = ensure(tag, kind, args, src)
            if not p:
                continue
            rimg = Image.open(p).convert("RGBA")
            if crop:
                # 需要知道真实倍数
                factor = rimg.width // Image.open(src).width
                x, y, cw, ch = crop
                rimg = rimg.crop((x * factor, y * factor, (x + cw) * factor, (y + ch) * factor))
            im = rimg
        # 统一到 out_size（等比，用 LANCZOS；仅用于并排展示，不代表最终资产）
        k = out_size / max(im.width, im.height)
        im2 = im.resize((max(1, round(im.width * k)), max(1, round(im.height * k))), Image.LANCZOS)
        tiles.append(tile(im2, out_size, out_size, disp))
    total_w = sum(t.width for t in tiles)
    total_h = max(t.height for t in tiles)
    sheet = Image.new("RGBA", (total_w, total_h), (0, 0, 0, 255))
    x = 0
    for t in tiles:
        sheet.paste(t, (x, 0))
        x += t.width
    CMP.mkdir(parents=True, exist_ok=True)
    path = CMP / f"{name}.png"
    sheet.save(path)
    print(f"  {path.name} {sheet.size}")


def main():
    # 1) 半身像 140×130（整体，等比放大到 512）
    pair("半身像_整图对比", SRC / "CHR/CHR_0452.png", [
        ("原始 NEAREST x4", "source", None),
        ("ESRGAN-v3 x4", "esrgan_v3_x4", ("rr", ["-n", "realesr-animevideov3", "-s", "4", "-g", "0"])),
    ], out_size=512)

    # 2) 背景 BG_0218（裁 160×160 细节区）
    pair("背景_细节对比", SRC / "BG/BG_0218.png", [
        ("原始 NEAREST x4", "source", None),
        ("ESRGAN-v3 x4", "esrgan_v3_x4", ("rr", ["-n", "realesr-animevideov3", "-s", "4", "-g", "0"])),
    ], crop=(240, 120, 160, 160), out_size=512)

    # 3) 立绘脸部（CHR_0000 裁脸部）
    pair("立绘脸部_对比", SRC / "CHR/CHR_0000.png", [
        ("原始 NEAREST x4", "source", None),
        ("ESRGAN-v3 x4", "esrgan_v3_x4", ("rr", ["-n", "realesr-animevideov3", "-s", "4", "-g", "0"])),
    ], crop=(250, 100, 160, 160), out_size=512)

    # 4) UI 面板 ETC_017_p10（376×280）
    pair("UI面板_对比", SRC / "ETC/ETC_017_p10.png", [
        ("原始 NEAREST x2", "source", None),
        ("ESRGAN-v3 x4", "esrgan_v3_x4", ("rr", ["-n", "realesr-animevideov3", "-s", "4", "-g", "0"])),
        ("RealCUGAN x3", "cugan_up3x", ("rc", ["-n", "up3x-conservative", "-s", "3", "-g", "0"])),
    ], out_size=420)


if __name__ == "__main__":
    main()
