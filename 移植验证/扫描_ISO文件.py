"""遍历 ISO9660 目录，列出所有文件（名称、LBA、大小），识别视频/音频等。"""
from __future__ import annotations

import struct
from pathlib import Path

from 本地路径 import ORIGINAL_ISO

ISO = ORIGINAL_ISO


def read_sector(f, lba, count=1, sector=2048):
    f.seek(lba * sector)
    return f.read(sector * count)


def parse_dir(f, lba, size, depth=0, out=None):
    if out is None:
        out = []
    data = read_sector(f, lba, max(1, (size + 2047) // 2048))
    pos = 0
    while pos < len(data):
        rec_len = data[pos]
        if rec_len == 0:
            # 跳到下一个扇区边界
            pos = (pos // 2048 + 1) * 2048
            if pos >= len(data):
                break
            continue
        rec = data[pos : pos + rec_len]
        ext_attr_len = rec[1]
        extent_lba = struct.unpack_from("<I", rec, 2)[0]
        data_len = struct.unpack_from("<I", rec, 10)[0]
        flags = rec[25]
        name_len = rec[32]
        name = rec[33 : 33 + name_len]
        pos += rec_len
        if name in (b"\x00", b"\x01"):
            continue
        try:
            nm = name.decode("ascii")
        except UnicodeDecodeError:
            nm = name.decode("latin-1", "replace")
        if ";" in nm:
            nm = nm.split(";")[0]
        is_dir = bool(flags & 0x02)
        out.append({"name": nm, "lba": extent_lba, "size": data_len, "dir": is_dir,
                    "depth": depth})
        if is_dir and depth < 4:
            parse_dir(f, extent_lba, data_len, depth + 1, out)
    return out


def main():
    with ISO.open("rb") as f:
        # PVD 在 LBA 16
        pvd = read_sector(f, 16)
        if pvd[1:6] != b"CD001":
            print("不是 ISO9660")
            return
        root = pvd[156 : 156 + 34]
        root_lba = struct.unpack_from("<I", root, 2)[0]
        root_size = struct.unpack_from("<I", root, 10)[0]
        entries = parse_dir(f, root_lba, root_size)

        files = [e for e in entries if not e["dir"]]
        print(f"文件总数 {len(files)}")
        print(f"\n{'名称':<44} {'LBA':>9} {'大小(MB)':>9}")
        for e in sorted(files, key=lambda x: -x["size"])[:40]:
            print(f"{e['name']:<44} {e['lba']:>9} {e['size']/1048576:>9.2f}")

        print("\n=== 按扩展名统计 ===")
        ext = {}
        for e in files:
            k = e["name"].rsplit(".", 1)[-1].lower() if "." in e["name"] else "(无)"
            ext[k] = ext.get(k, 0) + 1
        for k, v in sorted(ext.items(), key=lambda x: -x[1]):
            print(f"  {k:<12} {v}")

        print("\n=== 可能的视频文件 ===")
        for e in files:
            low = e["name"].lower()
            if any(low.endswith(s) for s in (".pss", ".sfd", ".m2v", ".mpg", ".mpeg", ".ipu", ".mov", ".avi")):
                print(f"  {e['name']}  LBA {e['lba']}  {e['size']/1048576:.2f} MB")


if __name__ == "__main__":
    main()
