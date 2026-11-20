"""视频超分可行性测试：抽短片段逐帧超分 → 重编码 → 时序一致性/耗时评估。"""
from __future__ import annotations

import shutil
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent.parent
MV = HERE.parent / "输出-保护边修复/MV"
TEST = HERE / "视频测试"
TOOLS = Path(r"E:\Entertainment\IS\is-pure-zh\工具\超分")
RR = TOOLS / "realesrgan-ncnn-vulkan.exe"

CLIP = MV / "MV_OP01.mp4"
SS = 20.0      # 起始秒
DUR = 2.0      # 时长（秒）
MODEL = ["-n", "realesr-animevideov3", "-s", "3", "-g", "0"]


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=3600, **kw)


def extract_frames(dest: Path):
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    r = run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
             "-ss", str(SS), "-t", str(DUR), "-i", str(CLIP),
             "-vsync", "0", str(dest / "%05d.png")])
    if r.returncode != 0:
        raise SystemExit(f"抽帧失败: {r.stderr[-300:]}")
    return sorted(dest.glob("*.png"))


def main():
    TEST.mkdir(exist_ok=True)
    frames = extract_frames(TEST / "frames")
    print(f"抽帧 {len(frames)} 张，源尺寸 {Image.open(frames[0]).size}")

    for tag, factor in (("lanczos3", 3), ("lanczos2", 2)):
        d = TEST / tag
        d.mkdir(exist_ok=True)
        t0 = time.time()
        for p in frames:
            with Image.open(p) as im:
                im.resize((im.width * factor, im.height * factor), Image.LANCZOS).save(d / p.name)
        print(f"  {tag}: {time.time()-t0:.1f}s")

    # AI 超分 ×3
    d_ai = TEST / "ai_x3"
    d_ai.mkdir(exist_ok=True)
    t0 = time.time()
    ok = 0
    for i, p in enumerate(frames, 1):
        outp = d_ai / p.name
        r = run([str(RR)] + MODEL + ["-i", str(p), "-o", str(outp)])
        if outp.exists():
            ok += 1
        if i % 20 == 0:
            print(f"    {i}/{len(frames)}  {time.time()-t0:.1f}s")
    dt = time.time() - t0
    print(f"  ai_x3: {ok}/{len(frames)} 张，用时 {dt:.1f}s，平均 {dt/max(ok,1):.2f}s/帧，"
          f"输出 {Image.open(frames[0]).size} → {Image.open(d_ai/frames[0].name).size}")

    # 时序一致性：相邻帧差异（灰度、缩到 480 宽比较，消除分辨率影响）
    def flicker(d: Path) -> float:
        prev = None
        vals = []
        for p in sorted(d.glob("*.png")):
            with Image.open(p) as im:
                g = im.convert("L").resize((480, 336), Image.LANCZOS)
                a = np.asarray(g, dtype=np.float32)
            if prev is not None:
                vals.append(float(np.abs(a - prev).mean()))
            prev = a
        return float(np.mean(vals)) if vals else 0.0

    f_l3 = flicker(TEST / "lanczos3")
    f_ai = flicker(d_ai)
    print(f"\n相邻帧差异（越小越稳定）：Lanczos×3 = {f_l3:.2f}   AI×3 = {f_ai:.2f}  "
          f"（比值 {f_ai/max(f_l3,1e-6):.2f}×）")

    # 重编码短片段（带原音频）
    for tag, d, factor in (("ai_x3", d_ai, 3), ("lanczos3", TEST / "lanczos3", 3)):
        outp = TEST / f"{tag}_clip.mp4"
        r = run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                 "-framerate", "30000/1001", "-i", str(d / "%05d.png"),
                 "-ss", str(SS), "-t", str(DUR), "-i", str(CLIP),
                 "-map", "0:v:0", "-map", "1:a:0",
                 "-c:v", "libx264", "-crf", "16", "-preset", "medium",
                 "-pix_fmt", "yuv420p", "-c:a", "copy", "-shortest", str(outp)])
        print(f"  {tag}_clip.mp4: {'OK' if outp.exists() else r.stderr[-200:]}"
              f"  {outp.stat().st_size/1048576:.1f} MB" if outp.exists() else "")

    print(f"\n产物目录: {TEST}")


if __name__ == "__main__":
    main()
