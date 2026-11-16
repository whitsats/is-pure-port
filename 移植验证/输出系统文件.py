"""导出光盘上的系统文件（ELF、IOPRP、IRX 模块、INIT.BIN、SYSTEM.CNF）。"""
from __future__ import annotations

import struct
from pathlib import Path

from 本地路径 import ORIGINAL_ISO

ISO = ORIGINAL_ISO
OUT = Path(__file__).resolve().parent / "输出-保护边修复" / "SYSTEM"
SECTOR = 2048


def iso_files(iso: Path):
    out = {}
    with iso.open("rb") as f:
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


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    files = iso_files(ISO)
    skip_ext = (".afs", ".pss")
    n = 0
    total = 0
    with ISO.open("rb") as f:
        for name, meta in sorted(files.items()):
            if name.lower().endswith(skip_ext):
                continue
            f.seek(meta["lba"] * SECTOR)
            data = f.read(meta["size"])
            (OUT / name).write_bytes(data)
            n += 1
            total += len(data)
            print(f"  {name:<20} {meta['size']:>10} B")
    print(f"\n系统文件 {n} 个，合计 {total/1048576:.2f} MB -> {OUT}")


if __name__ == "__main__":
    main()
