"""MAC.AFS 剧本核心解析库。

结构（已全量验证：74/74 脚本恰好解析到文本区起点）：
  MAC.AFS = AFS 容器：头 + 条目表(8B/条) + 数据 + 元数据表(48B/条，前 32B 为文件名)
  每个条目 = LZSS 压缩的脚本，解压后：
    [指令区] 0 .. text_start   指令 = 4 字节 [op][p1][p2][p3]
    [文本区] text_start .. EOF 连续的 cp932 文本，`%K`=换行 `%P`=翻页，NUL 结尾
  文本指令（12 字节）：
    60 00 00 00 | ptr:u32 | 行号:u16 | 语音号:u16
    - ptr 指向 cp932 文本；行号在每个脚本内从 0 递增；
    - 语音号 0xFFFF = 无语音，否则直接是 VOICE.AFS 的条目号（实测最大 12789 = 12790-1）。
"""
from __future__ import annotations

import struct
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import decode_clean_30 as dc  # noqa: E402

from 本地路径 import ORIGINAL_ISO

ISO = ORIGINAL_ISO
MAC_LBA = 192346
MAC_SIZE = 1_081_344


def load(path: Path = ISO) -> bytes:
    with path.open("rb") as f:
        f.seek(MAC_LBA * 2048)
        return f.read(MAC_SIZE)


def entries(data: bytes) -> list[dict]:
    magic, count = struct.unpack_from("<4sI", data, 0)
    if magic != b"AFS\x00":
        raise ValueError(f"不是 AFS：{magic!r}")
    meta, metalen = struct.unpack_from("<II", data, 8 + count * 8)
    out = []
    for i in range(count):
        off, size = struct.unpack_from("<II", data, 8 + i * 8)
        nm = data[meta + i * 48 : meta + i * 48 + 32].split(b"\0")[0].decode("ascii", "replace")
        out.append({"i": i, "name": nm, "off": off, "size": size})
    return out


def script(data: bytes, e: dict) -> bytes:
    return dc.unpack_lzss(data[e["off"] : e["off"] + e["size"]])


def split_script(scr: bytes):
    """返回 (指令列表 [(pos, op, args3, ptr)], 文本区起点)。"""
    p = 0
    seen = set()
    ops = []
    while p + 4 <= len(scr):
        if p in seen:
            break
        op = scr[p]
        args = (scr[p + 1], scr[p + 2], scr[p + 3])
        if op == 0x60 and args == (0, 0, 0) and p + 8 <= len(scr):
            ptr = struct.unpack_from("<I", scr, p + 4)[0]
            ops.append((p, op, args, ptr))
            if 0 < ptr < len(scr):
                seen.add(ptr)
            p += 8
        else:
            ops.append((p, op, args, None))
            p += 4
    return ops, p


def texts(scr: bytes, ops):
    """提取文本记录：[(pos, 行号, 语音号, 日文)]。"""
    out = []
    for k, (pos, op, args, ptr) in enumerate(ops):
        if ptr is None or k + 1 >= len(ops):
            continue
        npos, nop, nargs, nptr = ops[k + 1]
        if nptr is not None:
            continue
        line = nop | (nargs[0] << 8)
        vid = nargs[1] | (nargs[2] << 8)
        out.append((pos, line, vid, read_text(scr, ptr)))
    return out


def read_text(scr: bytes, ptr: int) -> str:
    if not (0 < ptr < len(scr)):
        return "<越界>"
    e = scr.find(b"\x00", ptr)
    if e < 0:
        e = min(len(scr), ptr + 400)
    try:
        return scr[ptr:e].decode("cp932")
    except UnicodeDecodeError:
        return scr[ptr:e].decode("cp932", "replace")


def is_debug(name: str) -> bool:
    return name.startswith("DBG_")
