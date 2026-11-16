"""根据原程序的资源编号拆分方式导出 graph_disp 画面文件候选。"""
import csv
import json
import struct
from collections import Counter
from pathlib import Path

from mac_reader import ROOT

BASE = Path(__file__).resolve().parents[1]
SOURCE = BASE / '数据/入口片段.json'
OUT = BASE / '数据/画面资源候选.tsv'
GROUPS = {1: 'BG', 2: 'EV', 3: 'CHR'}


def candidate(raw):
    group, index = raw >> 12, raw & 0x0FFF
    if group not in GROUPS:
        return group, index, None, '资源组未确认'
    if index == 0xFFF:
        return group, index, None, '特殊编号0xFFF'
    name = GROUPS[group]
    return group, index, f'{name}/{name}_{2 * index:04}.png', '待画面对照'


def main():
    if OUT.exists():
        raise FileExistsError(OUT)
    scripts = json.loads(SOURCE.read_text(encoding='utf-8'))['scripts']
    rows, stats = [], Counter()
    for script in scripts:
        name = script['file']
        data = (ROOT / '输出-保护边修复/MAC' / name).read_bytes()
        for cmd in script['commands']:
            if cmd['opcode'] != 0x33:
                continue
            raw = bytes.fromhex(cmd['raw_hex'])
            count, address = raw[1], struct.unpack_from('<I', raw, 4)[0]
            if address + count * 12 > len(data):
                raise ValueError(f'画面记录越界: {name} {cmd["offset"]:#x}')
            for index in range(count):
                offset = address + index * 12
                record = data[offset:offset + 12]
                resource = struct.unpack_from('<H', record, 4)[0]
                group, number, relative, note = candidate(resource)
                exists = bool(relative and (ROOT / '输出-保护边修复' / relative).is_file())
                stats[(group, '存在' if exists else note)] += 1
                rows.append([name, f"0x{cmd['offset']:06X}", index, f'0x{offset:06X}', record.hex(' '),
                             f'0x{resource:04X}', group, number, relative or '', '是' if exists else '否', note])
    with OUT.open('x', encoding='utf-8-sig', newline='') as f:
        w = csv.writer(f, delimiter='\t')
        w.writerow(['剧本', '命令偏移', '记录序号', '记录偏移', '记录原始字节', '资源编号', '资源组', '组内编号',
                    '候选图片（相对输出-保护边修复）', '文件存在', '状态'])
        w.writerows(rows)
    print('记录:', len(rows), '统计:', dict(stats), '输出:', OUT)


if __name__ == '__main__':
    main()
