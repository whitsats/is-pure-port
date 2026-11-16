"""用原作者字码表核对候选中文是否逐字写入当前汉化 MAC 归档。"""
import csv
import argparse
import hashlib
import json
import re
import struct
import sys
from collections import Counter
from pathlib import Path

from mac_reader import ROOT
from mac_release import DISC_MAC
import MAC_解析 as mac
from 本地路径 import ZH_ROOT

sys.path.insert(0, str(ZH_ROOT / '打盘'))
import 烘焙文本 as bake

BASE = Path(__file__).resolve().parents[1]
PATCHED = DISC_MAC
OUT = BASE / '数据/译文与实际汉化盘核查.tsv'
META = BASE / '数据/译文与实际汉化盘来源.json'


def matches(text, data, table, extra=None):
    """逐字节比对；extra 是对齐推断出的补充字码（字 → 码列表），来自 --extra-codes。"""
    if not text:
        return '无译文'
    extra = extra or {}
    pos = 0
    for ch in text:
        if ord(ch) < 128:
            codes = [bytes([ord(ch)])]
        else:
            raw_codes = table.get(ch) or extra.get(ch, [])
            if not raw_codes:
                return '字码缺失'
            codes = [bytes.fromhex(code) for code in raw_codes]
        if not any(data[pos:pos + len(code)] == code for code in codes):
            return '不一致'
        pos += len(codes[0])
    return '逐字节一致' if all(byte == 0xFF for byte in data[pos:]) else '不一致'


def read_tsv(name):
    with (BASE / '数据' / name).open(encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f, delimiter='\t'))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=OUT)
    parser.add_argument('--meta', type=Path, default=META)
    parser.add_argument('--old-mapping', type=Path)
    parser.add_argument('--extra-codes', type=Path,
                        help='对齐推断的补充字码 JSON（转换器/核查字码表缺口.py --codes-output 生成）')
    args = parser.parse_args()
    if args.output.exists() or args.meta.exists():
        raise FileExistsError('输出已存在')
    table = bake.load_author_table(bake.AUTHOR_TABLE)
    if not table:
        raise ValueError('原作者字码表不存在或为空')
    extra = {}
    if args.extra_codes:
        payload = json.loads(args.extra_codes.read_text(encoding='utf-8'))
        for code, item in payload['codes'].items():
            extra.setdefault(item['char'], []).append(code[2:].lower())
        print('补充字码:', {ch: codes for ch, codes in extra.items()}, '来自', args.extra_codes)
    source = read_tsv('台词v74原始工程核查.tsv')
    prior = read_tsv('台词对应核查.tsv')
    previous = {(x['剧本'], x['指令偏移']): x['中文（原对照表）'] for x in prior}
    if len(previous) != len(prior):
        raise ValueError('汇总文本的命令偏移重复')
    older = {}
    if args.old_mapping:
        with args.old_mapping.open(encoding='utf-8-sig', newline='') as f:
            old_rows = list(csv.DictReader(f, delimiter='\t'))
        older = {(r['剧本'], r['指令偏移']): r for r in old_rows}
        if len(older) != len(old_rows):
            raise ValueError('旧工程文本的命令偏移重复')
    archive = PATCHED.read_bytes()
    entries = mac.entries(archive)
    cache, rows, stats = {}, [], Counter()
    for row in source:
        if row['匹配状态'] != '工程与地址匹配':
            continue
        script = row['剧本']
        idx = int(script[4:7])
        if idx not in cache:
            cache[idx] = mac.script(archive, entries[idx])
        data = cache[idx]
        offset = int(row['文本偏移'], 16)
        japanese = re.sub(r'(?:%[KkPpNn])+$', '', row['日文原文'])
        frame_len = len(japanese.encode('cp932'))
        if offset + frame_len > len(data):
            raise ValueError(f'汉化盘槽位越界: {script}:{offset:#x}')
        frame = data[offset:offset + frame_len]
        v74 = row['v7.4中文']
        summary = previous.get((script, row['指令偏移']), '')
        v74_result = matches(v74, frame, table, extra)
        summary_result = matches(summary, frame, table, extra)
        old_row = older.get((script, row['指令偏移']), {})
        old_text = old_row.get('v7中文', '') if old_row.get('匹配状态') == '工程与地址匹配' else ''
        old_result = matches(old_text, frame, table, extra)
        stats[(v74_result, summary_result, old_result)] += 1
        rows.append([script, row['指令偏移'], row['文本偏移'], row['行号'], row['语音号'],
                     v74_result, summary_result, old_result, v74, summary, old_text])
    with args.output.open('x', encoding='utf-8-sig', newline='') as f:
        w = csv.writer(f, delimiter='\t')
        w.writerow(['剧本', '指令偏移', '文本偏移', '行号', '语音号', 'v7.4工程文本对盘', '汇总文本对盘', 'v7工程文本对盘', 'v7.4工程中文', '汇总中文', 'v7工程中文'])
        w.writerows(rows)
    with args.meta.open('x', encoding='utf-8') as f:
        json.dump({'archive': str(PATCHED), 'archive_sha256': hashlib.sha256(archive).hexdigest(),
                   'author_table': str(bake.AUTHOR_TABLE),
                   'extra_codes': str(args.extra_codes) if args.extra_codes else None,
                   'scope': '只比较可关联地址的固定文本槽，不保证整盘或译文语义；未匹配项不推测'}, f,
                  ensure_ascii=False, indent=2)
        f.write('\n')
    print('核对:', len(rows), '组合统计:', dict(stats))
    print('输出:', args.output)


if __name__ == '__main__':
    main()
