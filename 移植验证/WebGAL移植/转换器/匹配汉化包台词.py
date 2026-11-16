"""按 MAC 文本指针和日文原文匹配 v7 汉化包；不使用模糊对齐。"""
import csv
import argparse
import json
import re
import struct
from pathlib import Path

from mac_reader import ROOT
from 匹配汉化包选项 import PATCH, read_patch
import MAC_解析 as mac

BASE = Path(__file__).resolve().parents[1]
OUTPUT = BASE / '数据/台词中文地址核查_去尾控制符.tsv'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--patch', type=Path, default=PATCH)
    parser.add_argument('--output', type=Path, default=OUTPUT)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    patches = {}
    for path in args.patch.rglob('*.BIP.bin.txt'):
        key = path.name[:-len('.bin.txt')].lower()
        if key in patches:
            raise ValueError(f'重复汉化文件: {key}')
        patches[key] = path
    names = {f"MAC_{e['i']:03}.bin": e['name'].lower() for e in mac.entries(mac.load())}
    scripts = json.loads((BASE / '数据/入口片段.json').read_text(encoding='utf-8'))['scripts']
    rows = []
    for script in scripts:
        name = script['file']
        patch = patches.get(names[name])
        if not patch:
            continue
        lookup = read_patch(patch)
        data = (ROOT / '输出-保护边修复/MAC' / name).read_bytes()
        for c in script['commands']:
            if c['opcode'] != 0x60:
                continue
            pointer, line, voice = struct.unpack_from('<IHH', bytes.fromhex(c['raw_hex']), 4)
            if not 0 < pointer < len(data):
                raise ValueError(f'无效文本指针: {name}:{pointer:x}')
            end = data.find(b'\0', pointer)
            if end < 0:
                raise ValueError(f'文本缺少结束符: {name}:{pointer:x}')
            original = data[pointer:end].decode('cp932')
            normalized = re.sub(r'(?:%[KkPpNn])+$', '', original)
            matches = [translation for text, translation in lookup.get(pointer, []) if text == normalized]
            status = '唯一匹配' if len(matches) == 1 else '无匹配' if not matches else '重复匹配'
            rows.append([name, f"0x{c['offset']:06X}", f'0x{pointer:06X}', line,
                         -1 if voice == 0xFFFF else voice, original,
                         matches[0] if len(matches) == 1 else '', status])
    with args.output.open('x', encoding='utf-8-sig', newline='') as f:
        w = csv.writer(f, delimiter='\t')
        w.writerow(['剧本', '指令偏移', '文本偏移', '行号', '语音号', '日文原文', '汉化包中文', '匹配状态'])
        w.writerows(rows)
    print('覆盖汉化包剧本:', len({r[0] for r in rows}), '台词:', len(rows),
          '地址及去尾控制符原文唯一匹配:', sum(r[-1] == '唯一匹配' for r in rows),
          '有中文:', sum(r[-1] == '唯一匹配' and bool(r[-2]) for r in rows))
    print('输出:', args.output)


if __name__ == '__main__':
    main()
