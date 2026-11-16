"""Decode dialogue directly from the selected v7.4 disc-build archive."""
import argparse
from collections import Counter, defaultdict
import csv
import hashlib
import json
import re
import struct
from pathlib import Path

from mac_release import DISC_MAC, ENGINEERING_DIALOGUE, ROOT
import MAC_解析 as mac
from 核查字码表缺口 import decode_slot, load_tables

DATA = Path(__file__).resolve().parents[1] / '数据'
ARCHIVE = DISC_MAC
CONTROL_SUFFIX = re.compile(rb'(?:%[KkPpNn])+$')


def decode_dialogue(original, patched, offset, expected, codes):
    command = original[offset:offset + 12]
    pointer, line, voice = struct.unpack_from('<IHH', command, 4)
    end = original.index(b'\0', pointer)
    source, slot = original[pointer:end], patched[pointer:end]
    text, unknown = '', []
    if command != expected or command != patched[offset:offset + 12] or patched[end:end + 1] != b'\0':
        status = '指令或文本边界变化'
    elif source == slot:
        status = '原字节不变'
    else:
        match = CONTROL_SUFFIX.search(source)
        suffix = match.group() if match else b''
        if suffix and not slot.endswith(suffix):
            status = '控制码尾部变化'
        else:
            body = slot[:-len(suffix)] if suffix else slot
            glyphs = decode_slot(body, codes)
            unknown = sorted({code for char, code, _ in glyphs if char is None})
            candidate = ''.join(char or '' for char, _, _ in glyphs)
            used = sum(width for _, _, width in glyphs)
            if unknown:
                status = '未知或不唯一字码'
            elif (any(byte != 0xFF for byte in body[used:]) or not candidate
                  or any(char in ';:|\\%' or ord(char) < 32 for char in candidate)):
                status = '需核对控制码或特殊字符'
            else:
                status, text = '唯一匹配', candidate
    return [f'0x{pointer:06X}', line, -1 if voice == 0xFFFF else voice,
            source.decode('cp932'), text, status], unknown


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--from-script', type=int, default=0)
    parser.add_argument('--engineering-fallback', action='store_true', help='标注并保留盘内暂不能安全解码的已核对工程译文')
    args = parser.parse_args()
    if args.output.exists() or args.report.exists() or args.output == args.report:
        parser.error('输出路径已存在或重复')

    archive = ARCHIVE.read_bytes()
    entries = mac.entries(archive)
    originals = mac.entries(mac.load())
    candidates = defaultdict(set)
    for char, codes in load_tables()[0].items():
        for code in codes:
            candidates[int(code, 16)].add(char)
    reverse = {code: next(iter(chars)) for code, chars in candidates.items() if len(chars) == 1}
    # See 验证/字码表缺口与0x1EC.md and the original/v7.4 title comparison.
    supplement = {0x8140: '　', 0x8145: '・', 0x9643: '—'}
    for code, char in supplement.items():
        if candidates[code] and candidates[code] != {char}:
            raise ValueError(f'补充字码与作者表冲突: {code:#06x}')
        reverse[code] = char
    engineering = {}
    if args.engineering_fallback:
        with ENGINEERING_DIALOGUE.open(encoding='utf-8-sig', newline='') as file:
            engineering = {(row['剧本'], int(row['指令偏移'], 16)): row
                           for row in csv.DictReader(file, delimiter='\t')}
    graph = json.loads((DATA / '全盘剧情候选图.json').read_text(encoding='utf-8'))
    cache, statuses, unknown_codes, rows, sources = {}, Counter(), Counter(), [], Counter()
    for node in graph['nodes']:
        script = node['script']
        index = int(script[4:7])
        if index < args.from_script or node['name'] != 'msg_disp2':
            continue
        if index not in cache:
            if entries[index]['name'].casefold() != originals[index]['name'].casefold():
                raise ValueError(f'归档条目与原盘不对应: {script}')
            cache[index] = ((ROOT / '输出-保护边修复/MAC' / script).read_bytes(), mac.script(archive, entries[index]))
        offset = node['offset']
        row, unknown = decode_dialogue(*cache[index], offset, bytes.fromhex(node['raw_hex']), reverse)
        status = row[-1]
        statuses[status] += 1
        unknown_codes.update(unknown)
        fallback = engineering.get((script, offset), {})
        text = fallback.get('v7.4中文', '')
        if status == '唯一匹配':
            provenance = 'v7.4 打盘归档'
        elif (status != '指令或文本边界变化' and fallback.get('匹配状态') == '工程与地址匹配'
              and fallback.get('日文原文') == row[3] and fallback.get('语音号') == str(row[2]) and text):
            row[-2:] = [text, '唯一匹配']
            provenance = 'v7.4 工程回退'
        else:
            provenance = ''
        sources[provenance or '待核'] += 1
        rows.append([script, f'0x{offset:06X}', *row, provenance, status])

    with args.output.open('x', encoding='utf-8-sig', newline='') as file:
        writer = csv.writer(file, delimiter='\t')
        writer.writerow(['剧本', '指令偏移', '文本偏移', '行号', '语音号', '日文原文',
                         '中文（原对照表）', '匹配状态', '译文来源', '归档核对状态'])
        writer.writerows(rows)
    report = {'archive': str(ARCHIVE), 'sha256': hashlib.sha256(archive).hexdigest(),
              'scope': f'主线候选图 MAC_{args.from_script:03} 起，逐条检查指令、指针、终止符、原盘控制码尾部及作者表唯一字码。',
              'status_counts': dict(statuses),
              'sources': dict(sources),
              'supplemental_codes': {f'0x{code:04X}': char for code, char in supplement.items()},
              'unknown_codes': {f'0x{code:04X}': count for code, count in unknown_codes.most_common()}}
    with args.report.open('x', encoding='utf-8') as file:
        json.dump(report, file, ensure_ascii=False, indent=2)
        file.write('\n')
    print(report['status_counts'])


if __name__ == '__main__':
    main()
