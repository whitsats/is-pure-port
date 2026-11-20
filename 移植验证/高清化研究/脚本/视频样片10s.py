"""生成 10 秒视频超分样片：母版（1920×1344）与手机成品版（2400×1080，两侧背景填充）。"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

HERE = Path(__file__).resolve().parent.parent
MV = HERE.parent / "输出-保护边修复/MV"
TEST = HERE / "视频测试"
TOOLS = Path(r"E:\Entertainment\IS\is-pure-zh\工具\超分")
RR = TOOLS / "realesrgan-ncnn-vulkan.exe"

CLIP = MV / "MV_OP01.mp4"
SS, DUR = 20.0, 10.0
FPS = "30000/1001"
MODEL = ["-n", "realesr-animevideov3", "-s", "3", "-g", "0"]


def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=7200)


def main():
    frames = TEST / "frames10"
    up = TEST / "ai_x3_10s"
    if frames.exists():
        shutil.rmtree(frames)
    frames.mkdir(parents=True)
    r = run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", str(SS),
             "-t", str(DUR), "-i", str(CLIP), "-vsync", "0", str(frames / "%05d.png")])
    if r.returncode:
        raise SystemExit(r.stderr[-300:])
    fl = sorted(frames.glob("*.png"))
    print(f"抽帧 {len(fl)} 张")
    up.mkdir(parents=True, exist_ok=True)
    ok = 0
    for i, p in enumerate(fl, 1):
        outp = up / p.name
        if outp.exists():
            ok += 1
            continue
        run([str(RR)] + MODEL + ["-i", str(p), "-o", str(outp)])
        if outp.exists():
            ok += 1
        if i % 60 == 0:
            print(f"  {i}/{len(fl)}")
    print(f"超分 {ok}/{len(fl)}")

    # 母版：1920×1344 + 原音轨
    master = TEST / "样片_母版_1920x1344.mp4"
    r = run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
             "-framerate", FPS, "-i", str(up / "%05d.png"),
             "-ss", str(SS), "-t", str(DUR), "-i", str(CLIP),
             "-map", "0:v:0", "-map", "1:a:0",
             "-c:v", "libx264", "-crf", "16", "-preset", "medium", "-pix_fmt", "yuv420p",
             "-c:a", "aac", "-b:a", "192k", "-shortest", str(master)])
    print(f"母版: {master.name} {master.stat().st_size/1048576:.1f} MB" if master.exists() else r.stderr[-300:])

    # 成品手机版：2400×1080，视频等比到 1080 高居中，两侧用模糊视频做背景填充
    phone = TEST / "样片_手机版_2400x1080.mp4"
    vf = (
        "[0:v]scale=1544:1080:flags=lanczos,split[fg][bg];"
        "[bg]scale=2400:1080:force_original_aspect_ratio=increase,crop=2400:1080,"
        "gblur=sigma=28[blur];"
        "[blur][fg]overlay=(W-w)/2:0[v]"
    )
    r = run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
             "-framerate", FPS, "-i", str(up / "%05d.png"),
             "-ss", str(SS), "-t", str(DUR), "-i", str(CLIP),
             "-filter_complex", vf, "-map", "[v]", "-map", "1:a:0",
             "-c:v", "libx264", "-crf", "18", "-preset", "medium", "-pix_fmt", "yuv420p",
             "-c:a", "aac", "-b:a", "192k", "-shortest", str(phone)])
    print(f"手机版: {phone.name} {phone.stat().st_size/1048576:.1f} MB" if phone.exists() else r.stderr[-300:])

    # 时序一致性（10 秒更可信）
    def flicker(d: Path) -> float:
        prev, vals = None, []
        for p in sorted(d.glob("*.png")):
            with Image.open(p) as im:
                a = np.asarray(im.convert("L").resize((480, 336), Image.LANCZOS), dtype=np.float32)
            if prev is not None:
                vals.append(float(np.abs(a - prev).mean()))
            prev = a
        return float(np.mean(vals)) if vals else 0.0

    print(f"相邻帧差异 AI×3 = {flicker(up):.2f}")


if __name__ == "__main__":
    main()
