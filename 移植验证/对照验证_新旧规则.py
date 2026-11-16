"""新旧解码规则对照验证：用游戏自带的 TIM2 缩略图（独立真值）评分数。

对每类各取若干条目：
  - 旧规则：32px 步长、不剥保护边（chr_body.py 的模型）
  - 新规则：30px 步长、剥 1px 保护边（decode_clean_30 的规则）
把两者分别降采样到缩略图尺寸，与 TIM2 缩略图逐像素比较，算平均色差。
分数越低越接近真值。
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import decode_clean_30 as dc  # noqa: E402
import 输出保护边修复素材 as new  # noqa: E402

from 本地路径 import ORIGINAL_ISO

ISO = ORIGINAL_ISO
BASE = {"CHR": 106958848, "BG": 636928, "EV": 343689216}


def grab(f, base, idx):
    f.seek(base + 8 + idx * 8)
    off, ln = struct.unpack("<II", f.read(8))
    if not off or not ln:
        return None
    f.seek(base + off)
    return dc.unpack_lzss(f.read(ln))


def old_decode_32(raw: bytes):
    """旧规则：32px 步长、含保护边、按部件表拼到 30 步长前的 32 步长画布。"""
    cnt = struct.unpack_from("<I", raw, 0)[0]
    ptrs = struct.unpack_from(f"<{cnt}I", raw, 4)
    sec0, hs = ptrs[0], ptrs[-2]
    n_rect, cx, cy, cw, ch, fmt = struct.unpack_from("<IHHHHH", raw, sec0)
    rects = [struct.unpack_from("<BBBBHH", raw, sec0 + 16 + r * 8) for r in range(n_rect)]
    max_w = max([cw] + [(gx + gw) * 32 for gx, _, gw, _, _, _ in rects])
    max_h = max([ch] + [(gy + gh) * 32 for _, gy, _, gh, _, _ in rects])
    canvas = bytearray(max_w * max_h * 4)
    tile = 0
    for gx, gy, gw, gh, _r, end_tile in rects:
        for j in range(gh):
            for i in range(gw):
                sy, sx = tile // 32, tile % 32
                for py in range(32):
                    dy = (gy + j) * 32 + py
                    if dy >= max_h:
                        continue
                    src_row = hs + ((sy * 32 + py) * 1024 + sx * 32) * 4
                    dst_row = (dy * max_w + (gx + i) * 32) * 4
                    for px in range(32):
                        sp = src_row + px * 4
                        a8 = min(255, (raw[sp + 3] * 255 + 64) // 128)
                        if a8 > 0:
                            dp = dst_row + px * 4
                            canvas[dp : dp + 4] = bytes((raw[sp], raw[sp + 1], raw[sp + 2], a8))
                tile += 1
        if end_tile > tile:
            tile = end_tile
    out = bytearray(cw * ch * 4)
    for y in range(ch):
        s_off = ((cy + y) * max_w + cx) * 4
        out[y * cw * 4 : (y + 1) * cw * 4] = canvas[s_off : s_off + cw * 4]
    return cw, ch, out


def to_img(w, h, rgba):
    a = np.frombuffer(bytes(rgba), np.uint8).reshape(h, w, 4).copy()
    return Image.fromarray(a, "RGBA")


def score(img: Image.Image, thumb: Image.Image):
    """缩略图对比：两边先裁到内容包围盒，再统一缩到缩略图尺寸，比较 RGBA。"""
    t = thumb.convert("RGBA")
    tw, th = t.size
    a = np.array(img.convert("RGBA"))
    ys, xs = np.where(a[:, :, 3] > 0)
    if not len(ys):
        return None
    crop = img.crop((int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1))
    small = crop.convert("RGBA").resize((tw, th), Image.Resampling.LANCZOS)
    sa = np.array(small).astype(np.int16)
    ta = np.array(t).astype(np.int16)
    rgb = np.abs(sa[:, :, :3] - ta[:, :, :3]).mean()
    return rgb


def main():
    picks = {
        "CHR": [2792, 2840, 2852, 2768, 2894, 2, 8, 14, 20, 26, 32, 38, 44],
        "BG": [12, 14, 16, 18, 20, 40, 80, 120, 160, 200, 240],
        "EV": [0, 2, 4, 6],
    }
    with ISO.open("rb") as f:
        for kind, indices in picks.items():
            base = BASE[kind]
            print(f"\n=== {kind} ===")
            print(f"{'条目':>6} {'缩略图':>9} | {'旧(32含边)':>10} {'新(30剥边)':>10} | 谁更好")
            wins = {"old": 0, "new": 0, "tie": 0}
            for idx in indices:
                raw = grab(f, base, idx)
                thumb_raw = grab(f, base, idx + 1)
                if raw is None or thumb_raw is None:
                    print(f"{idx:>6} 缺数据")
                    continue
                t = new.decode_tim2(thumb_raw)
                if t is None:
                    print(f"{idx:>6} 缩略图无法解析")
                    continue
                thumb = to_img(*t)
                ow, oh, orgba = old_decode_32(raw)
                nw, nh, nrgba, _ = new.decode_chr(raw)
                so = score(to_img(ow, oh, orgba), thumb)
                sn = score(to_img(nw, nh, nrgba), thumb)
                if so is None or sn is None:
                    print(f"{idx:>6} 空图")
                    continue
                if abs(so - sn) < 0.5:
                    verdict = "≈持平"
                    wins["tie"] += 1
                elif sn < so:
                    verdict = "新更好"
                    wins["new"] += 1
                else:
                    verdict = "旧更好"
                    wins["old"] += 1
                print(f"{idx:>6} {thumb.size[0]:>4}x{thumb.size[1]:<4} | {so:>10.2f} {sn:>10.2f} | {verdict}")
            print(f"  汇总：新更好 {wins['new']}，旧更好 {wins['old']}，持平 {wins['tie']}")


if __name__ == "__main__":
    main()
