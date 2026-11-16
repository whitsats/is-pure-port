"""只读检查已验证剧本中的跳转目标和 0x72 选项文本。"""
from collections import Counter
from pathlib import Path
import csv
import json
import struct

import MAC_命令表提取 as extractor

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "MAC_命令表"


def main():
    table = extractor.load_table(extractor.ELF.read_bytes())
    checks = json.loads((OUT / "脚本验证.json").read_text(encoding="utf-8"))
    target_tsv = OUT / "选项文本_原文.tsv"
    target_json = OUT / "分支选项核验.json"
    if target_tsv.exists() or target_json.exists():
        raise FileExistsError("核验输出已存在，未覆盖")
    stats, unresolved, rows = Counter(), [], []
    for filename, check in checks.items():
        if check["status"] != "ok":
            continue
        data = (extractor.SCRIPTS / filename).read_bytes()
        pos, commands, starts = 0, [], set()
        while pos < check["boundary"]:
            starts.add(pos)
            op = data[pos]
            commands.append((pos, op))
            pos += table[op]["bytes"]
        for pos, op in commands:
            if op in (0x02, 0x03, 0x04):
                target = struct.unpack_from("<I", data, pos + 4)[0]
                stats[f"{op:02x}_target_instruction" if target in starts else f"{op:02x}_target_other"] += 1
            if op != 0x72:
                continue
            count = data[pos + 1]
            target = struct.unpack_from("<I", data, pos + 4)[0]
            stats["selection_commands"] += 1
            if not count or target + count * 12 > check["text_start"]:
                unresolved.append({"file": filename, "offset": pos, "reason": "table_out_of_bounds"})
                continue
            options = []
            for i in range(count):
                ptr, field1, field2 = struct.unpack_from("<III", data, target + i * 12)
                end = data.find(b"\0", ptr) if check["text_start"] <= ptr < len(data) else -1
                if end < 0:
                    break
                try:
                    text = data[ptr:end].decode("cp932")
                except UnicodeDecodeError:
                    break
                options.append([filename, f"0x{pos:06X}", i, f"0x{target + i * 12:06X}",
                                f"0x{ptr:06X}", f"0x{field1:08X}", f"0x{field2:08X}", text])
            if len(options) != count:
                unresolved.append({"file": filename, "offset": pos, "reason": "unresolved_option_record"})
                continue
            stats["selection_tables_decoded"] += 1
            stats["selection_options"] += count
            rows.extend(options)
    with target_tsv.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f, delimiter="\t")
        writer.writerow(["脚本", "指令偏移", "表内序号", "记录偏移", "文本偏移", "字段1未知", "字段2未知", "日文原文"])
        writer.writerows(rows)
    target_json.write_text(json.dumps({"counts": dict(stats), "unresolved": unresolved},
                          ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("统计:", dict(stats), "待处理:", unresolved)


if __name__ == "__main__":
    main()
