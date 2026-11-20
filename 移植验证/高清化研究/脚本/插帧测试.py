"""插帧可行性测试：动画源的有效帧率分析 + RIFE(rife-anime) 2× 插帧 + 质量/耗时评估。"""
from __future__ import annotations

import subprocess
import time
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent.parent
TEST = HERE / "视频测试"
TOOLS = Path(r"E:\Entertainment\IS\is-pure-zh\工具\超分")
RIFE_DIR = TOOLS / "rife-ncnn-vulkan-20221029-windows"
RIFE = RIFE_DIR / "rife-ncnn-vulkan.exe"


def analyze_effective_fps(frames: list[Path]) -> None:
    """统计相邻帧是否重复（动画常按 2/3 格绘制，重复帧很多）。"""
    prev, diffs = None, []
    for p in frames:
        with Image.open(p) as im:
            a = np.asarray(im.convert("L").resize((320, 224), Image.LANCZOS), dtype=np.float32)
        if prev is not None:
            diffs.append(float(np.abs(a - prev).mean()))
        prev = a
    d = np.array(diffs)
    hold = float((d < 0.5).mean())
    small = float((d < 2.0).mean())
    print(f"  相邻帧差异：均值 {d.mean():.2f}  中位 {np.median(d):.2f}  最大 {d.max():.2f}")
    print(f"  重复帧占比 {hold*100:.1f}%（差异<0.5）  近静止 {small*100:.1f}%（差异<2.0）")
    print(f"  → 有效率帧率估计 ≈ {30*(1-hold):.1f} fps（若按重复帧算）")


def main():
    src = TEST / "ai_x3_10s"
    frames = sorted(src.glob("*.png"))
    print(f"输入 {len(frames)} 帧（10 秒 29.97fps 的超分结果）")
    print("\n=== 动画有效帧率分析 ===")
    analyze_effective_fps(frames)

    variants = [
        ("rife-anime", ["-m", "models/rife-anime"]),                      # 不支持 -n，默认 2×
        ("rife-v4.6", ["-m", "models/rife-v4.6", "-n", str(len(frames) * 2)]),
    ]
    outputs = {}
    for name, extra in variants:
        out = TEST / f"ai_x3_60fps_{name.replace('.', '_')}"
        out.mkdir(exist_ok=True)
        t0 = time.time()
        r = subprocess.run([str(RIFE), "-i", str(src), "-o", str(out), "-g", "0"] + extra,
                           cwd=str(RIFE_DIR), capture_output=True, text=True, errors="replace", timeout=7200)
        dt = time.time() - t0
        got = len(list(out.glob("*.png")))
        print(f"\n=== RIFE {name} 2× 插帧 ===")
        print(f"  输出 {got} 帧，用时 {dt:.1f}s，平均 {dt/max(len(frames),1):.2f}s/输入帧")
        if got == 0:
            print("  " + (r.stderr or r.stdout)[-300:])
            continue
        outputs[name] = out

    def step_diff(d: Path) -> float:
        prev, vals = None, []
        for p in sorted(d.glob("*.png")):
            with Image.open(p) as im:
                a = np.asarray(im.convert("L").resize((480, 336), Image.LANCZOS), dtype=np.float32)
            if prev is not None:
                vals.append(float(np.abs(a - prev).mean()))
            prev = a
        return float(np.mean(vals))

    d30 = step_diff(src)
    print(f"\n相邻帧差异：30fps {d30:.2f}")
    for name, out in outputs.items():
        d60 = step_diff(out)
        print(f"  {name}: 60fps {d60:.2f}（理想≈{d30/2:.2f}；远大于说明有鬼影/闪烁）")

    # 编码对比片段（用第一个成功的模型）
    for name, out in outputs.items():
        mp4 = TEST / f"插帧对比_60fps_{name.replace('.', '_')}.mp4"
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                        "-framerate", "60000/1001", "-i", str(out / "%08d.png"),
                        "-c:v", "libx264", "-crf", "18", "-preset", "medium",
                        "-pix_fmt", "yuv420p", str(mp4)], capture_output=True, text=True, errors="replace")
        if mp4.exists():
            print(f"  {mp4.name}: {mp4.stat().st_size/1048576:.1f} MB")
        break

    # 30fps 对照片段
    mp4 = TEST / "插帧对比_30fps.mp4"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                    "-framerate", "30000/1001", "-i", str(src / "%05d.png"),
                    "-c:v", "libx264", "-crf", "18", "-preset", "medium",
                    "-pix_fmt", "yuv420p", str(mp4)], capture_output=True, text=True, errors="replace")
    if mp4.exists():
        print(f"  {mp4.name}: {mp4.stat().st_size/1048576:.1f} MB")


if __name__ == "__main__":
    main()
