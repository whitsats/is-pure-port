"""用原日文工程文件校验原盘文本，再按相同地址关联 v7.4 译文。"""
import csv
import argparse
import json
import re
import struct
from pathlib import Path

from mac_reader import ROOT
from 匹配汉化包选项 import read_patch
import MAC_解析 as mac
from 本地路径 import V74_RELEASE, ZH_ROOT

BASE = Path(__file__).resolve().parents[1]
ORIGINAL = ZH_ROOT / '素材/汉化原始工程/日文原始文本'
PATCH = V74_RELEASE / '补丁'
OUTPUT = BASE / '数据/台词v74原始工程核查.tsv'


def index(root):
    result = {}
    for path in root.rglob('*.BIP.bin.txt'):
        name = path.name[:-len('.bin.txt')].lower()
        if name in result:
            raise ValueError(f'文件名重复: {name}')
        result[name] = path
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--patch', type=Path, default=PATCH)
    parser.add_argument('--output', type=Path, default=OUTPUT)
    parser.add_argument('--column', default='v7.4中文')
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    old_files, patches = index(ORIGINAL), index(args.patch)
    names = {f"MAC_{e['i']:03}.bin": e['name'].lower() for e in mac.entries(mac.load())}
    scripts = json.loads((BASE / '数据/入口片段.json').read_text(encoding='utf-8'))['scripts']
    rows = []
    for script in scripts:
        name = script['file']
        logical = names[name]
        if logical not in old_files or logical not in patches:
            continue
        original_records = read_patch(old_files[logical])
        patch_records = read_patch(patches[logical])
        data = (ROOT / '输出-保护边修复/MAC' / name).read_bytes()
        for command in script['commands']:
            if command['opcode'] != 0x60:
                continue
            pointer, line, voice = struct.unpack_from('<IHH', bytes.fromhex(command['raw_hex']), 4)
            if not 0 < pointer < len(data):
                raise ValueError(f'文本指针越界: {name}:{pointer:x}')
            end = data.find(b'\0', pointer)
            if end < 0:
                raise ValueError(f'文本无终止符: {name}:{pointer:x}')
            raw = data[pointer:end].decode('cp932')
            normalized = re.sub(r'(?:%[KkPpNn])+$', '', raw)
            references = [item for item in original_records.get(pointer, []) if item[0] == normalized]
            translated = patch_records.get(pointer, [])
            if len(references) != 1:
                status, chinese = '日文工程与原盘不唯一匹配', ''
            elif len(translated) != 1:
                status, chinese = '译文地址不唯一', ''
            elif not translated[0][1]:
                status, chinese = '译文为空', ''
            else:
                status, chinese = '工程与地址匹配', translated[0][1]
            rows.append([name, f"0x{command['offset']:06X}", f'0x{pointer:06X}', line,
                         -1 if voice == 0xFFFF else voice, raw, chinese, status])
    with args.output.open('x', encoding='utf-8-sig', newline='') as f:
        writer = csv.writer(f, delimiter='\t')
        writer.writerow(['剧本', '指令偏移', '文本偏移', '行号', '语音号', '日文原文', args.column, '匹配状态'])
        writer.writerows(rows)
    print('总数:', len(rows), '工程和地址匹配:', sum(r[-1] == '工程与地址匹配' for r in rows),
          '输出:', args.output)


if __name__ == '__main__':
    main()
