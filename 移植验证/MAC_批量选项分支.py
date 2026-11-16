"""保守提取已知 0x72 选项及返回值到目标的静态映射。"""
import argparse
import csv
import json
import struct
from pathlib import Path

import MAC_命令表提取 as common

ROOT = Path(__file__).resolve().parent
CHECKS = ROOT / "MAC_命令表" / "脚本验证.json"


def u16(d, p):
    return struct.unpack_from("<H", d, p)[0]


def u32(d, p):
    return struct.unpack_from("<I", d, p)[0]


def inspect(data, selection, text_start, starts):
    count = data[selection + 1]
    table = u32(data, selection + 4)
    if not 2 <= count <= 6 or table + count * 12 > text_start:
        raise ValueError("unsupported selection table")
    if data[selection + 2:selection + 4] != b"\x07\x60":
        raise ValueError("unexpected selection destination")
    if data[selection + 12:selection + 20] != bytes.fromhex("09 00 00 60 07 60 00 00"):
        raise ValueError("unexpected register copy")
    rows = []
    for i in range(count):
        p = selection + 20 + 16 * i
        if p + 16 > text_start or data[p:p + 4] != bytes.fromhex("02 00 00 00"):
            raise ValueError("unexpected condition instruction")
        if (u16(data, p + 8), u16(data, p + 10), data[p + 12], data[p + 13]) != (0x6000, i, 0, 0):
            raise ValueError("unexpected comparison")
        target = u32(data, p + 4)
        if target not in starts:
            raise ValueError("branch target is not an instruction boundary")
        ptr, field1, field2 = struct.unpack_from("<III", data, table + 12 * i)
        if not text_start <= ptr < len(data):
            raise ValueError("selection text outside text region")
        end = data.find(b"\0", ptr)
        if end < 0:
            raise ValueError("unterminated selection text")
        text = data[ptr:end].decode("cp932")
        rows.append((i, text, target, field1, field2))
    if len({row[2] for row in rows}) != count:
        raise ValueError("repeated branch target")
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "MAC_命令表" / "选项分支静态映射.tsv")
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(f"Not overwriting {args.output}")
    table = common.load_table(common.ELF.read_bytes())
    checks = json.loads(CHECKS.read_text(encoding="utf-8"))
    rows, skipped = [], []
    import MAC_解析 as mac
    entries = mac.entries(mac.load())
    names = {f"MAC_{e['i']:03}.bin": e["name"] for e in entries}
    for filename, info in checks.items():
        if info["status"] != "ok":
            continue
        data = (common.SCRIPTS / filename).read_bytes()
        commands, starts, p = [], set(), 0
        while p < info["boundary"]:
            starts.add(p)
            op = data[p]
            commands.append((p, op))
            p += table[op]["bytes"]
        for p, op in commands:
            if op != 0x72:
                continue
            try:
                options = inspect(data, p, info["text_start"], starts)
            except (ValueError, UnicodeDecodeError, struct.error) as exc:
                skipped.append((filename, hex(p), str(exc)))
                continue
            for index, text, target, field1, field2 in options:
                rows.append((filename, names.get(filename, ""), f"0x{p:06X}", index,
                             text, f"0x{target:06X}", f"0x{field1:08X}", f"0x{field2:08X}"))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f, delimiter="\t")
        writer.writerow(["文件", "原剧本名", "选项指令偏移", "假设返回值", "日文选项", "静态跳转目标", "记录字段1", "记录字段2"])
        writer.writerows(rows)
    print(f"静态映射 {len(rows)} 条；未处理 {len(skipped)} 处：{skipped}")
    print(args.output)


if __name__ == "__main__":
    main()
