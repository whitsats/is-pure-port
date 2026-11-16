"""核查通过结构检查的脚本中的 reg_calc 17 表入口，不猜测表长度。"""
import json
import struct
from collections import Counter
from pathlib import Path

import MAC_命令表提取 as common

ROOT = Path(__file__).resolve().parent


def main():
    checks = json.loads((ROOT / 'MAC_命令表/脚本验证.json').read_text(encoding='utf-8'))
    table = common.load_table(common.ELF.read_bytes())
    patterns = Counter()
    for name, info in checks.items():
        if info['status'] != 'ok':
            continue
        data = (common.SCRIPTS / name).read_bytes()
        starts, found, p = set(), [], 0
        while p < info['boundary']:
            starts.add(p)
            op = data[p]
            if op == 9 and data[p + 1] == 17:
                found.append(p)
            p += table[op]['bytes']
        if p != info['boundary']:
            raise ValueError(f'指令边界不一致：{name}')
        for p in found:
            source, address = struct.unpack_from('<HH', data, p + 2)
            if address + 4 > len(data):
                raise ValueError(f'表项超出文件：{name}')
            target = struct.unpack_from('<I', data, address)[0]
            patterns[(p, source, address, target, target in starts)] += 1
    for pattern, count in patterns.items():
        p, source, address, target, valid = pattern
        print(f'指令={p:#x} 索引操作数={source:#x} 表位置={address:#x} '
              f'表项0={target:#x} 是指令边界={valid}: {count} 处')
    if sum(patterns.values()) != 61:
        raise ValueError('样本数量与此前统计不一致')


if __name__ == '__main__':
    main()
