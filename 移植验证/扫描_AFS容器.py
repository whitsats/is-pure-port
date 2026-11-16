"""扫描 ISO 中所有 AFS 容器，列出偏移、条目数、解压长度分布，判断还有哪些素材未输出。"""
from __future__ import annotations

import struct
from pathlib import Path

from 本地路径 import ORIGINAL_ISO

ISO = ORIGINAL_ISO


def scan_afs(iso: Path) -> list[dict]:
    size = iso.stat().st_size
    hits = []
    with iso.open("rb") as f:
        pos = 0
        CHUNK = 4 * 1024 * 1024
        overlap = b""
        while pos < size:
            f.seek(pos)
            buf = f.read(CHUNK)
            if not buf:
                break
            data = overlap + buf
            start = 0
            while True:
                i = data.find(b"AFS\0", start)
                if i < 0:
                    break
                abs_off = pos - len(overlap) + i
                start = i + 4
                # 解析
                if abs_off + 8 > size:
                    continue
                f.seek(abs_off)
                hdr = f.read(8)
                cnt = struct.unpack("<I", hdr[4:8])[0]
                if not (1 <= cnt <= 20000):
                    continue
                if abs_off + 8 + cnt * 8 > size:
                    continue
                f.seek(abs_off + 8)
                table = f.read(cnt * 8)
                offs = []
                ok = True
                for k in range(cnt):
                    off, ln = struct.unpack("<II", table[k * 8 : k * 8 + 8])
                    if off == 0 or ln == 0:
                        continue
                    if abs_off + off + ln > size:
                        ok = False
                        break
                    offs.append((off, ln))
                if not ok or not offs:
                    continue
                hits.append({
                    "offset": abs_off, "count": cnt, "valid": len(offs),
                    "first_off": offs[0][0],
                    "total_len": sum(l for _, l in offs),
                })
            overlap = data[-4:]
            pos += CHUNK
    # 去重（同一偏移可能出现多次）
    uniq = {}
    for h in hits:
        uniq.setdefault(h["offset"], h)
    return sorted(uniq.values(), key=lambda h: h["offset"])


def main() -> None:
    print(f"扫描 {ISO} …")
    afs = scan_afs(ISO)
    print(f"发现 {len(afs)} 个 AFS 容器\n")
    print(f"{'ISO偏移':>12} {'LBA':>9} {'条目':>6} {'有效':>6} {'总长(MB)':>10}")
    for h in afs:
        print(f"{h['offset']:>12} {h['offset']//2048:>9} {h['count']:>6} {h['valid']:>6} "
              f"{h['total_len']/1048576:>10.1f}")


if __name__ == "__main__":
    main()
