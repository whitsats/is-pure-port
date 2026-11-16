"""从四个调试剧本的第 0 入口起线性检查；不把覆盖区域外的目标认定为错误。"""
import json
import struct
from pathlib import Path

import MAC_命令表提取 as common

ROOT = Path(__file__).resolve().parent


def main():
    checks = json.loads((ROOT / 'MAC_命令表/脚本验证.json').read_text(encoding='utf-8'))
    table = common.load_table(common.ELF.read_bytes())
    for name in ('MAC_063.bin', 'MAC_064.bin', 'MAC_065.bin', 'MAC_069.bin'):
        data = (common.SCRIPTS / name).read_bytes()
        entry = struct.unpack_from('<I', data, 8)[0]
        boundary = checks[name]['boundary']
        p, starts, edges = entry, set(), []
        while p < boundary:
            starts.add(p)
            opcode = data[p]
            if opcode >= len(table) or not table[opcode]['bytes']:
                raise ValueError(f'{name}: 不支持的命令 {opcode:#x} @ {p:#x}')
            length = table[opcode]['bytes']
            if p + length > boundary:
                raise ValueError(f'{name}: 命令越过边界 @ {p:#x}')
            if opcode in (2, 3, 4):
                edges.append(struct.unpack_from('<I', data, p + 4)[0])
            p += length
        local = sum(target in starts for target in edges)
        print(f'{name}: 入口={entry:#x} 结束={p:#x} 指令={len(starts)} '
              f'固定目标={len(edges)} 范围内边界={local} 范围外或未对齐={len(edges)-local}')


if __name__ == '__main__':
    main()
