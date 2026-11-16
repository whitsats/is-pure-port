"""统计已通过结构检查的 MAC 脚本中 if 的编码形式；不推断运行时状态。"""
from collections import Counter
from pathlib import Path
import csv
import json
import struct

import MAC_命令表提取 as common

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "MAC_命令表" / "条件指令覆盖.tsv"


def kind(raw):
    k = raw & 0xC000
    if k == 0x4000:
        return "状态值"
    if k == 0x8000:
        return "状态位"
    return "立即数"


def main():
    if OUT.exists():
        raise FileExistsError(OUT)
    checks = json.loads((ROOT / "MAC_命令表/脚本验证.json").read_text(encoding="utf-8"))
    table = common.load_table(common.ELF.read_bytes())
    rows = []
    counts = Counter()
    for filename, info in checks.items():
        if info["status"] != "ok":
            continue
        data = (common.SCRIPTS / filename).read_bytes()
        p = 0
        while p < info["boundary"]:
            op = data[p]
            length = table[op]["bytes"]
            if op == 2:
                ins = data[p:p + length]
                if len(ins) != 16:
                    raise ValueError(f"Unexpected if length at {filename}:{p:x}")
                left, right = struct.unpack_from("<HH", ins, 8)
                covered = ins[1] == 0 and ins[13] == 0 and ins[12] in (0, 1, 3, 4, 5)
                key = (ins[1], ins[12], ins[13], kind(left), kind(right), covered)
                counts[key] += 1
                rows.append((filename, f"0x{p:06X}", f"0x{struct.unpack_from('<I', ins, 4)[0]:06X}",
                             f"0x{left:04X}", f"0x{right:04X}", ins[1], ins[12], ins[13],
                             "支持" if covered else "未支持"))
            p += length
        if p != info["boundary"]:
            raise ValueError(f"Boundary mismatch: {filename}")
    with OUT.open("x", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f, delimiter="\t")
        writer.writerow(["剧本", "指令偏移", "目标偏移", "左操作数", "右操作数", "模式", "比较类型", "组合类型", "静态格式支持"])
        writer.writerows(rows)
    print("条件数:", len(rows), "格式支持:", sum(v for k, v in counts.items() if k[-1]))
    for k, v in sorted(counts.items()):
        print(k, v)
    print("输出:", OUT)


if __name__ == "__main__":
    main()
