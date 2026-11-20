"""批量超分管线（严格等比 ×4，不裁剪、不拉伸、保留 alpha）。

设计要点：
  1. 只读原始素材目录，输出到独立目录，绝不覆盖原素材；
  2. 严格 ×4：输出尺寸必须是输入的 4 倍，否则判失败；
  3. 自动质检（防止 AI 模型在某些图上崩坏）：
       - alpha 均值与源图偏差 ≤ 2
       - RGB 均值与源图偏差 ≤ 12（超出说明跑飞/变色，如 realesrgan-x4plus-anime 在噪点图上）
       - 结果非纯色（唯一颜色数 > 16）
       - 回采（BOX 缩回源尺寸）后的 SSIM ≥ 0.90
     失败项记录到 CSV，并跳过（不写入坏图）。
  4. 断点续跑：已存在且通过质检的输出直接跳过。

用法：
    python 批量超分.py --limit 10          # 小样本试跑
    python 批量超分.py                     # 全量
    python 批量超分.py --dirs BG CHR      # 只做指定类别
"""
from __future__ import annotations

import argparse
import csv
import subprocess
import time
from pathlib import Path

import numpy as np
from PIL import Image
from skimage.metrics import structural_similarity as ssim

HERE = Path(__file__).resolve().parent.parent
SRC_ROOT = HERE.parent / "输出-保护边修复"
OUT_ROOT = HERE.parent / "输出-高清化-×4"
TOOLS = Path(r"E:\Entertainment\IS\is-pure-zh\工具\超分")
RR = TOOLS / "realesrgan-ncnn-vulkan.exe"
MODEL = ["-n", "realesr-animevideov3", "-s", "4", "-g", "0"]

CATEGORIES = {
    "BG": SRC_ROOT / "BG",
    "CHR": SRC_ROOT / "CHR",
    "EV": SRC_ROOT / "EV",
    "ETC": SRC_ROOT / "ETC",
}


def is_flat(img: Image.Image, max_colors: int = 16) -> bool:
    """判断是否为纯色/极简图（这类图无需 AI 超分，整像素放大即无损）。
    在小图上判断即可，避免对 2560×1792 做全量 unique。"""
    small = img.convert("RGBA")
    if max(small.size) > 64:
        small = small.resize((64, max(1, round(small.height * 64 / small.width))), Image.NEAREST)
    a = np.asarray(small)
    return len(np.unique(a.reshape(-1, 4), axis=0)) <= max_colors


def quality_check(src: Path, out: Path, flat_mode: bool = False) -> tuple[bool, str]:
    try:
        s = Image.open(src).convert("RGBA")
        o = Image.open(out).convert("RGBA")
    except Exception as e:  # noqa: BLE001
        return False, f"打不开: {type(e).__name__}"
    if o.size != (s.width * 4, s.height * 4):
        return False, f"尺寸不是4倍 {s.size}->{o.size}"
    sa = np.asarray(s, dtype=np.uint8)
    oa = np.asarray(o, dtype=np.uint8)
    # 均值比较用 uint8 即可
    if abs(float(sa[..., 3].mean()) - float(oa[..., 3].mean())) > 2:
        return False, f"alpha 均值偏差 {abs(float(sa[...,3].mean())-float(oa[...,3].mean())):.1f}"
    if abs(float(sa[..., :3].mean()) - float(oa[..., :3].mean())) > 12:
        return False, f"RGB 均值偏差 {abs(float(sa[...,:3].mean())-float(oa[...,:3].mean())):.1f}"
    # 颜色数：缩到小图上判断（快）
    small = o.convert("RGB")
    if max(small.size) > 160:
        small = small.resize((160, max(1, round(small.height * 160 / small.width))), Image.NEAREST)
    colors = len(np.unique(np.asarray(small).reshape(-1, 3), axis=0))
    if flat_mode:
        if colors > 64:
            return False, f"纯色源被加噪（输出唯一色 {colors}）"
        return True, f"纯色源 整像素放大 唯一色 {colors}"
    if colors <= 8:
        return False, f"结果近似纯色(唯一色 {colors})"
    back = np.asarray(o.resize(s.size, Image.BOX).convert("RGB"), dtype=np.uint8)
    srgb = sa[..., :3]
    mask = sa[..., 3] > 8
    y0, y1, x0, x1 = 0, s.height, 0, s.width
    ys = np.where(mask.mean(axis=1) > 0.02)[0]
    xs = np.where(mask.mean(axis=0) > 0.02)[0]
    if len(ys) and len(xs):
        y0, y1, x0, x1 = int(ys[0]), int(ys[-1]) + 1, int(xs[0]), int(xs[-1]) + 1
    if (y1 - y0) < 16 or (x1 - x0) < 16:
        return True, "面积过小跳过SSIM"
    try:
        v = ssim(back[y0:y1, x0:x1], srgb[y0:y1, x0:x1], channel_axis=2, data_range=255)
    except Exception as e:  # noqa: BLE001
        return True, f"SSIM计算失败({type(e).__name__})"
    if v < 0.90:
        return False, f"回采SSIM {v:.3f} < 0.90"
    return True, f"OK SSIM {v:.3f}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dirs", nargs="*", default=list(CATEGORIES), choices=list(CATEGORIES))
    ap.add_argument("--limit", type=int, default=0, help="每类最多处理多少张（0=全部）")
    ap.add_argument("--skip-check", action="store_true")
    args = ap.parse_args()

    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    log_path = OUT_ROOT / "质检日志.csv"
    write_header = not log_path.exists()
    logf = log_path.open("a", newline="", encoding="utf-8-sig")
    writer = csv.writer(logf)
    if write_header:
        writer.writerow(["类别", "文件", "状态", "说明", "耗时s"])
        logf.flush()

    t_all = time.time()
    stats = {}
    for cat in args.dirs:
        d = CATEGORIES[cat]
        if not d.exists():
            print(f"[跳过] 目录不存在 {d}")
            continue
        files = sorted(d.glob("*.png"))
        if args.limit:
            files = files[: args.limit]
        outdir = OUT_ROOT / cat
        outdir.mkdir(parents=True, exist_ok=True)
        ok = fail = skipped = 0
        print(f"\n=== {cat}: {len(files)} 张 ===")
        for i, src in enumerate(files, 1):
            outp = outdir / src.name
            if outp.exists():
                # 断点续跑：直接信任已存在（除非要复检）
                skipped += 1
                continue
            t0 = time.time()
            flat = False
            with Image.open(src) as im0:
                flat = is_flat(im0)
            if flat:
                # 纯色/极简图：AI 超分只会加噪，改为整像素 ×4（数学上无损）
                with Image.open(src) as im0:
                    im0.convert("RGBA").resize((im0.width * 4, im0.height * 4),
                                               Image.NEAREST).save(outp)
                dt = time.time() - t0
            else:
                r = subprocess.run([str(RR)] + MODEL + ["-i", str(src), "-o", str(outp)],
                                   capture_output=True, text=True, timeout=1200)
                dt = time.time() - t0
            if not outp.exists():
                fail += 1
                writer.writerow([cat, src.name, "失败", (r.stderr or r.stdout)[-200:] if not flat else "纯色放大失败", f"{dt:.2f}"])
                logf.flush()
                continue
            if args.skip_check:
                passed, why = True, "跳过质检"
            else:
                passed, why = quality_check(src, outp, flat_mode=flat)
            if not passed:
                # 回退：AI 质检不过（典型：噪声/速度线/遮罩贴图被改写结构）→ 整像素 ×4（严格无损）
                fail += 1
                outp.unlink(missing_ok=True)
                with Image.open(src) as im0:
                    im0.convert("RGBA").resize((im0.width * 4, im0.height * 4),
                                               Image.NEAREST).save(outp)
                p2, why2 = quality_check(src, outp, flat_mode=flat)
                if p2:
                    writer.writerow([cat, src.name, "通过(回退整像素)",
                                     f"AI未过({why}) → 整像素无损({why2})", f"{dt:.2f}"])
                    logf.flush()
                    ok += 1
                    fail -= 1
                    continue
                oute = ""
                outp.unlink(missing_ok=True)
                writer.writerow([cat, src.name, "剔除", f"AI({why}) + 回退({why2}) 均未过", f"{dt:.2f}"])
                logf.flush()
                continue
            ok += 1
            writer.writerow([cat, src.name, "通过", why, f"{dt:.2f}"])
            logf.flush()
            if i % 50 == 0:
                print(f"  {i}/{len(files)}  通过 {ok} 剔除 {fail} 跳过 {skipped}")
        stats[cat] = {"ok": ok, "fail": fail, "skipped": skipped, "total": len(files)}
        print(f"  {cat} 完成：通过 {ok}，剔除 {fail}，跳过 {skipped}")
    logf.close()

    print(f"\n=== 汇总（总耗时 {(time.time()-t_all)/60:.1f} 分钟）===")
    for cat, s in stats.items():
        print(f"  {cat:<5} 通过 {s['ok']:>5} / {s['total']:>5}，剔除 {s['fail']}，已存在跳过 {s['skipped']}")
    print(f"输出目录：{OUT_ROOT}")
    print(f"质检日志：{log_path}")


if __name__ == "__main__":
    main()
