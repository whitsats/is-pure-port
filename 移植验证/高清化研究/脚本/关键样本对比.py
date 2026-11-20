"""对关键样本跑超分并生成 1:1 堆叠对比图。

样本：
  - ETC_011_p2（264×32 的 "OPTION" 按钮，文字可读性关键）
  - CHR_0452（140×130 半身像，最低分辨率）
  - BG_0218（640×280 实际画面的背景）
  - ETC_017_p10（376×280 UI 面板）
"""
from __future__ import annotations

import subprocess
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent.parent
SRC = HERE.parent / "输出-保护边修复"
OUT = HERE / "超分结果"
CMP = HERE / "对比图"
TOOLS = Path(r"E:\Entertainment\IS\is-pure-zh\工具\超分")
RR = TOOLS / "realesrgan-ncnn-vulkan.exe"
RC = TOOLS / "realcugan-ncnn-vulkan-20220728-windows" / "realcugan-ncnn-vulkan.exe"

SAMPLES = {
    "UI_OPTION": SRC / "ETC/ETC_011_p2.png",
    "UI_PANEL": SRC / "ETC/ETC_017_p10.png",
    "BUST_0452": SRC / "CHR/CHR_0452.png",
    "BG_0218": SRC / "BG/BG_0218.png",
}

METHODS = [
    ("nearest4", "pil", ("NEAREST", 4)),
    ("lanczos4", "pil", ("LANCZOS", 4)),
    ("esrgan_v3_x4", "rr", ["-n", "realesr-animevideov3", "-s", "4", "-g", "0"]),
    ("cugan_up3x", "rc", ["-n", "up3x-conservative", "-s", "3", "-g", "0"]),
]


def label(txt: str, w: int, h: int = 24) -> Image.Image:
    bar = Image.new("RGB", (w, h), (12, 12, 12))
    try:
        f = ImageFont.truetype("C:/Windows/Fonts/consola.ttf", 16)
    except Exception:  # noqa: BLE001
        f = ImageFont.load_default()
    ImageDraw.Draw(bar).text((6, 4), txt, fill=(255, 235, 120), font=f)
    return bar


def run(tag: str, kind: str, args, src: Path) -> Path | None:
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


def stack_compare(key: str, src: Path, title: str, bg=(40, 40, 40)):
    with Image.open(src) as im:
        w, h = im.size
    base_w = w * 4
    rows = [label(f"{title}  原始像素 NEAREST x4（{w}×{h}）", base_w)]
    ref = run("nearest4", "pil", ("NEAREST", 4), src)
    rows.append(Image.open(ref).convert("RGBA").resize((base_w, h * 4), Image.NEAREST))
    for tag, kind, args in METHODS:
        if tag == "nearest4":
            continue
        p = run(tag, kind, args, src)
        if not p:
            continue
        rimg = Image.open(p).convert("RGBA")
        factor = rimg.width // w
        # 统一到 ×4 画布：按各自真实倍数 1:1 放置（不缩放）
        canvas = Image.new("RGBA", (base_w, h * 4), bg + (255,))
        canvas.alpha_composite(rimg)  # 左上角对齐，剩余部分露底色
        rows.append(label(f"{tag}（真实 x{factor}：{rimg.width}×{rimg.height}，1:1 放置，未缩放）", base_w))
        rows.append(canvas)

    total_h = sum(r.height for r in rows)
    sheet = Image.new("RGBA", (base_w, total_h), (0, 0, 0, 255))
    y = 0
    for r in rows:
        sheet.paste(r if r.mode == "RGBA" else r.convert("RGBA"), (0, y))
        y += r.height
    CMP.mkdir(parents=True, exist_ok=True)
    path = CMP / f"{key}_1比1堆叠.png"
    sheet.save(path)
    print(f"  {key}: {path.name} {sheet.size}")


def main():
    OUT.mkdir(exist_ok=True)
    for key, src in SAMPLES.items():
        if src.exists():
            stack_compare(key, src, src.name)
        else:
            print(f"[跳过] {key}")


if __name__ == "__main__":
    main()
