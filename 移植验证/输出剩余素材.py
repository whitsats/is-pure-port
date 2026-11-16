"""输出剩余容器素材：BGM / MAC / SE / VOICE。

- BGM：每条目解压 215248B = 16B 头 + 3 张 TIM2(160x112)，输出 120 张 PNG（调试占位图）。
- MAC：74 条剧本 → 解压后 .bin（反汇编见 MAC_反汇编.py）。
- SE ：174 条 CRI ADX（2ch/48kHz）→ 原始 .adx + 转 16bit PCM .wav。
- VOICE：12790 条 CRI ADX（1ch/48kHz）→ 原始 .adx + 转 16bit PCM .wav。

注意：ETC 不在此脚本内 —— 旧 TIM2 布局实现是错的（会产出错误 PNG），
      请使用 输出ETC素材.py（CLUT 在图像之后 + 调色板反 swizzle + viable_pic 校验）。

用法：
  python 输出剩余素材.py                # 全部（BGM/MAC/SE/VOICE）
  python 输出剩余素材.py --only VOICE   # 指定容器
  python 输出剩余素材.py --only VOICE --no-wav   # 只导出 .adx
"""
from __future__ import annotations

import argparse
import struct
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import decode_clean_30 as dc  # noqa: E402
import 输出保护边修复素材 as img  # noqa: E402

from 本地路径 import ORIGINAL_ISO

ISO = ORIGINAL_ISO
BASES = {"BGM": 103104512, "MAC": 393924608,
         "SE": 395005952, "VOICE": 696072192}
OUT_ROOT = Path(__file__).resolve().parent / "输出-保护边修复"


def entry_count(f, base):
    f.seek(base + 4)
    return struct.unpack("<I", f.read(4))[0]


def read_entry(f, base, idx):
    f.seek(base + 8 + idx * 8)
    off, ln = struct.unpack("<II", f.read(8))
    if not off or not ln:
        return None
    f.seek(base + off)
    return f.read(ln)


# ---------------- BGM ----------------
def run_bgm(f, out: Path) -> dict:
    d = out / "BGM"
    d.mkdir(parents=True, exist_ok=True)
    n = entry_count(f, BASES["BGM"])
    ok = 0
    for idx in range(n):
        raw = read_entry(f, BASES["BGM"], idx)
        if raw is None:
            continue
        dec = dc.unpack_lzss(raw)
        pos = [i for i in range(len(dec) - 4) if dec[i:i + 4] == b"TIM2"]
        for k, p in enumerate(pos):
            sub = dec[p:]
            t = img.decode_tim2(sub)
            if t is None:
                continue
            w, h, rgba = t
            img.write_png(d / f"BGM_{idx:03d}_{k}.png", w, h, rgba)
            ok += 1
    return {"ok": ok, "fail": 0}


# ---------------- MAC ----------------
def run_mac(f, out: Path) -> dict:
    d = out / "MAC"
    d.mkdir(parents=True, exist_ok=True)
    n = entry_count(f, BASES["MAC"])
    ok = 0
    fail = 0
    for idx in range(n):
        raw = read_entry(f, BASES["MAC"], idx)
        if raw is None:
            continue
        try:
            dec = dc.unpack_lzss(raw)
        except Exception:  # noqa: BLE001
            fail += 1
            continue
        (d / f"MAC_{idx:03d}.bin").write_bytes(dec)
        ok += 1
    return {"ok": ok, "fail": fail}


# ---------------- 音频 ----------------
def _convert_one(args):
    adx_path, wav_path, raw = args
    Path(adx_path).write_bytes(raw)
    if wav_path:
        try:
            subprocess.run(
                ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                 "-f", "adx", "-i", str(adx_path),
                 "-acodec", "pcm_s16le", str(wav_path)],
                check=True, capture_output=True, timeout=60,
            )
            return "ok"
        except Exception as e:  # noqa: BLE001
            return f"wav:{type(e).__name__}"
    return "ok"


def run_audio(kind: str, f, out: Path, make_wav: bool, workers: int) -> dict:
    base = BASES[kind]
    d_adx = out / kind / "adx"
    d_adx.mkdir(parents=True, exist_ok=True)
    d_wav = None
    if make_wav:
        d_wav = out / kind / "wav"
        d_wav.mkdir(parents=True, exist_ok=True)
    n = entry_count(f, base)
    tasks = []
    for idx in range(n):
        raw = read_entry(f, base, idx)
        if raw is None:
            continue
        adx = d_adx / f"{kind}_{idx:05d}.adx"
        wav = (d_wav / f"{kind}_{idx:05d}.wav") if d_wav else None
        tasks.append((str(adx), str(wav) if wav else None, raw))
    ok = 0
    fails = []
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for n_done, res in enumerate(pool.map(_convert_one, tasks, chunksize=32), 1):
            if res == "ok":
                ok += 1
            else:
                fails.append(res)
            if n_done % 500 == 0:
                print(f"  [{kind}] {n_done}/{len(tasks)}…", flush=True)
    return {"ok": ok, "fail": len(fails), "fails": fails[:5], "total": len(tasks)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--iso", type=Path, default=ISO)
    ap.add_argument("--out", type=Path, default=OUT_ROOT)
    ap.add_argument("--only", nargs="*", choices=list(BASES), default=None)
    ap.add_argument("--no-wav", action="store_true")
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()

    kinds = args.only if args.only else ["BGM", "MAC", "SE", "VOICE"]
    with args.iso.open("rb") as f:
        for kind in kinds:
            print(f"\n=== {kind} ===", flush=True)
            if kind == "BGM":
                r = run_bgm(f, args.out)
            elif kind == "MAC":
                r = run_mac(f, args.out)
            else:
                r = run_audio(kind, f, args.out, not args.no_wav, args.workers)
            print(f"[{kind}] {r}")

    print(f"\n输出目录：{args.out}")


if __name__ == "__main__":
    main()
