"""管线短测：验证「分段插帧 + 帧数守恒 + 编码」逻辑（6 秒，强制切点在第 90 帧）。"""
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import 视频全量60fps as V  # noqa: E402

from 视频全量60fps import WORK, MV, log, run  # noqa: E402

NAME = "MV_OP01"
DUR = "6"


def main():
    base = WORK / "_test"
    if base.exists():
        shutil.rmtree(base)
    frames = base / "frames"
    sr = base / "sr"
    seq = base / "seq"
    cut_clip = base / "clip.mp4"
    base.mkdir(parents=True)
    # 截取 20s 起 6 秒
    r = run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
             "-ss", "20", "-t", DUR, "-i", str(MV / f"{NAME}.mp4"),
             "-c", "copy", str(cut_clip)])
    n = V.extract_frames(cut_clip, frames)
    log(f"抽帧 {n}")
    got = V.sr_batch(frames, sr)
    log(f"超分 {got}")
    total60 = V.split_and_interp(sr, seq, [90], got)
    log(f"60fps 帧数 {total60}（期望 {2*got}）")
    master = base / "test_master_60fps.mp4"
    V.encode_master(seq, MV / f"{NAME}.mp4", master, "60000/1001")
    info = V.ffprobe_info(master)
    vs = [x for x in info["streams"] if x["codec_type"] == "video"][0]
    log(f"母版：{vs['width']}x{vs['height']} {vs['r_frame_rate']} "
        f"帧数 {vs.get('nb_frames')} 时长 {info['format']['duration']}s "
        f"体积 {master.stat().st_size/1048576:.1f} MB")
    ok = (total60 == 2 * got)
    log("结论: " + ("✅ 帧数守恒、逻辑正确" if ok else "❌ 帧数不守恒"))
    log(f"测试产物: {base}")


if __name__ == "__main__":
    main()
