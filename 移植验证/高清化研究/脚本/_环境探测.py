"""环境探测：GPU / Python 包 / 联网能力。"""
from __future__ import annotations

import importlib
import shutil
import subprocess
import sys


def gpu_info():
    cmds = [
        ["wmic", "path", "win32_VideoController", "get", "name,adapterram,driverversion"],
        ["powershell", "-NoProfile", "-Command",
         "Get-CimInstance Win32_VideoController | Select-Object Name,AdapterRAM,DriverVersion | Format-List"],
    ]
    for c in cmds:
        exe = shutil.which(c[0])
        if not exe:
            continue
        try:
            r = subprocess.run(c, capture_output=True, text=True, timeout=30)
            out = (r.stdout or "") + (r.stderr or "")
            if out.strip():
                return out.strip()
        except Exception as e:  # noqa: BLE001
            return f"{c[0]} 失败: {e}"
    return "无法获取"


def main():
    print("=== Python ===", sys.version.replace("\n", " "))
    print("\n=== GPU ===")
    print(gpu_info())

    print("\n=== 相关包 ===")
    for m in ("torch", "torchvision", "cv2", "basicsr", "realesrgan", "numpy",
              "PIL", "onnxruntime", "scipy", "skimage"):
        try:
            mod = importlib.import_module(m)
            ver = getattr(mod, "__version__", "?")
            print(f"  {m:12} OK   {ver}")
        except Exception as e:  # noqa: BLE001
            print(f"  {m:12} --   {type(e).__name__}")

    # torch 是否能看见 GPU
    try:
        import torch  # noqa: F811
        print(f"\n  torch.cuda.is_available = {torch.cuda.is_available()}")
        if torch.cuda.is_available():
            print(f"  GPU: {torch.cuda.get_device_name(0)}")
        print(f"  torch.backends.mps = {getattr(torch.backends, 'mps', None)}")
    except Exception:  # noqa: BLE001
        pass

    print("\n=== 联网 ===")
    try:
        r = subprocess.run(["python", "-c",
                            "import urllib.request;"
                            "print(urllib.request.urlopen('https://pypi.org/simple/', timeout=10).status)"],
                           capture_output=True, text=True, timeout=30)
        print("  pypi:", (r.stdout or r.stderr).strip()[:200])
    except Exception as e:  # noqa: BLE001
        print("  pypi 探测失败:", e)

    print("\n=== ffmpeg ===")
    try:
        r = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True, timeout=20)
        print("  " + r.stdout.splitlines()[0])
    except Exception as e:  # noqa: BLE001
        print("  失败:", e)


if __name__ == "__main__":
    main()
