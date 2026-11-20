"""视频全量高清化 + 60fps 插帧（母版 + 手机版）。

流程（每条视频）：
  1. ffmpeg 抽帧（原生 29.97/30fps，PNG 无损）
  2. Real-ESRGAN animevideov3 ×3 目录批量超分（1920×1344 或 1920×1440）
  3. 镜头切换检测（ffmpeg scene），按切点分段
  4. RIFE(rife-anime) 分段 2× 插帧 → 60fps；切点处不插帧、每段输出 2N 帧（含补位帧）
     → 总帧数 = 2N，时长与源完全一致（不会音画不同步）
  5. 编码母版（60fps / CRF16 / 原音轨 copy）
  6. 编码手机版（2400×1080，视频等比居中 + 两侧模糊填充，60fps）
  7. 验收：帧数/时长/音轨；清理中间帧

输出：
  移植验证/输出-视频-60fps/<视频>_母版_60fps.mp4
  移植验证/输出-视频-60fps/<视频>_手机版_2400x1080_60fps.mp4
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
MV = HERE.parent / "输出-保护边修复/MV"
OUT = HERE.parent / "输出-视频-60fps"
WORK = HERE / "视频工作区"
TOOLS = Path(r"E:\Entertainment\IS\is-pure-zh\工具\超分")
RR = TOOLS / "realesrgan-ncnn-vulkan.exe"
RIFE_DIR = TOOLS / "rife-ncnn-vulkan-20221029-windows"
RIFE = RIFE_DIR / "rife-ncnn-vulkan.exe"

SPECS = [
    ("MV_OP01", 30000 / 1001),
    ("MV_END01", 30.0),
    ("MV_LG01", 30000 / 1001),
]
PHONE_W, PHONE_H = 2400, 1080
SCENE_THR = 0.25


LOG_FILE = Path(__file__).resolve().parent.parent.parent / "输出-视频-60fps" / "运行日志.txt"


def log(msg: str) -> None:
    print(msg, flush=True)
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except Exception:  # noqa: BLE001
        pass


def run(cmd, cwd=None, timeout=14400):
    return subprocess.run(cmd, capture_output=True, text=True, errors="replace",
                          timeout=timeout, cwd=cwd)


def ffprobe_info(p: Path) -> dict:
    r = run(["ffprobe", "-v", "error", "-print_format", "json",
             "-show_format", "-show_streams", str(p)])
    try:
        return json.loads(r.stdout)
    except Exception:  # noqa: BLE001
        return {}


def extract_frames(src: Path, dst: Path) -> int:
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True)
    r = run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(src),
             "-vsync", "0", str(dst / "%05d.png")])
    if r.returncode != 0:
        raise RuntimeError(f"抽帧失败: {r.stderr[-300:]}")
    return len(list(dst.glob("*.png")))


def sr_batch(frames: Path, sr: Path) -> int:
    if sr.exists():
        shutil.rmtree(sr)
    sr.mkdir(parents=True)
    t0 = time.time()
    r = run([str(RR), "-i", str(frames), "-o", str(sr),
             "-n", "realesr-animevideov3", "-s", "3", "-g", "0"])
    got = len(list(sr.glob("*.png")))
    if got == 0:
        raise RuntimeError(f"超分失败: {(r.stderr or r.stdout)[-300:]}")
    log(f"    超分 {got} 帧，{time.time()-t0:.0f}s（{ (time.time()-t0)/max(got,1):.2f}s/帧）")
    return got


def detect_cuts(src: Path, fps: float, total: int) -> list[int]:
    r = run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(src),
             "-vf", f"select='gt(scene,{SCENE_THR})',metadata=print", "-f", "null", "-"])
    # 注意：ffmpeg 把 metadata=print 的输出写到 stderr，必须合并解析
    text = (r.stdout or "") + "\n" + (r.stderr or "")
    times = []
    for line in text.splitlines():
        if "pts_time:" in line:
            try:
                times.append(float(line.split("pts_time:")[1].split()[0]))
            except Exception:  # noqa: BLE001
                pass
    idx = sorted({min(total - 1, max(0, round(t * fps))) for t in times})
    # 合并相邻 2 帧内的切点，且保证每段至少 3 帧
    merged = []
    for i in idx:
        if merged and i - merged[-1] <= 2:
            continue
        if i < 3 or i > total - 3:
            continue
        merged.append(i)
    return merged


def split_and_interp(sr: Path, seq: Path, cuts: list[int], total: int) -> int:
    """按切点分段 RIFE 插帧；每段输出 2N 帧；用硬链接组装 seq/%06d.png。"""
    if seq.exists():
        shutil.rmtree(seq)
    seq.mkdir(parents=True)
    bounds = [0] + cuts + [total]
    seg_root = WORK / "_seg"
    all_names = sorted(p.name for p in sr.glob("*.png"))
    global_idx = 0
    for si in range(len(bounds) - 1):
        a, b = bounds[si], bounds[si + 1]
        n = b - a
        names = all_names[a:b]
        if seg_root.exists():
            shutil.rmtree(seg_root)
        seg_in = seg_root / "in"
        seg_out = seg_root / "out"
        seg_in.mkdir(parents=True)
        seg_out.mkdir(parents=True)
        for k, nm in enumerate(names, 1):
            os.link(sr / nm, seg_in / f"{k:05d}.png")

        if n < 2:
            # 单帧段：复制两次，保证 2N 帧与时长
            for _ in range(2):
                global_idx += 1
                os.link(sr / names[0], seq / f"{global_idx:06d}.png")
            log(f"    段 {si+1}/{len(bounds)-1}: 输入 1 帧 → 输出 2 帧（复制）")
            continue

        r = run([str(RIFE), "-i", str(seg_in), "-o", str(seg_out),
                 "-m", "rife-anime", "-g", "0"], cwd=str(RIFE_DIR))
        outs = sorted(p.name for p in seg_out.glob("*.png"))
        if not outs:
            raise RuntimeError(f"RIFE 失败: {(r.stderr or r.stdout)[-300:]}")
        if len(outs) != 2 * n:
            raise RuntimeError(f"RIFE 输出帧数异常：输入 {n} → 输出 {len(outs)}（应为 {2*n}）")
        for nm in outs:
            global_idx += 1
            os.link(seg_out / nm, seq / f"{global_idx:06d}.png")
        log(f"    段 {si+1}/{len(bounds)-1}: 输入 {n} 帧 → 输出 {len(outs)} 帧"
            f"（累计 {global_idx}）")
    shutil.rmtree(seg_root, ignore_errors=True)
    return global_idx


def encode_master(seq: Path, src: Path, dst: Path, fps_out: str) -> None:
    r = run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
             "-framerate", fps_out, "-i", str(seq / "%06d.png"),
             "-i", str(src), "-map", "0:v:0", "-map", "1:a:0",
             "-c:v", "libx264", "-crf", "16", "-preset", "medium",
             "-pix_fmt", "yuv420p", "-c:a", "copy", "-shortest", str(dst)])
    if not dst.exists():
        raise RuntimeError(f"母版编码失败: {(r.stderr or r.stdout)[-400:]}")


def encode_phone(seq: Path, src: Path, dst: Path, fps_out: str) -> None:
    vf = (f"[0:v]scale=-2:{PHONE_H}:flags=lanczos,split[fg][bg];"
          f"[bg]scale={PHONE_W}:{PHONE_H}:force_original_aspect_ratio=increase,"
          f"crop={PHONE_W}:{PHONE_H},gblur=sigma=28[blur];"
          f"[blur][fg]overlay=(W-w)/2:0[v]")
    r = run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
             "-framerate", fps_out, "-i", str(seq / "%06d.png"),
             "-i", str(src), "-filter_complex", vf,
             "-map", "[v]", "-map", "1:a:0",
             "-c:v", "libx264", "-crf", "18", "-preset", "medium",
             "-pix_fmt", "yuv420p", "-c:a", "copy", "-shortest", str(dst)])
    if not dst.exists():
        raise RuntimeError(f"手机版编码失败: {(r.stderr or r.stdout)[-400:]}")


def verify(src: Path, master: Path, phone: Path) -> dict:
    res = {}
    s = ffprobe_info(src)
    sd = float(s.get("format", {}).get("duration", 0))
    res["源时长"] = round(sd, 3)
    for tag, p in (("母版", master), ("手机版", phone)):
        if not p.exists():
            res[tag] = "缺失"
            continue
        info = ffprobe_info(p)
        d = float(info.get("format", {}).get("duration", 0))
        vs = [x for x in info.get("streams", []) if x.get("codec_type") == "video"]
        aus = [x for x in info.get("streams", []) if x.get("codec_type") == "audio"]
        res[tag] = {
            "时长": round(d, 3),
            "时差_vs源": round(d - sd, 3),
            "分辨率": f"{vs[0]['width']}x{vs[0]['height']}" if vs else "?",
            "帧率": vs[0].get("r_frame_rate") if vs else "?",
            "帧数": vs[0].get("nb_frames") if vs else "?",
            "音轨": bool(aus),
            "体积MB": round(p.stat().st_size / 1048576, 1),
        }
    return res


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    WORK.mkdir(parents=True, exist_ok=True)
    report = {}
    t_all = time.time()
    for name, fps in SPECS:
        src = MV / f"{name}.mp4"
        if not src.exists():
            log(f"[跳过] 缺 {src}")
            continue
        log(f"\n===== {name} =====")
        t0 = time.time()
        frames = WORK / name / "frames"
        sr = WORK / name / "sr"
        seq = WORK / name / "seq60"
        # 断点续跑：若已有中间帧且数量正确，则跳过抽帧/超分
        src_info = ffprobe_info(src)
        vs = [x for x in src_info.get("streams", []) if x.get("codec_type") == "video"]
        expected = int(vs[0].get("nb_frames") or 0) if vs else 0
        n_existing = len(list(frames.glob("*.png"))) if frames.exists() else 0
        sr_existing = len(list(sr.glob("*.png"))) if sr.exists() else 0
        if expected and n_existing == expected:
            log(f"  1) 抽帧已有 {n_existing} 帧，跳过")
            n = n_existing
        else:
            log("  1) 抽帧…")
            n = extract_frames(src, frames)
            log(f"    帧数 {n}")
        if sr_existing == n and n > 0:
            log(f"  2) 超分已有 {sr_existing} 帧，跳过")
            got = sr_existing
        else:
            log("  2) 超分 ×3（目录批量）…")
            got = sr_batch(frames, sr)
        log("  3) 镜头切换检测…")
        cuts = detect_cuts(src, fps, got)
        log(f"    切点 {len(cuts)} 处（帧索引）：{cuts[:12]}{' …' if len(cuts)>12 else ''}")
        log("  4) 分段 RIFE 插帧 60fps…")
        total60 = split_and_interp(sr, seq, cuts, got)
        log(f"    60fps 总帧数 {total60}（理论 2N={2*got}）")
        fps_out = "60000/1001" if abs(fps - 30000 / 1001) < 0.01 else "60"
        master = OUT / f"{name}_母版_60fps.mp4"
        phone = OUT / f"{name}_手机版_2400x1080_60fps.mp4"
        log("  5) 编码母版…")
        encode_master(seq, src, master, fps_out)
        log(f"    {master.name} {master.stat().st_size/1048576:.1f} MB")
        log("  6) 编码手机版…")
        encode_phone(seq, src, phone, fps_out)
        log(f"    {phone.name} {phone.stat().st_size/1048576:.1f} MB")
        log("  7) 验收…")
        v = verify(src, master, phone)
        report[name] = {"cuts": len(cuts), "src_frames": got, "fps60_frames": total60,
                        "verify": v, "耗时分钟": round((time.time() - t0) / 60, 1)}
        log("    " + json.dumps(v, ensure_ascii=False))
        # 清理中间帧（保留成品）
        shutil.rmtree(WORK / name, ignore_errors=True)
        log(f"  完成，用时 {(time.time()-t0)/60:.1f} 分钟；中间帧已清理")
    (OUT / "验收报告.json").write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                     encoding="utf-8")
    log(f"\n全部完成，总耗时 {(time.time()-t_all)/60:.1f} 分钟")
    log(f"输出目录：{OUT}")


if __name__ == "__main__":
    main()
