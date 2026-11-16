"""重点核对图：对比旧(32含保护边)与新(30剥保护边)在用户指出的下颌/耳朵区域。

输出到 输出-保护边修复/_重点核对/
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent))
import decode_clean_30 as dc  # noqa: E402
import 输出保护边修复素材 as new  # noqa: E402
import 对照验证_新旧规则 as cmp  # noqa: E402

from 本地路径 import ORIGINAL_ISO

ISO = ORIGINAL_ISO
OUT = new.OUT_ROOT / "_重点核对"
CHR = 106958848


def render(idx: int, scale: int = 8, box=None) -> tuple[Image.Image, Image.Image]:
    with ISO.open("rb") as f:
        raw = cmp.grab(f, CHR, idx)
    ow, oh, orgba = cmp.old_decode_32(raw)
    nw, nh, nrgba, _ = new.decode_chr(raw)
    old = cmp.to_img(ow, oh, orgba)
    newimg = cmp.to_img(nw, nh, nrgba)

    def crop_resize(img):
        if box is None:
            a = np.array(img)
            ys, xs = np.where(a[:, :, 3] > 0)
            img = img.crop((int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1))
        else:
            img = img.crop(box)
        return img.resize((img.width * scale, img.height * scale), Image.LANCZOS)

    return crop_resize(old), crop_resize(newimg)


def labeled(img: Image.Image, text: str) -> Image.Image:
    out = Image.new("RGB", (img.width, img.height + 22), (28, 32, 40))
    bg = Image.new("RGBA", img.size, (210, 210, 214, 255))
    bg.alpha_composite(img, (0, 0))
    out.paste(bg.convert("RGB"), (0, 22))
    ImageDraw.Draw(out).text((4, 5), text, fill=(255, 230, 80))
    return out


def main() -> None:
    OUT.mkdir(exist_ok=True)
    for idx in (2792, 2840, 2852, 2768):
        old, newimg = render(idx, scale=8)
        a = labeled(old, f"CHR {idx}  旧规则 32px 含保护边")
        b = labeled(newimg, f"CHR {idx}  新规则 30px 剥保护边")
        sheet = Image.new("RGB", (a.width + b.width + 16, max(a.height, b.height)), (16, 18, 22))
        sheet.paste(a, (0, 0))
        sheet.paste(b, (a.width + 16, 0))
        sheet.save(OUT / f"CHR{idx}_旧vs新_8x.png")
        print("saved", OUT / f"CHR{idx}_旧vs新_8x.png")


if __name__ == "__main__":
    main()
