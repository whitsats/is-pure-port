"""统计全片镜头切换数量与静止帧占比（决定插帧需要多少切点保护）。"""
import glob
import subprocess
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

MV = Path(r"E:\Entertainment\IS\is-pure-port\移植验证\输出-保护边修复\MV")
CLIP = MV / "MV_OP01.mp4"


def scene_cuts(clip: Path, thr: float = 0.25):
    tmp = Path(tempfile.mkdtemp()) / "scene.txt"
    r = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(clip),
         "-vf", f"select='gt(scene,{thr})',metadata=print:file={tmp}",
         "-f", "null", "-"],
        capture_output=True, text=True, errors="replace")
    if not tmp.exists():
        print("  检测失败:", (r.stderr or r.stdout)[-200:])
        return []
    pts = []
    for line in tmp.read_text(errors="replace").splitlines():
        if "pts_time" in line:
            try:
                pts.append(float(line.split("pts_time:")[1].split()[0]))
            except Exception:  # noqa: BLE001
                pass
    return pts


def static_ratio(clip: Path, fps: int = 3):
    tmpdir = Path(tempfile.mkdtemp())
    pattern = str(tmpdir / "f%04d.png")
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                    "-i", str(clip), "-vf", f"fps={fps},scale=240:-1", pattern],
                   capture_output=True, text=True, errors="replace")
    fs = sorted(glob.glob(str(tmpdir / "*.png")))
    prev, d = None, []
    for f in fs:
        a = np.asarray(Image.open(f).convert("L"), dtype=np.float32)
        if prev is not None:
            d.append(float(np.abs(a - prev).mean()))
        prev = a
    return np.array(d), len(fs)


def main():
    print(f"=== {CLIP.name} ===")
    cuts = scene_cuts(CLIP, 0.25)
    print(f"  镜头切换（scene>0.25）：{len(cuts)} 处")
    if cuts:
        print("  前 10 处时间点:", [round(c, 1) for c in cuts[:10]])
        gaps = np.diff(cuts)
        print(f"  平均镜头长度 {np.mean(gaps):.2f}s，最短 {gaps.min():.2f}s"
              f" → 需要保护的切点约 {len(cuts)} 个")
    d, n = static_ratio(CLIP, 3)
    print(f"  采样 {n} 帧（3fps）：相邻差异均值 {d.mean():.2f} 中位 {np.median(d):.2f}")
    print(f"  近静止(<2.0) {float((d<2.0).mean())*100:.1f}%   完全重复(<0.5) "
          f"{float((d<0.5).mean())*100:.1f}%")
    # 全片帧数
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                        "-show_entries", "stream=nb_frames,width,height",
                        "-of", "csv=p=0", str(CLIP)],
                       capture_output=True, text=True, errors="replace")
    print(f"  视频信息: {r.stdout.strip()}")


if __name__ == "__main__":
    main()
