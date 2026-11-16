"""核查“候选译文包含作者码表没有的字”时，汉化盘里到底写了什么字码。

背景：`数据/三版译文与汉化盘核查.tsv` 里标成“字码缺失”的行，并不是磁盘上没有文本，
而是候选译文里有字不在作者的 `输出码表.txt`（3126 字）中，导致 `校验实际汉化盘.py`
无法把它编码成字节去比对。本脚本换一个方向：先用作者码表把磁盘槽位**反向解码**，
再把解码出的字符序列与候选译文逐字符对齐；只要两边长度一致，未知字码就唯一对应到候选里的某个字。
把所有行的这种对应关系统计起来，就能看出某个字码是否稳定对应同一个字、有多少条独立支撑。

输出（JSON）：
- `codes`：未知字码 → {字, 支撑行数, 冲突字, 例子}；只有同一字码在所有行都对应同一个字时才算“一致”。
- `rows`：逐行状态（逐字节一致 / 仅缺字码 / 不一致 / 对齐失败）。
- `notes`：这些对应**只是对齐推断**，字体层面（字模）没有核对，不能当作已证实的字码表。

用法：
  python -B 转换器/核查字码表缺口.py --output 数据/字码缺口核查.json
"""
import argparse
import csv
import hashlib
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

from mac_reader import ROOT
from mac_release import DISC_MAC
import MAC_解析 as mac

from 本地路径 import ZH_ROOT

sys.path.insert(0, str(ZH_ROOT / '打盘'))
import 烘焙文本 as bake

BASE = Path(__file__).resolve().parents[1]
ARCHIVE = DISC_MAC
SOURCE = BASE / '数据/台词v74原始工程核查.tsv'


def load_tables():
    table = bake.load_author_table(bake.AUTHOR_TABLE)
    reverse = {}
    for char, codes in table.items():
        for code in codes:
            reverse[int(code, 16)] = char
    return table, reverse


def decode_slot(slot, reverse):
    """槽位字节 → [(字符或 None, 字码或 ASCII 值, 字节数)]，遇到 0xFF 结束。

    作者码表里有的字码直接换成字；换不出字的保留 None，交给对齐统计。
    """
    items, index = [], 0
    while index < len(slot):
        byte = slot[index]
        if byte == 0xFF:
            break
        if byte < 0x80:
            items.append((chr(byte), byte, 1))
            index += 1
            continue
        if index + 1 >= len(slot):
            items.append((None, -1, 1))
            break
        code = (slot[index] << 8) | slot[index + 1]
        items.append((reverse.get(code), code, 2))
        index += 2
    return items


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--codes-output', type=Path,
                        help='另存一份可供 校验实际汉化盘.py --extra-codes 使用的补充字码')
    parser.add_argument('--min-support', type=int, default=3,
                        help='一个字母码至少要在多少行上无冲突对齐才写入补充字码')
    args = parser.parse_args()
    if args.output.exists() or (args.codes_output and args.codes_output.exists()):
        raise FileExistsError('输出已存在')

    table, reverse = load_tables()
    archive = ARCHIVE.read_bytes()
    entries = mac.entries(archive)
    with SOURCE.open(encoding='utf-8-sig', newline='') as f:
        rows = [r for r in csv.DictReader(f, delimiter='\t') if r['匹配状态'] == '工程与地址匹配']

    codes = defaultdict(lambda: {'chars': defaultdict(int), 'rows': []})
    status_rows = []
    for row in rows:
        script = row['剧本']
        data = bytes(mac.script(archive, entries[int(script[4:7])]))
        offset = int(row['文本偏移'], 16)
        japanese = re.sub(r'(?:%[KkPpNn])+$', '', row['日文原文'])
        frame = len(japanese.encode('cp932'))
        slot = data[offset:offset + frame]
        if len(slot) != frame:
            status_rows.append([script, row['指令偏移'], '槽位越界', ''])
            continue
        text = row['v7.4中文']
        items = decode_slot(slot, reverse)
        unknown = [i for i, (char, _, _) in enumerate(items) if char is None]
        # 把已知字码换成字，先看长度能否与候选对齐。
        if len(items) != len(text):
            status_rows.append([script, row['指令偏移'], '对齐失败（长度不同）',
                                f'盘上 {len(items)} 字 / 候选 {len(text)} 字'])
            continue
        for index in unknown:
            code = items[index][1]
            codes[code]['chars'][text[index]] += 1
            if len(codes[code]['rows']) < 8:
                codes[code]['rows'].append(f'{script}:{row["指令偏移"]}:{index}')

        # 用“作者码表 + 该行未知字码→候选字”重新编码，判断字节是否完全一致。
        mapping = {items[index][1]: text[index] for index in unknown}
        encoded, missing = encode_with(text, table, mapping)
        if missing:
            status_rows.append([script, row['指令偏移'], '缺译文字码',
                                ''.join(sorted(set(missing)))])
        elif encoded == bytes(slot):
            status_rows.append([script, row['指令偏移'],
                                '逐字节一致（作者码表）' if not unknown else '逐字节一致（含对齐推断字码）',
                                ','.join(f'{code:04X}={text[i]}' for i, code in
                                         ((i, items[i][1]) for i in unknown))])
        else:
            status_rows.append([script, row['指令偏移'], '不一致', ''])

    payload = {
        'archive': str(ARCHIVE),
        'archive_sha256': hashlib.sha256(archive).hexdigest(),
        'author_table': str(bake.AUTHOR_TABLE),
        'author_table_chars': len(table),
        'source': str(SOURCE),
        'rows': len(rows),
        'codes': {f'0x{code:04X}': {'chars': dict(item['chars']),
                                    'rows': item['rows'],
                                    'consistent': len(item['chars']) == 1}
                  for code, item in sorted(codes.items())},
        'status': {name: sum(1 for r in status_rows if r[2].startswith(name))
                   for name in ('逐字节一致（作者码表）', '逐字节一致（含对齐推断字码）',
                                '不一致', '对齐失败', '缺译文字码', '槽位越界')},
        'examples': [r for r in status_rows if r[2] != '逐字节一致（作者码表）'][:40],
        'notes': [
            '这里的“对齐推断字码”只说明：磁盘槽位里那个字码，按字符位置对应到候选译文的这个字，'
            '且所有出现该字码的行都对应同一个字。字体的字模没有被核对，不能当作作者码表的一部分。',
            '要把它变成已证实的字码，需要对照字库图集（例如同一字模在多位图中的形状），或由人工确认。',
            '本脚本只读，不修改任何归档或现有核查表。',
        ],
    }
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    if args.codes_output:
        usable = {code: {'char': next(iter(item['chars'])), 'support': sum(item['chars'].values())}
                  for code, item in payload['codes'].items()
                  if item['consistent'] and sum(item['chars'].values()) >= args.min_support}
        blocked = {code: item['chars'] for code, item in payload['codes'].items()
                   if not item['consistent'] or sum(item['chars'].values()) < args.min_support}
        args.codes_output.write_text(json.dumps({
            'source': str(args.output), 'min_support': args.min_support,
            'status': '对齐推断（字体字模未核对）',
            'codes': usable, 'excluded': blocked,
            'note': '每项都要求：同一字码在所有行都对到同一个字，且行数 ≥ min_support。只能用于对盘核对，'
                    '不能拿去当作者码表新增字，也不能替代人工/字体确认。',
        }, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print('补充字码', {code: (v['char'], v['support']) for code, v in usable.items()},
              '排除', blocked)
    print('行数', len(rows), '状态', payload['status'])
    for code, item in payload['codes'].items():
        print(code, item['chars'], '一致' if item['consistent'] else '冲突', item['rows'][:3])


def encode_with(text, table, mapping):
    """按作者码表编码；mapping 是 {字码: 字}，用于这一行里作者码表缺的字。"""
    extra = {}
    for code, char in mapping.items():
        extra[char] = f'{code:04x}'
    out, missing = bytearray(), []
    for char in text:
        if ord(char) < 0x80:
            out.append(ord(char))
            continue
        candidates = table.get(char) or ([extra[char]] if char in extra else [])
        if not candidates:
            missing.append(char)
            continue
        code = int(candidates[0], 16)
        out.append(code >> 8)
        out.append(code & 0xFF)
    return bytes(out), missing


if __name__ == '__main__':
    main()
