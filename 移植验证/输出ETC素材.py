"""输出 ETC.AFS 全部素材（TIM2 布局已按 PS2-Visual-Novel-Tool 修正）。

参考实现：punk7890/PS2-Visual-Novel-Tool 的 `src/comFuncs.gd::load_tim2_images`。
关键修正（与早期实现相比）：
  1. **CLUT 位于像素数据之后**：clut_off = (pic_header + header_size) + image_size；
  2. clut_colors 为 256/512 且 clut_color_type 的 bit7 为 0 时，调色板需要 **unswizzle**：
         pos = (p & 231) | ((p & 0x8) << 1) | ((p & 0x10) >> 1)
     （即交换调色板序号的 bit3/bit4）
  3. 调色板可能是 32 位 RGBA8（1024B）或 16 位 RGBA5551（512B）；
  4. 图像类型：3=32bpp 直读、4=4bpp 索引、5=8bpp 索引；
  5. alpha 从 0..128 映射到 0..255。
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import decode_clean_30 as dc  # noqa: E402
import 输出保护边修复素材 as img  # noqa: E402

from 本地路径 import ORIGINAL_ISO

ISO = ORIGINAL_ISO
ETC_BASE = 325799936
OUT = Path(__file__).resolve().parent / "输出-保护边修复"


def alpha8(a: int) -> int:
    return min(255, (a * 255 + 64) // 128)


def pal_pos(p: int) -> int:
    return (p & 231) | ((p & 0x8) << 1) | ((p & 0x10) >> 1)


def unswizzle_pal(pal: bytes, nbpp: int) -> bytes:
    n = len(pal) // nbpp
    out = bytearray(len(pal))
    for p in range(n):
        pos = pal_pos(p)
        if pos >= n:
            continue
        out[pos * nbpp : pos * nbpp + nbpp] = pal[p * nbpp : p * nbpp + nbpp]
    return bytes(out)


def tim2_pic(d: bytes, off: int):
    if d[off : off + 4] != b"TIM2" or len(d) < off + 0x40:
        return None
    ph = off + 0x10
    total, clut_size, img_size = struct.unpack_from("<III", d, ph)
    hs = struct.unpack_from("<H", d, ph + 0x0C)[0]
    ncol = struct.unpack_from("<H", d, ph + 0x0E)[0]
    clut_type = d[ph + 0x12]
    img_type = d[ph + 0x13]
    w, h = struct.unpack_from("<HH", d, ph + 0x14)
    return {"total": total, "clut_size": clut_size, "img_size": img_size, "hs": hs,
            "ncol": ncol, "clut_type": clut_type, "img_type": img_type, "w": w, "h": h,
            "img_off": ph + hs, "clut_off": ph + hs + img_size,
            "next": off + total + 16}


def decode_tim2(d: bytes, off: int = 0):
    p = tim2_pic(d, off)
    if not p or not p["w"] or not p["h"]:
        return None
    w, h = p["w"], p["h"]
    area = w * h
    if area > 8_000_000:
        return None

    clut_size, ncol = p["clut_size"], p["ncol"]
    pal = b""
    if clut_size > 0 and 0 <= p["clut_off"] and p["clut_off"] + clut_size <= len(d):
        pal = d[p["clut_off"] : p["clut_off"] + clut_size]
        if (p["clut_type"] & 128) == 0 and ncol in (256, 512):
            nbpp = 4 if clut_size == ncol * 4 else (2 if clut_size == ncol * 2 else 4)
            pal = unswizzle_pal(pal, nbpp)

    def pal_color(i: int):
        if clut_size == ncol * 2 and len(pal) >= i * 2 + 2:
            px = struct.unpack_from("<H", pal, i * 2)[0]
            r5, g5, b5 = px & 0x1F, (px >> 5) & 0x1F, (px >> 10) & 0x1F
            a1 = (px >> 15) & 1
            return ((r5 << 3) | (r5 >> 2), (g5 << 3) | (g5 >> 2),
                    (b5 << 3) | (b5 >> 2), 255 if a1 else 0)
        q = i * 4
        if q + 4 > len(pal):
            return (0, 0, 0, 0)
        return (pal[q], pal[q + 1], pal[q + 2], alpha8(pal[q + 3]))

    base = p["img_off"]
    out = bytearray(area * 4)
    if p["img_type"] == 3:
        if base + area * 4 > len(d):
            return None
        src = d[base : base + area * 4]
        for i in range(area):
            o = i * 4
            out[o], out[o + 1], out[o + 2] = src[o], src[o + 1], src[o + 2]
            out[o + 3] = alpha8(src[o + 3])
        return w, h, out
    if p["img_type"] == 5:
        if base + area > len(d):
            return None
        for i in range(area):
            r, g, b, a = pal_color(d[base + i])
            o = i * 4
            out[o], out[o + 1], out[o + 2], out[o + 3] = r, g, b, a
        return w, h, out
    if p["img_type"] == 4:
        need = (area + 1) // 2
        if base + need > len(d):
            return None
        for i in range(area):
            byte = d[base + (i >> 1)]
            idx = (byte & 0x0F) if (i & 1) == 0 else ((byte >> 4) & 0x0F)
            r, g, b, a = pal_color(idx)
            o = i * 4
            out[o], out[o + 1], out[o + 2], out[o + 3] = r, g, b, a
        return w, h, out
    return None


def viable_pic(d: bytes, off: int) -> bool:
    """判定该偏移是否真的是一个可解码的 TIM2 图块（滤掉数据里偶然出现的 "TIM2" 字样）。"""
    p = tim2_pic(d, off)
    if not p:
        return False
    w, h = p["w"], p["h"]
    if not (0 < w <= 2048 and 0 < h <= 2048):
        return False
    area = w * h
    if area == 0 or area > 8_000_000:
        return False
    if not (0x40 <= p["total"] <= len(d) - off):
        return False
    if p["hs"] <= 0 or p["hs"] > 0x400:
        return False
    if p["img_type"] not in (3, 4, 5):
        return False
    bpp = 4 if p["img_type"] == 3 else (1 if p["img_type"] == 5 else 0.5)
    if p["img_off"] + int(area * bpp) > len(d):
        return False
    if p["clut_size"] > 0 and p["clut_off"] + p["clut_size"] > len(d):
        return False
    return True


def find_tim2s(d: bytes) -> list[int]:
    found = []
    pos = 0
    while True:
        i = d.find(b"TIM2", pos)
        if i < 0:
            break
        if viable_pic(d, i):
            found.append(i)
            pos = tim2_pic(d, i)["next"]
        else:
            pos = i + 4
    return found


def read_entry(f, idx):
    f.seek(ETC_BASE + 8 + idx * 8)
    off, ln = struct.unpack("<II", f.read(8))
    if not off or not ln:
        return None
    f.seek(ETC_BASE + off)
    return f.read(ln)


def main():
    d_png, d_bin = OUT / "ETC", OUT / "ETC_bin"
    d_png.mkdir(parents=True, exist_ok=True)
    d_bin.mkdir(parents=True, exist_ok=True)
    with ISO.open("rb") as f:
        f.seek(ETC_BASE + 4)
        n = struct.unpack("<I", f.read(4))[0]
        png = 0
        bins = 0
        fails = []
        for idx in range(n):
            raw = read_entry(f, idx)
            if raw is None:
                continue
            try:
                dec = dc.unpack_lzss(raw)
            except Exception as e:  # noqa: BLE001
                fails.append((idx, f"unpack:{type(e).__name__}"))
                (d_bin / f"ETC_{idx:03d}_raw.bin").write_bytes(raw)
                bins += 1
                continue
            offs = find_tim2s(dec)
            wrote = 0
            for k, off in enumerate(offs):
                t = decode_tim2(dec, off)
                if t is None:
                    continue
                w, h, rgba = t
                suffix = "" if len(offs) == 1 else f"_p{k}"
                img.write_png(d_png / f"ETC_{idx:03d}{suffix}.png", w, h, rgba)
                wrote += 1
                png += 1
            if wrote == 0:
                (d_bin / f"ETC_{idx:03d}.bin").write_bytes(dec)
                bins += 1
    print(f"ETC: PNG {png} 张，二进制 {bins} 个，失败 {len(fails)}")
    for idx, why in fails[:10]:
        print(f"   {idx}: {why}")


if __name__ == "__main__":
    main()
