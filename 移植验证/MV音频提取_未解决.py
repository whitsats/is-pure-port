"""MV(PSS) 音频提取 —— ⚠ 已知未解决，产物是错误的，仅供继续排查。

状态（2026-11-14 复查）：
    按本脚本当前实现产出的 WAV 是**噪声**（谱平坦度 0.47，正常音乐应 <0.2）。
    原因未查明。原产出的 MV_*_audio.wav / MV_*_with_audio.mp4 已删除。

已确定的字节结构（MV_OP01 逐字节核对）：
    MPEG-PS 私有流 (stream id 0xBD) 的 payload：
    [0:17]   封装头：83 80 0a 21 | A A | B B | ff ff ff ff ff ff | a0 00 00
             [4:6]、[6:8] 两个递增字段，含义未定
    [17:49]  【仅首包】SShd 块：'SShd' + size=0x18 + codec=1 + rate=48000 + ch=2 + block=0x200 + ff×8
    [49:57]  【仅首包】SSbd 块头：'SSbd' + body_size = 18,329,600
    [57:]    【仅首包】音频数据；后续包从第 17 字节开始就是数据

关键线索（详见 项目进度总览.md 第 4.1 节）：
    * 数据量 18,329,600 B / 95.47 s = 192,000 B/s，精确等于 48kHz×2ch×16bit
      → 体积上必须是未压缩 PCM。
    * 0xBD 包 4,506 个；包长只有 4090(3418 个) / 4076(1086 个) 两种，另有 4061/743/98 各 1 个。
    * 包长 − 17 = 4073 / 4059，**都是奇数** → 每包音频数据不落在样值边界上；
      两种包长差 14 字节，成因未明。 ← 最强线索，优先攻这里
    * 按 16bit/小端/2ch 解读：相邻样值相关 0.897、L/R 相关 0.956（结构像音频），
      但谱平坦度 0.47、自相关无音高周期、波形是低通噪声 → 样值内容不对。

已排除：头长 16/17/18/19/20（17 才对）、大端、平面/分块重排（256~4096B）、
        8bit、int32/float32、多流混淆、包边界拼接错位。

用法：
    python MV音频提取_未解决.py                 # 提取三条 MV 的音频 + 打印诊断
    python MV音频提取_未解决.py --stem MV_OP01   # 只做一条
"""
from __future__ import annotations

import argparse
import struct
import sys
import wave
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
MV = HERE / "输出-保护边修复" / "MV"
HEADER_LEN = 17  # 已确认正确的封装头长度（不是问题根因）


def packets(d: bytes) -> list[bytes]:
    """切出所有 MPEG-PS 私有流 (0xBD) 包的 payload。"""
    out = []
    pos = 0
    while True:
        i = d.find(b"\x00\x00\x01\xbd", pos)
        if i < 0 or i + 6 > len(d):
            break
        pos = i + 1
        ln = struct.unpack(">H", d[i + 4 : i + 6])[0]
        out.append(d[i + 6 : i + 6 + ln])
    return out


def flatness(mono: np.ndarray, win: int = 2048) -> float:
    fs = []
    for s in range(0, max(1, len(mono) - win), win * 4):
        seg = mono[s : s + win] * np.hanning(win)
        sp = np.abs(np.fft.rfft(seg)) + 1e-9
        fs.append(float(np.exp(np.log(sp).mean()) / sp.mean()))
        if len(fs) >= 20:
            break
    return float(np.mean(fs)) if fs else 9.9


def build_pcm(d: bytes):
    """当前最佳猜测：跳过 17 字节封装头，首包跳过 SShd/SSbd，按小端 16bit 2ch 拼接。"""
    pk = packets(d)
    if not pk:
        return None, None, None
    first = pk[0]
    k = first.find(b"SSbd")
    if k < 0:
        return None, None, None
    body_size = struct.unpack_from("<I", first, k + 4)[0]
    shd = first.find(b"SShd")
    info = {}
    if shd >= 0:
        codec, rate, ch, block = struct.unpack_from("<IIII", first, shd + 8)
        info = {"codec": codec, "rate": rate, "ch": ch, "block": block}
    chunks = [first[k + 8 :]] + [pl[HEADER_LEN:] for pl in pk[1:]]
    blob = b"".join(chunks)[:body_size]
    return blob, info, len(pk)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stem", default=None)
    args = ap.parse_args()

    stems = [args.stem] if args.stem else ["MV_OP01", "MV_END01", "MV_LG01"]
    for stem in stems:
        pss = MV / f"{stem}.PSS"
        if not pss.exists():
            print(f"[跳过] {pss} 不存在")
            continue
        d = pss.read_bytes()
        blob, info, n_pk = build_pcm(d)
        if blob is None:
            print(f"[{stem}] 未找到 SSbd 块")
            continue
        print(f"\n=== {stem} ===")
        print(f"  0xBD 包 {n_pk} 个；SShd {info}")
        print(f"  数据 {len(blob)} B → {len(blob)/192000:.2f} s @48k/2ch/16bit")
        a = np.frombuffer(blob[: (len(blob) // 4) * 4], dtype="<i2")
        L = a[0::2].astype(np.float64)
        R = a[1::2].astype(np.float64)
        corr_lr = float(np.corrcoef(L, R)[0, 1]) if len(L) > 2 else 0.0
        corr_adj = float(np.corrcoef(L[:-1], L[1:])[0, 1]) if len(L) > 2 else 0.0
        print(f"  相邻样值相关 {corr_adj:.3f}  L/R 相关 {corr_lr:.3f}")
        print(f"  谱平坦度 {flatness(L):.3f}   ← 正常音乐应 <0.2，语音 ≈0.3，噪声 >0.4")

        wav = MV / f"{stem}_audio_未解决.wav"
        with wave.open(str(wav), "wb") as w:
            w.setnchannels(2)
            w.setsampwidth(2)
            w.setframerate(48000)
            w.writeframes(blob[: (len(blob) // 4) * 4])
        print(f"  已写出（错误产物，仅供分析）：{wav.name}")

    print("\n⚠ 该产出已知不正确，不要用于交付/混流。改进方向见 项目进度总览.md 第 4.1 节。")


if __name__ == "__main__":
    main()
