"""下载超分工具（ncnn-Vulkan 预编译版，无需 Python 依赖，可用 AMD/Intel 核显）。"""
from __future__ import annotations

import sys
import urllib.request
import zipfile
from pathlib import Path

DEST = Path(r"E:\Entertainment\IS\is-pure-zh\工具\超分")
CANDIDATES = {
    "realesrgan-ncnn-vulkan": [
        "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesrgan-ncnn-vulkan-20220424-windows.zip",
        "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesrgan-ncnn-vulkan-20220424-windows.zip",
    ],
    "realcugan-ncnn-vulkan": [
        "https://github.com/nihui/realcugan-ncnn-vulkan/releases/download/20220728/realcugan-ncnn-vulkan-20220728-windows.zip",
    ],
    "waifu2x-ncnn-vulkan": [
        "https://github.com/nihui/waifu2x-ncnn-vulkan/releases/download/20220424/waifu2x-ncnn-vulkan-20220424-windows.zip",
    ],
}


def head_ok(url: str) -> bool:
    try:
        req = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(req, timeout=20) as r:
            return 200 <= r.status < 400
    except Exception:  # noqa: BLE001
        return False


def download(url: str, dest: Path) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=60) as r, dest.open("wb") as f:
            total = int(r.headers.get("Content-Length") or 0)
            got = 0
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
                got += len(chunk)
                if total:
                    print(f"\r    {got/1048576:.1f}/{total/1048576:.1f} MB", end="", flush=True)
        print()
        return True
    except Exception as e:  # noqa: BLE001
        print(f"    失败: {type(e).__name__}: {str(e)[:120]}")
        return False


def main():
    DEST.mkdir(parents=True, exist_ok=True)
    for name, urls in CANDIDATES.items():
        target_dir = DEST / name
        if target_dir.exists() and any(target_dir.iterdir()):
            print(f"[跳过] {name} 已存在")
            continue
        print(f"\n=== {name} ===")
        url = next((u for u in urls if head_ok(u)), None)
        if not url:
            print("   所有 URL 不可达")
            continue
        print(f"   下载 {url}")
        zpath = DEST / f"{name}.zip"
        if not download(url, zpath):
            continue
        try:
            with zipfile.ZipFile(zpath) as z:
                z.extractall(DEST)
            print(f"   已解压到 {DEST}")
        except Exception as e:  # noqa: BLE001
            print(f"   解压失败: {e}")
        finally:
            zpath.unlink(missing_ok=True)

    print("\n=== 结果 ===")
    for p in sorted(DEST.iterdir()):
        if p.is_dir():
            exes = list(p.glob("*.exe"))
            print(f"  {p.name}: {len(list(p.rglob('*')))} 项, exe={[e.name for e in exes]}")


if __name__ == "__main__":
    main()
