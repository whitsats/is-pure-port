"""从 SE.AFS 中筛出 BGM 音乐曲目（长时长），单独归档到 BGM_music/。

判据：ADX 头声明时长 > 40s（SE 音效中位仅 3.87s）。
"""
from __future__ import annotations

import shutil
import struct
import subprocess
import wave
from pathlib import Path

import numpy as np

from 本地路径 import ORIGINAL_ISO

ISO = ORIGINAL_ISO
SE_BASE = 395005952
OUT = Path(__file__).resolve().parent / "输出-保护边修复"
ADX = OUT / "SE" / "adx"
DST = OUT / "BGM_music"
THRESHOLD = 40.0


def entries():
    rows = []
    with ISO.open("rb") as f:
        f.seek(SE_BASE + 4)
        n = struct.unpack("<I", f.read(4))[0]
        for idx in range(n):
            f.seek(SE_BASE + 8 + idx * 8)
            off, ln = struct.unpack("<II", f.read(8))
            if not off or not ln:
                continue
            f.seek(SE_BASE + off)
            h = f.read(0x20)
            if h[:2] != b"\x80\x00":
                continue
            ch = h[0x07]
            rate = struct.unpack(">I", h[0x08:0x0C])[0]
            ns = struct.unpack(">I", h[0x0C:0x10])[0]
            rows.append({"idx": idx, "ch": ch, "rate": rate,
                         "dur": ns / rate if rate else 0, "size": ln})
    return rows


def spectral_flatness(path: Path) -> float:
    """谱平坦度（越低越像有调性的音乐，越高越像噪声/音效）。"""
    try:
        w = wave.open(str(path), "rb")
        n = min(w.getnframes(), w.getframerate() * 8)
        a = np.frombuffer(w.readframes(n), dtype="<i2").astype(np.float64)
        w.close()
    except Exception:  # noqa: BLE001
        return 1.0
    if len(a) < 4096:
        return 1.0
    spec = np.abs(np.fft.rfft(a * np.hanning(len(a)))) + 1e-9
    return float(np.exp(np.log(spec).mean()) / spec.mean())


def main():
    DST.mkdir(parents=True, exist_ok=True)
    rows = entries()
    long_rows = [r for r in rows if r["dur"] > THRESHOLD]
    print(f"SE.AFS 共 {len(rows)} 条，时长 > {THRESHOLD}s 的 {len(long_rows)} 条：")
    manifest = []
    for r in sorted(long_rows, key=lambda x: x["idx"]):
        idx = r["idx"]
        src = ADX / f"SE_{idx:05d}.adx"
        if not src.exists():
            print(f"  #{idx} 缺 adx，跳过")
            continue
        wav_dst = DST / f"BGM_se{idx:05d}.wav"
        if not wav_dst.exists():
            subprocess.run(
                ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "adx",
                 "-i", str(src), "-acodec", "pcm_s16le", str(wav_dst)],
                check=False, capture_output=True)
        flat = spectral_flatness(wav_dst) if wav_dst.exists() else 1.0
        kind = "音乐" if flat < 0.15 else ("噪音/环境" if flat > 0.35 else "待定")
        manifest.append((idx, r["dur"], r["ch"], r["rate"], flat, kind))
        print(f"  #{idx:>5} {r['ch']}ch {r['rate']}Hz {r['dur']:>7.2f}s "
              f"谱平坦度={flat:.3f} -> {kind}")

    with (DST / "清单.txt").open("w", encoding="utf-8") as f:
        f.write("SE.AFS 中的长音频（>40s）清单\n")
        f.write("条目号\t时长(s)\t声道\t采样率\t谱平坦度\t判读\n")
        for idx, dur, ch, rate, flat, kind in manifest:
            f.write(f"SE_{idx:05d}\t{dur:.2f}\t{ch}\t{rate}\t{flat:.3f}\t{kind}\n")
    print(f"\n归档 {len(manifest)} 条 -> {DST}")


if __name__ == "__main__":
    main()
