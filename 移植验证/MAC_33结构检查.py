"""只读验证 MAC 中 0x33 候选引用和 12 字节记录排列。"""
from collections import Counter
from pathlib import Path
import struct

import MAC_解析 as mac

FOLDER = Path(__file__).resolve().parent / "输出-保护边修复" / "MAC"
PATTERNS = {(1, 0, 0), (1, 1, 0), (2, 0, 0), (3, 0, 0)}


def main():
    totals, transitions = Counter(), Counter()
    for path in sorted(FOLDER.glob("MAC_*.bin")):
        data = path.read_bytes()
        ops, text_start = mac.split_script(data)
        refs = []
        for pos, op, args, _ in ops:
            if op != 0x33 or args not in PATTERNS or pos + 8 > text_start:
                continue
            target = struct.unpack_from("<I", data, pos + 4)[0]
            valid = target % 4 == 0 and pos + 8 <= target and target + 12 * args[0] <= text_start
            totals["有效引用" if valid else "无效候选"] += 1
            if valid:
                refs.append((pos, args[0], target))
        if refs:
            totals["有引用的文件"] += 1
        for current, following in zip(refs, refs[1:]):
            delta = following[2] - current[2]
            transitions[(current[1], delta)] += 1
            if delta != 12 * current[1]:
                totals["间距异常"] += 1
                print("异常", path.name, current, following)
    print("统计:", dict(totals))
    print("前一条数量、目标偏移差:", dict(sorted(transitions.items())))


if __name__ == "__main__":
    main()
