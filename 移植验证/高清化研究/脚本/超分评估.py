"""超分方案评估（严格等比、不拉伸、不裁剪）。

评估维度：
  1. 回采保真度（无损伤真）：SR 结果用 BOX 缩回原始尺寸，与源图比较 PSNR/SSIM。
     - 整像素 NEAREST 放大 + BOX 回采 = 恒等变换（PSNR = ∞）→ 严格无损
     - AI 超分会“补细节”，回采后与源图有差异 → 保真度下降（换来视觉锐度）
  2. 锐度提升：SR 尺度下的平均梯度（越大越锐）
  3. Alpha 保真度：alpha 通道回采后的 PSNR
  4. 透明边缘溢色：合成到品红底，检查边缘带是否出现异常色边
  5. 速度：单张耗时（用于整批成本估算）
"""
from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

import numpy as np
from PIL import Image
from skimage.metrics import structural_similarity as ssim

HERE = Path(__file__).resolve().parent.parent
RES = HERE
SRC = HERE.parent / "输出-保护边修复"
TOOLS = Path(r"E:\Entertainment\IS\is-pure-zh\工具\超分")
RR = TOOLS / "realesrgan-ncnn-vulkan.exe"
RC = TOOLS / "realcugan-ncnn-vulkan-20220728-windows" / "realcugan-ncnn-vulkan.exe"
RESULTS = RES / "超分结果"
os_dir = RESULTS
os_dir.mkdir(parents=True, exist_ok=True)

SAMPLES = {
    "BG_0218": SRC / "BG/BG_0218.png",
    "BG_0000": SRC / "BG/BG_0000.png",
    "CHR_0000": SRC / "CHR/CHR_0000.png",
    "CHR_0452_bust": SRC / "CHR/CHR_0452.png",
    "EV_0126": SRC / "EV/EV_0126.png",
    "ETC_095": SRC / "ETC/ETC_095.png",
}

# (标签, 类型, 参数)
METHODS = [
    ("nearest4", "pil", ("NEAREST", 4)),
    ("lanczos4", "pil", ("LANCZOS", 4)),
    ("nearest2", "pil", ("NEAREST", 2)),
    ("lanczos2", "pil", ("LANCZOS", 2)),
    ("esrgan_v3_x3", "rr", ["-n", "realesr-animevideov3", "-s", "3", "-g", "0"]),
    ("esrgan_v3_x4", "rr", ["-n", "realesr-animevideov3", "-s", "4", "-g", "0"]),
    ("esrgan_anime_x4", "rr", ["-n", "realesrgan-x4plus-anime", "-s", "4", "-g", "0"]),
    ("cugan_up3x", "rc", ["-n", "up3x-conservative", "-s", "3", "-g", "0"]),
    ("cugan_up2x", "rc", ["-n", "up2x-conservative", "-s", "2", "-g", "0"]),
]


def run_method(tag: str, kind: str, args, src: Path) -> tuple[Path, float] | None:
    outp = RESULTS / f"{src.stem}__{tag}.png"
    if outp.exists():
        return outp, 0.0
    t0 = time.time()
    if kind == "pil":
        filt, factor = args
        with Image.open(src) as im:
            im.convert("RGBA").resize((im.width * factor, im.height * factor),
                                      getattr(Image, filt)).save(outp)
    else:
        exe = RR if kind == "rr" else RC
        r = subprocess.run([str(exe)] + args + ["-i", str(src), "-o", str(outp)],
                           capture_output=True, text=True, timeout=3600)
        if not outp.exists():
            print(f"    [失败] {src.stem} {tag}: {(r.stderr or r.stdout)[-160:]}")
            return None
    return outp, time.time() - t0


def masked_psnr(a: np.ndarray, b: np.ndarray, mask: np.ndarray) -> float:
    m = mask > 0
    if m.sum() == 0:
        return 99.0
    d = (a[m] - b[m]).astype(np.float64)
    mse = float((d ** 2).mean())
    if mse <= 1e-12:
        return 99.0
    return float(10 * np.log10(255.0 ** 2 / mse))


def eval_one(src: Path, sr: Path, factor: int) -> dict:
    s = Image.open(src).convert("RGBA")
    o = Image.open(sr).convert("RGBA")
    assert o.size == (s.width * factor, s.height * factor), f"尺寸不是整数倍: {s.size} -> {o.size}"
    sarr = np.asarray(s, dtype=np.float64)
    oarr = np.asarray(o, dtype=np.float64)
    # 回采（BOX = 面积平均）
    back = np.asarray(o.resize(s.size, Image.BOX), dtype=np.float64)
    mask = sarr[..., 3]
    psnr_rgb = masked_psnr(back[..., :3], sarr[..., :3], mask)
    psnr_a = masked_psnr(back[..., 3:4], sarr[..., 3:4], np.full(mask.shape, 255.0))
    # SSIM（RGB，仅不透明区域）
    y0, y1, x0, x1 = bbox(mask)
    if (y1 - y0) > 8 and (x1 - x0) > 8:
        sm = ssim(back[y0:y1, x0:x1, :3].round().astype(np.uint8),
                  sarr[y0:y1, x0:x1, :3].round().astype(np.uint8),
                  channel_axis=2, data_range=255)
    else:
        sm = 1.0
    # 锐度（SR 尺度，RGB 亮度梯度）
    lum = oarr[..., 0] * .299 + oarr[..., 1] * .587 + oarr[..., 2] * .114
    gy, gx = np.gradient(lum)
    sharp = float((np.abs(gx) + np.abs(gy)).mean())
    # 透明边缘溢色：合成品红底后看边缘带色偏
    comp = np.zeros_like(oarr[..., :3])
    al = (oarr[..., 3:4] / 255.0)
    comp = oarr[..., :3] * al + np.array([200., 0., 200.]) * (1 - al)
    edge = (oarr[..., 3] > 8) & (oarr[..., 3] < 247)
    if edge.sum() > 100:
        r, g, b = comp[..., 0][edge], comp[..., 1][edge], comp[..., 2][edge]
        spill = float(np.mean(np.abs(r - g) + np.abs(b - g)))
    else:
        spill = 0.0
    return {"psnr_rgb": round(psnr_rgb, 2), "psnr_alpha": round(psnr_a, 2),
            "ssim": round(float(sm), 4), "sharp": round(sharp, 2),
            "edge_spill": round(spill, 2)}


def bbox(mask: np.ndarray):
    ys = np.where((mask > 8).mean(axis=1) > 0.02)[0]
    xs = np.where((mask > 8).mean(axis=0) > 0.02)[0]
    if len(ys) == 0 or len(xs) == 0:
        return 0, mask.shape[0], 0, mask.shape[1]
    return int(ys[0]), int(ys[-1]) + 1, int(xs[0]), int(xs[-1]) + 1


def main():
    report = {}
    for name, src in SAMPLES.items():
        if not src.exists():
            print(f"[跳过] {name}")
            continue
        print(f"\n=== {name} {Image.open(src).size} ===")
        row = {}
        for tag, kind, args in METHODS:
            got = run_method(tag, kind, args, src)
            if not got:
                continue
            outp, dt = got
            factor = (args[1] if kind == "pil" else int(args[args.index("-s") + 1]))
            m = eval_one(src, outp, factor)
            m["factor"] = factor
            m["seconds"] = round(dt, 2)
            row[tag] = m
            print(f"  {tag:<18} x{factor} {str(Image.open(outp).size):<14} "
                  f"PSNRrgb {m['psnr_rgb']:>6} αPSNR {m['psnr_alpha']:>6} "
                  f"SSIM {m['ssim']:.4f} 锐度 {m['sharp']:>6.2f} 溢色 {m['edge_spill']:>6.1f} {dt:>6.2f}s")
        report[name] = row
    (RES / "评估指标.json").write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                       encoding="utf-8")
    print(f"\n指标已存 {RES / '评估指标.json'}")


if __name__ == "__main__":
    main()
