"""验收 MV_OP01 60fps 成品：切点处理、帧率/时长、手机版布局、音画同步。"""
from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent.parent
OUT = HERE.parent / "输出-视频-60fps"
CMP = HERE / "对比"
TMP = HERE / "视频工作区" / "_verify"


def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=1800)


def grab(clip: Path, frame_idx: int, dst: Path) -> bool:
    """按帧号抽帧（60fps 视频）"""
    fps = 60000 / 1001
    t = frame_idx / fps
    r = run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{t:.6f}",
             "-i", str(clip), "-frames:v", "1", str(dst)])
    return dst.exists()


def gray(p: Path):
    with Image.open(p) as im:
        return np.asarray(im.convert("L").resize((320, 224), Image.LANCZOS), dtype=np.float32)


def main():
    TMP.mkdir(parents=True, exist_ok=True)
    master = OUT / "MV_OP01_母版_60fps.mp4"
    phone = OUT / "MV_OP01_手机版_2400x1080_60fps.mp4"
    print(f"母版存在: {master.exists()}  手机版存在: {phone.exists()}")

    # 切点：30fps 帧 523 → 60fps 输出帧 1046（段 1 输出 1046 帧后切换）
    cut60 = 1046
    diffs = []
    prev = None
    for i in range(cut60 - 4, cut60 + 4):
        p = TMP / f"f{i:06d}.png"
        if not grab(master, i, p):
            print(f"  抽帧失败 {i}")
            continue
        g = gray(p)
        if prev is not None:
            diffs.append((i, float(np.abs(g - prev).mean())))
        prev = g
    print("\n切点附近相邻帧差异（应出现一个明显峰值，且无中间过渡帧）：")
    for i, d in diffs:
        mark = "  ← 切点" if i == cut60 else ""
        print(f"  帧 {i-1}→{i}: {d:6.2f}{mark}")

    # 手机版布局：抽一帧看
    fp = TMP / "phone.png"
    if grab(phone, 600, fp):
        im = Image.open(fp)
        print(f"\n手机版抽帧 {im.size}")
        im.resize((1200, 540), Image.LANCZOS).save(CMP / "视频60fps_手机版_预览.png")

    # 音画同步：比较成品音频与源音频时长
    def dur(p: Path, stream: str) -> float:
        r = run(["ffprobe", "-v", "error", "-select_streams", stream,
                 "-show_entries", "stream=duration", "-of", "csv=p=0", str(p)])
        try:
            return float(r.stdout.strip())
        except Exception:  # noqa: BLE001
            return -1
    src = HERE.parent / "输出-保护边修复/MV/MV_OP01.mp4"
    print(f"\n音画同步：源视频 {dur(src,'v:0'):.3f}s 源音频 {dur(src,'a:0'):.3f}s  "
          f"成品视频 {dur(master,'v:0'):.3f}s 成品音频 {dur(master,'a:0'):.3f}s")

    # 60fps 平滑度：相邻帧差异应约为 30fps 的一半
    seq_d = []
    prev = None
    for i in range(600, 660, 2):
        p = TMP / f"s{i:06d}.png"
        if grab(master, i, p):
            g = gray(p)
            if prev is not None:
                seq_d.append(float(np.abs(g - prev).mean()))
            prev = g
    if seq_d:
        print(f"\n60fps 每隔 2 帧的差异均值 {np.mean(seq_d):.2f}")


if __name__ == "__main__":
    main()
