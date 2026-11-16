"""静态导出 ext_goto 候选目标；不假设资源组与 AFS 对应关系已完全证实。"""
import csv
import json
import struct
from collections import Counter
from pathlib import Path

import MAC_命令表提取 as common
import MAC_解析 as mac

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'MAC_命令表/跨剧本跳转候选.tsv'
ZERO = bytes.fromhex('09 00 00 60 00 00 00 00')


def main():
    if OUT.exists():
        raise FileExistsError(OUT)
    checks = json.loads((ROOT / 'MAC_命令表/脚本验证.json').read_text(encoding='utf-8'))
    table = common.load_table(common.ELF.read_bytes())
    names = {e['i']: e['name'] for e in mac.entries(mac.load())}
    rows, summary = [], Counter()
    for filename, info in checks.items():
        if info['status'] != 'ok':
            continue
        data = (common.SCRIPTS / filename).read_bytes()
        commands, positions, destinations, p = [], set(), set(), 0
        while p < info['boundary']:
            positions.add(p)
            op = data[p]
            length = table[op]['bytes']
            if op in (2, 3, 4):
                destinations.add(struct.unpack_from('<I', data, p + 4)[0])
            commands.append((p, op, data[p:p + length]))
            p += length
        if p != info['boundary']:
            raise ValueError(f'脚本边界不一致: {filename}')
        for i, (pos, op, raw) in enumerate(commands):
            if op not in (6, 7, 8):
                continue
            summary[f'op_{op:02x}'] += 1
            if op == 8:
                continue
            resource = struct.unpack_from('<H', raw, 2)[0]
            group, index = resource >> 12, resource & 0xFFF
            zero = i > 0 and commands[i - 1][2] == ZERO
            target_file = common.SCRIPTS / f'MAC_{index:03}.bin'
            target_data = target_file.read_bytes() if group == 0 and target_file.exists() else b''
            header_ok = len(target_data) >= 12 and target_data[:8] == bytes.fromhex('09 11 00 60 08 00 00 00')
            entry = struct.unpack_from('<I', target_data, 8)[0] if header_ok else None
            summary['之前清零'] += zero
            summary['直接跳入跳转指令'] += pos in destinations
            summary['目标存在并有已知入口'] += header_ok
            rows.append([filename, f'0x{pos:06X}', 'ext_goto' if op == 6 else 'ext_call',
                         f'0x{resource:04X}', group, index, target_file.name if target_data else '',
                         names.get(index, '') if target_data else '', '是' if zero else '否',
                         '是' if pos in destinations else '否', f'0x{entry:06X}' if entry is not None else ''])
    with OUT.open('x', encoding='utf-8-sig', newline='') as f:
        w = csv.writer(f, delimiter='\t')
        w.writerow(['源脚本', '偏移', '命令', '资源编号', '高4位', '低12位', '候选目标文件', '候选原始名称',
                    '前条清零6000', '本脚本直接目标指向本指令', '候选目标第0入口'])
        w.writerows(rows)
    print('统计:', dict(summary))
    print('导出:', OUT)


if __name__ == '__main__':
    main()
