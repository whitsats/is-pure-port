"""从原游戏 ELF 中读取 MAC 命令表，并保守验证已提取剧本。"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import struct
from pathlib import Path

import MAC_解析 as mac

ROOT = Path(__file__).resolve().parent
ELF = ROOT / "输出-保护边修复" / "SYSTEM" / "SLPM_665.70"
SCRIPTS = ROOT / "输出-保护边修复" / "MAC"
TABLE_VADDR = 0x213590
ENTRY_SIZE = 24
PATTERNS = {(1, 0, 0), (1, 1, 0), (2, 0, 0), (3, 0, 0)}


def load_table(data):
    if data[:6] != b"\x7fELF\x01\x01":
        raise ValueError("Expected 32-bit little-endian ELF")
    e = struct.unpack_from("<16sHHIIIIIHHHHHH", data)
    phoff, phsize, phcount = e[5], e[9], e[10]
    segments = [struct.unpack_from("<8I", data, phoff + i * phsize) for i in range(phcount)]

    def file_offset(address, size=1):
        for kind, offset, vaddr, _, filesz, _, _, _ in segments:
            if kind == 1 and vaddr <= address and address + size <= vaddr + filesz:
                return offset + address - vaddr
        raise ValueError(f"Address {address:#x} is not within an ELF load segment")

    start = file_offset(TABLE_VADDR, 121 * ENTRY_SIZE)
    result = []
    for opcode in range(120):
        handler, name_ptr, extra, mode1, mode2, length = struct.unpack_from(
            "<6I", data, start + opcode * ENTRY_SIZE)
        file_offset(handler, 4)
        off = file_offset(name_ptr)
        end = data.find(b"\0", off, min(len(data), off + 64))
        if end < 0:
            raise ValueError(f"Unterminated name at opcode {opcode:#x}")
        name = data[off:end].decode("ascii")
        if not re.fullmatch(r"[a-z0-9_]+", name) or length not in {0, 4, 8, 12, 16, 40}:
            raise ValueError(f"Unexpected table row at opcode {opcode:#x}")
        result.append({"opcode": opcode, "name": name, "bytes": length,
                       "handler": handler, "name_vaddr": name_ptr,
                       "unknown_field": extra, "mode1": mode1, "mode2": mode2})
    if struct.unpack_from("<2I", data, start + 120 * ENTRY_SIZE) != (0, 0):
        raise ValueError("Expected command table terminator")
    if result[0x33]["name"] != "graph_disp" or result[0x60]["name"] != "msg_disp2":
        raise ValueError("Command table does not match the expected game")
    return result


def validate_script(data, table):
    legacy, text_start = mac.split_script(data)
    targets = []
    for pos, op, args, _ in legacy:
        if op == 0x33 and args in PATTERNS and pos + 8 <= text_start:
            target = struct.unpack_from("<I", data, pos + 4)[0]
            if target % 4 == 0 and pos + 8 <= target and target + 12 * args[0] <= text_start:
                targets.append(target)
    if not targets:
        return {"status": "no_33_boundary", "text_start": text_start}
    boundary = min(targets)
    pos, anchors, command_count = 0, [], 0
    while pos < boundary:
        op = data[pos]
        if op >= len(table):
            return {"status": "unknown_opcode", "offset": pos, "opcode": op,
                    "boundary": boundary, "text_start": text_start}
        length = table[op]["bytes"]
        if not length or pos + length > boundary:
            return {"status": "variable_or_truncated", "offset": pos, "opcode": op,
                    "length": length, "boundary": boundary, "text_start": text_start}
        if op == 0x60:
            anchors.append(pos)
        pos += length
        command_count += 1
    old_anchors = [p for p, op, _, ptr in legacy if op == 0x60 and ptr is not None and p < boundary]
    return {"status": "ok" if anchors == old_anchors else "anchor_mismatch",
            "boundary": boundary, "text_start": text_start, "commands": command_count,
            "message_count": len(anchors), "legacy_message_count": len(old_anchors)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "MAC_命令表")
    args = parser.parse_args()
    data = ELF.read_bytes()
    table = load_table(data)
    scripts = [(path.name, validate_script(path.read_bytes(), table))
               for path in sorted(SCRIPTS.glob("MAC_*.bin"))]
    if len(scripts) != 74:
        raise ValueError(f"Expected 74 scripts, found {len(scripts)}")
    args.output.mkdir(parents=True, exist_ok=True)
    targets = [args.output / name for name in ("命令表.csv", "脚本验证.json", "来源.json")]
    if any(p.exists() for p in targets):
        raise FileExistsError("Output already exists; choose a new --output directory")
    with targets[0].open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["opcode", "原程序名称", "长度字节", "处理函数地址", "名称地址", "字段2未知", "字段3", "字段4"])
        for row in table:
            writer.writerow([f"0x{row['opcode']:02X}", row["name"], row["bytes"],
                f"0x{row['handler']:08X}", f"0x{row['name_vaddr']:08X}", row["unknown_field"],
                f"0x{row['mode1']:08X}", f"0x{row['mode2']:08X}"])
    targets[1].write_text(json.dumps(dict(scripts), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    targets[2].write_text(json.dumps({"ELF": str(ELF), "sha256": hashlib.sha256(data).hexdigest(),
        "table_vaddr": hex(TABLE_VADDR), "entry_size": ENTRY_SIZE, "entry_count": len(table)},
        ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    counts = {}
    for _, item in scripts:
        counts[item["status"]] = counts.get(item["status"], 0) + 1
    print("Extracted", len(table), "commands; script checks:", counts)
    print("Outputs:", args.output)


if __name__ == "__main__":
    main()
