"""超分方案基准测试：在真实素材上跑多种模型，记录耗时并输出样张。

输出到 移植验证/高清化测试/：
  <素材>_<方案>.png          超分结果
  <素材>_<方案>_crop.png     与 Lanczos 的局部对比裁切
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
ASSETS = HERE / "输出-保护边修复"
TOOLS = Path(r"E:\Entertainment\IS\is-pure-zh\工具\超分")
OUT = HERE / "高清化测试"
RR = TOOLS / "realesrgan-ncnn-vulkan.exe"
RC = TOOLS / "realcugan-ncnn-vulkan-20220728-windows" / "realcugan-ncnn-vulkan.exe"

SAMPLES = {
    "BG": ASSETS / "BG" / "BG_0000.png",
    "CHR_full": ASSETS / "CHR" / "CHR_0000.png",
    "EV": ASSETS / "EV" / "EV_0000.png",
    "ETC_menu": None,  # 下面按尺寸挑一个 640×448 的 UI 图
}
METHODS = [
    ("esrgan_x4anime", RR, ["-n", "realesrgan-x4plus-anime", "-g", "0"]),
    ("esrgan_v3x3", RR, ["-n", "realesr-animevideov3-x3", "-g", "0"]),
    ("esrgan_v3x4", RR, ["-n", "realesr-animevideov3-x4", "-g", "0"]),
    ("cugan_up3x", RC, ["-n", "up3x-conservative", "-s", "3", "-g", "0"]),
    ("cugan_up2x", RC, ["-n", "up2x-conservative", "-s", "2", "-g", "0"]),
]


def pick_etc_menu():
    for p in sorted((ASSETS / "ETC").glob("*.png")):
        with Image.open(p) as im:
            if im.size == (640, 448):
                return p
    return None


def run(cmd: list[str], inp: Path, outp: Path) -> float:
    t0 = time.time()
    r = subprocess.run(cmd + ["-i", str(inp), "-o", str(outp)],
                       capture_output=True, text=True, timeout=1800)
    dt = time.time() - t0
    if r.returncode != 0 or not outp.exists():
        tail = (r.stderr or r.stdout)[-300:]
        raise RuntimeError(f"{cmd[0].split(chr(92))[-1]} 失败: {tail}")
    return dt


def main():
    OUT.mkdir(exist_ok=True)
    SAMPLES["ETC_menu"] = pick_etc_menu()
    results = []
    for sname, spath in SAMPLES.items():
        if not spath or not spath.exists():
            print(f"[跳过] {sname}")
            continue
        with Image.open(spath) as im:
            print(f"\n=== {sname}: {spath.name} {im.size} {im.mode} ===")
        # Lanczos 基线（放大 3 倍）
        t0 = time.time()
        with Image.open(spath) as im:
            base = im.resize((im.width * 3, im.height * 3), Image.LANCZOS)
        base.save(OUT / f"{sname}_lanczos3x.png")
        results.append((sname, "lanczos3x", time.time() - t0, base.size, "PIL"))
        print(f"  lanczos3x      {base.size}  {time.time()-t0:.2f}s")

        for mname, exe, args in METHODS:
            outp = OUT / f"{sname}_{mname}.png"
            try:
                dt = run([str(exe)] + args, spath, outp)
                with Image.open(outp) as im:
                    sz, mode = im.size, im.mode
                results.append((sname, mname, dt, sz, mode))
                print(f"  {mname:<14} {sz} {mode}  {dt:.2f}s")
            except Exception as e:  # noqa: BLE001
                print(f"  {mname:<14} 失败: {str(e)[:160]}")

    print("\n=== 汇总 ===")
    for r in results:
        print(f"  {r[0]:<10} {r[1]:<15} {str(r[3]):<14} {r[4]:<6} {r[2]:.2f}s")


if __name__ == "__main__":
    main()
