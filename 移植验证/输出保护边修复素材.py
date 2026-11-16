"""PS2 素材批量解码（1px 镜像保护边剥离版）。

新规则（见《PS2素材提取与保护边修复指南.md》）：
  - 像素流按 1024px 行宽切成 32 行高的存储行，每行 32 个 32x32 物理瓦片；
  - 每个物理瓦片四周各有 1px 镜像保护边，有效核心为 30x30（索引 1..30）；
  - 部件表坐标为网格单位，网格步长 = 30px，而非 32px；
  - 全局连续瓦片号，部件网格边界处不重置；表内累计瓦片数用于跳过未描述瓦片。

输出目录结构：
  <输出根>/CHR/  CHR_0000.png ...        （1473 张，偶数条目）
  <输出根>/BG/   BG_0000.png ...         （140 张，偶数条目；奇数条目为 TIM2 缩略图）
  <输出根>/BG_thumb/ BG_thumb_0001.png … （140 张 TIM2 缩略图，供对照）
  <输出根>/EV/   EV_0000.png ...         （EV 全部条目）

用法：
  python 输出保护边修复素材.py                     # 全部 CHR/BG/EV
  python 输出保护边修复素材.py --only CHR          # 只做 CHR
  python 输出保护边修复素材.py --only CHR --range 0 40
"""
from __future__ import annotations

import argparse
import struct
import sys
import zlib
from pathlib import Path

from 本地路径 import ORIGINAL_ISO

ISO_DEFAULT = ORIGINAL_ISO
BASE = {"CHR": 106958848, "BG": 636928, "EV": 343689216}
OUT_ROOT = Path(__file__).resolve().parent / "输出-保护边修复"


# ---------- LZSS ----------
def unpack_lzss(blob: bytes) -> bytearray:
    size = int.from_bytes(blob[:4], "little")
    if size > 20_000_000:
        raise ValueError(f"unexpected size {size}")
    ring, at, pos, out = bytearray(4096), 0xFEE, 4, bytearray()
    while pos < len(blob) and len(out) < size:
        flag = blob[pos]
        pos += 1
        for _ in range(8):
            if pos >= len(blob) or len(out) >= size:
                break
            if flag & 1:
                n = blob[pos]
                pos += 1
                out.append(n)
                ring[at] = n
                at = (at + 1) & 4095
            else:
                a, b = blob[pos], blob[pos + 1]
                pos += 2
                src = a | ((b & 0xF0) << 4)
                for j in range((b & 15) + 3):
                    n = ring[(src + j) & 4095]
                    out.append(n)
                    ring[at] = n
                    at = (at + 1) & 4095
            flag >>= 1
    if len(out) != size:
        raise ValueError(f"expected {size}, got {len(out)}")
    return out


# ---------- 解码 ----------
def decode_chr(raw: bytes) -> tuple[int, int, bytearray, dict]:
    """CHR/BG/EV 通用：部件表 + 30px 核心拼合。返回 (w, h, rgba, info)。"""
    cnt = struct.unpack_from("<I", raw, 0)[0]
    if not (2 <= cnt <= 64):
        raise ValueError(f"bad section count {cnt}")
    ptrs = struct.unpack_from(f"<{cnt}I", raw, 4)
    sec0 = ptrs[0]
    hs = ptrs[-2]
    if not (0 < sec0 < len(raw)) or not (0 < hs <= len(raw)):
        raise ValueError("bad header offsets")

    n_rect, cx, cy, cw, ch, fmt = struct.unpack_from("<IHHHHH", raw, sec0)
    if not (1 <= n_rect <= 40) or sec0 + 16 + n_rect * 8 > hs:
        raise ValueError(f"bad part table n_rect={n_rect}")
    rects = [struct.unpack_from("<BBBBHH", raw, sec0 + 16 + r * 8) for r in range(n_rect)]

    # 网格步长严格 30px
    max_w = max([cw] + [(gx + gw) * 30 for gx, _, gw, _, _, _ in rects])
    max_h = max([ch] + [(gy + gh) * 30 for _, gy, _, gh, _, _ in rects])
    pix = len(raw) - hs
    if pix <= 0:
        raise ValueError("no pixel data")
    canvas = bytearray(max_w * max_h * 4)

    tile = 0
    nband = pix // (1024 * 32 * 4)  # 完整存储行数（像素流按 32x32x4 的整块计）
    total_tiles = (pix // 4) // (32 * 32)

    def tile_src(t: int) -> int:
        sy, sx = t // 32, t % 32
        return hs + ((sy * 32) * 1024 + sx * 32) * 4

    for gx, gy, gw, gh, rfmt, end_tile in rects:
        for j in range(gh):
            for i in range(gw):
                if tile >= total_tiles:
                    break
                base = tile_src(tile)
                for py in range(1, 31):
                    dy = (gy + j) * 30 + (py - 1)
                    if dy >= max_h:
                        continue
                    src_row = base + py * 1024 * 4
                    dst_row = (dy * max_w + (gx + i) * 30) * 4
                    for px in range(1, 31):
                        sp = src_row + px * 4
                        a8 = min(255, (raw[sp + 3] * 255 + 64) // 128)
                        if a8 > 0:
                            dp = dst_row + (px - 1) * 4
                            canvas[dp : dp + 4] = bytes(
                                (raw[sp], raw[sp + 1], raw[sp + 2], a8)
                            )
                tile += 1
        if end_tile > tile:
            tile = end_tile

    # 裁到显示矩形
    out = bytearray(cw * ch * 4)
    for y in range(ch):
        s_off = ((cy + y) * max_w + cx) * 4
        d_off = y * cw * 4
        out[d_off : d_off + cw * 4] = canvas[s_off : s_off + cw * 4]

    info = {"parts": n_rect, "disp": (cw, ch), "canvas": (max_w, max_h),
            "tiles_used": tile, "tiles_total": total_tiles, "fmt": fmt}
    return cw, ch, out, info


def decode_tim2(raw: bytes) -> tuple[int, int, bytearray] | None:
    """TIM2 缩略图（BG/CHR 奇数条目）。"""
    if raw[:4] != b"TIM2":
        return None
    hs = struct.unpack_from("<H", raw, 0x1C)[0]
    w, h = struct.unpack_from("<HH", raw, 0x24)
    img_type = raw[0x23]
    if not w or not h or img_type != 3:
        return None
    start = 0x10 + hs
    if start + w * h * 4 > len(raw):
        return None
    src = raw[start : start + w * h * 4]
    out = bytearray(w * h * 4)
    for i in range(0, len(src), 4):
        out[i] = src[i]
        out[i + 1] = src[i + 1]
        out[i + 2] = src[i + 2]
        out[i + 3] = min(255, (src[i + 3] * 255 + 64) // 128)
    return w, h, out


def write_png(path: Path, w: int, h: int, rgba: bytearray) -> None:
    stride = w * 4
    raw = bytearray()
    for y in range(h):
        raw.append(0)
        raw.extend(rgba[y * stride : (y + 1) * stride])
    comp = zlib.compress(bytes(raw), level=6)

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
                     + chunk(b"IDAT", comp) + chunk(b"IEND", b""))


# ---------- 批处理 ----------
def read_entry(f, base: int, idx: int) -> bytes | None:
    f.seek(base + 8 + idx * 8)
    off, ln = struct.unpack("<II", f.read(8))
    if not off or not ln:
        return None
    f.seek(base + off)
    return unpack_lzss(f.read(ln))


def entry_count(f, base: int) -> int:
    f.seek(base + 4)
    return struct.unpack("<I", f.read(4))[0]


def run_afs(kind: str, iso: Path, out_dir: Path, lo: int, hi: int | None) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    base = BASE[kind]
    thumb_dir = out_dir.parent / f"{kind}_thumb"
    stats = {"ok": 0, "skip": 0, "fail": []}
    with iso.open("rb") as f:
        n = entry_count(f, base)
        end = n if hi is None else min(hi, n)
        for idx in range(lo, end):
            try:
                raw = read_entry(f, base, idx)
            except Exception as e:  # noqa: BLE001
                stats["fail"].append((idx, f"unpack:{type(e).__name__}:{e}"))
                continue
            if raw is None:
                stats["skip"] += 1
                continue
            # 自动识别：TIM2 开头的是缩略图，其余按图块格式解码
            if raw[:4] == b"TIM2":
                try:
                    t = decode_tim2(raw)
                except Exception as e:  # noqa: BLE001
                    stats["fail"].append((idx, f"tim2:{type(e).__name__}:{e}"))
                    continue
                if t is None:
                    stats["skip"] += 1
                    continue
                w, h, rgba = t
                thumb_dir.mkdir(parents=True, exist_ok=True)
                write_png(thumb_dir / f"{kind}_thumb_{idx:04d}.png", w, h, rgba)
                stats["ok"] += 1
                continue
            try:
                w, h, rgba, _info = decode_chr(raw)
                write_png(out_dir / f"{kind}_{idx:04d}.png", w, h, rgba)
                stats["ok"] += 1
            except Exception as e:  # noqa: BLE001
                stats["fail"].append((idx, f"{type(e).__name__}:{e}"))
            if stats["ok"] and stats["ok"] % 200 == 0:
                print(f"  [{kind}] {stats['ok']} 张…", flush=True)
    return stats


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--iso", type=Path, default=ISO_DEFAULT)
    ap.add_argument("--out", type=Path, default=OUT_ROOT)
    ap.add_argument("--only", choices=["CHR", "BG", "EV"], default=None)
    ap.add_argument("--range", nargs=2, type=int, default=None,
                    metavar=("LO", "HI"), help="条目号范围 [LO, HI)")
    args = ap.parse_args()

    kinds = [args.only] if args.only else ["CHR", "BG", "EV"]
    lo, hi = (args.range if args.range else (0, None))
    for kind in kinds:
        print(f"\n=== {kind} ===", flush=True)
        stats = run_afs(kind, args.iso, args.out / kind, lo, hi)
        print(f"[{kind}] 成功 {stats['ok']}，跳过 {stats['skip']}，失败 {len(stats['fail'])}")
        for idx, why in stats["fail"][:15]:
            print(f"   失败 {idx}: {why}")
    print(f"\n输出目录：{args.out}")


if __name__ == "__main__":
    main()
