"""提取并转码视频：MV_OP01 / MV_END01 / MV_LG01（PS2 CRI Sofdec .PSS）。

步骤：
  1. 按 ISO9660 目录中的 LBA/大小直接从镜像切出 .pss；
  2. 用 ffmpeg 探测/转码为 MP4（H.264 + AAC），同时保留原始 .pss。
"""
from __future__ import annotations

import json
import subprocess
import struct
from pathlib import Path

from 本地路径 import ORIGINAL_ISO

ISO = ORIGINAL_ISO
OUT = Path(__file__).resolve().parent / "输出-保护边修复" / "MV"
SECTOR = 2048

VIDEOS = {
    "MV_OP01": {"lba": 825001, "size": 65938432 * 0 + 0},  # 大小由目录读取后填
    "MV_END01": {"lba": 857202, "size": 0},
    "MV_LG01": {"lba": 824432, "size": 0},
}


def iso_dirs():
    """返回 {文件名: {lba, size}}。"""
    out = {}
    with ISO.open("rb") as f:
        f.seek(16 * SECTOR)
        pvd = f.read(SECTOR)
        root = pvd[156 : 156 + 34]
        root_lba = struct.unpack_from("<I", root, 2)[0]
        root_size = struct.unpack_from("<I", root, 10)[0]

        def walk(lba, size):
            f.seek(lba * SECTOR)
            data = f.read(((size + SECTOR - 1) // SECTOR) * SECTOR)
            pos = 0
            while pos < len(data):
                rl = data[pos]
                if rl == 0:
                    pos = (pos // SECTOR + 1) * SECTOR
                    continue
                rec = data[pos : pos + rl]
                pos += rl
                elba = struct.unpack_from("<I", rec, 2)[0]
                dlen = struct.unpack_from("<I", rec, 10)[0]
                flags = rec[25]
                nl = rec[32]
                name = rec[33 : 33 + nl]
                if name in (b"\x00", b"\x01"):
                    continue
                nm = name.decode("latin-1", "replace").split(";")[0]
                if flags & 0x02:
                    walk(elba, dlen)
                else:
                    out[nm] = {"lba": elba, "size": dlen}

        walk(root_lba, root_size)
    return out


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    files = iso_dirs()
    print("视频条目:")
    for name, meta in files.items():
        if name.lower().endswith(".pss"):
            print(f"  {name}: LBA {meta['lba']}  {meta['size']/1048576:.2f} MB")

    with ISO.open("rb") as f:
        for name, meta in sorted(files.items()):
            if not name.lower().endswith(".pss"):
                continue
            stem = name.rsplit(".", 1)[0]
            dst = OUT / name
            f.seek(meta["lba"] * SECTOR)
            data = f.read(meta["size"])
            dst.write_bytes(data)
            print(f"\n提取 {name} -> {dst} ({len(data)} B)")

            # 探测
            probe = subprocess.run(
                ["ffprobe", "-hide_banner", "-loglevel", "error", "-print_format", "json",
                 "-show_format", "-show_streams", str(dst)],
                capture_output=True, text=True,
            )
            ok = probe.returncode == 0
            info = {}
            if ok:
                try:
                    info = json.loads(probe.stdout or "{}")
                except json.JSONDecodeError:
                    info = {}
            fmt = info.get("format", {})
            streams = info.get("streams", [])
            print(f"  ffprobe: rc={probe.returncode} format={fmt.get('format_name')} "
                  f"duration={fmt.get('duration')}")
            for s in streams:
                print(f"    stream {s.get('index')}: {s.get('codec_type')}/{s.get('codec_name')} "
                      f"{s.get('width','')}x{s.get('height','')} {s.get('sample_rate','')}Hz "
                      f"{s.get('channels','')}ch")
            if not ok:
                print(f"    ffprobe stderr: {probe.stderr.strip()[:400]}")
                continue

            # 转 MP4
            mp4 = OUT / f"{stem}.mp4"
            conv = subprocess.run(
                ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(dst),
                 "-c:v", "libx264", "-preset", "medium", "-crf", "18",
                 "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", str(mp4)],
                capture_output=True, text=True,
            )
            if conv.returncode == 0:
                print(f"  转码成功 -> {mp4} ({mp4.stat().st_size/1048576:.2f} MB)")
            else:
                print(f"  转码失败：{conv.stderr.strip()[:400]}")
                # 退化：只抽视频轨
                m2v = OUT / f"{stem}.m2v"
                conv2 = subprocess.run(
                    ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(dst),
                     "-c:v", "copy", "-an", str(m2v)],
                    capture_output=True, text=True,
                )
                print(f"    抽视频轨 rc={conv2.returncode} {conv2.stderr.strip()[:200]}")


if __name__ == "__main__":
    main()
