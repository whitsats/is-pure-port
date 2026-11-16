"""Fill untranslated option-table rows from the existing patched MAC archive."""
import argparse
from collections import Counter, defaultdict
import csv
import hashlib
import json
from pathlib import Path

from 校验实际汉化盘 import PATCHED, ROOT, mac
from 核查字码表缺口 import decode_slot, load_tables

DATA = Path(__file__).resolve().parents[1] / '数据'


def fill(source, archive, reviewed):
    table, _ = load_tables()
    by_code = defaultdict(set)
    for character, codes in table.items():
        for code in codes:
            by_code[int(code, 16)].add(character)
    reverse = {code: next(iter(chars)) for code, chars in by_code.items() if len(chars) == 1}
    original_archive = mac.load()
    before_entries = mac.entries(original_archive)
    patched_entries = mac.entries(archive)
    with source.open(encoding='utf-8-sig', newline='') as file:
        reader = csv.DictReader(file, delimiter='\t')
        rows = list(reader)
    columns = [*reader.fieldnames, '编译译文来源']
    cache, detail = {}, []
    pending_review = dict(reviewed)
    for row in rows:
        engineering = row['汉化包中文'] if row['匹配状态'] == '唯一匹配' else ''
        row['编译译文来源'] = ''
        script = row['脚本']
        number = int(script[4:7])
        if number not in cache:
            source_entry, target_entry = before_entries[number], patched_entries[number]
            if source_entry['name'].casefold() != target_entry['name'].casefold():
                raise ValueError(f'归档条目不对应: {script}')
            original = (ROOT / '输出-保护边修复/MAC' / script).read_bytes()
            cache[number] = original, mac.script(archive, target_entry)
        original, patched = cache[number]
        ip, position, index = int(row['选项指令偏移'], 16), int(row['文本偏移'], 16), int(row['表内序号'])
        base = int.from_bytes(original[ip + 4:ip + 8], 'little') + index * 12
        japanese = row['日文原文'].encode('cp932')
        limit = position + len(japanese)
        slot = patched[position:limit]
        text = ''
        if (original[ip:ip + 12] != patched[ip:ip + 12]
                or original[base:base + 12] != patched[base:base + 12]
                or int.from_bytes(original[base:base + 4], 'little') != position
                or original[position:limit + 1] != japanese + b'\0'
                or len(slot) != len(japanese) or patched[limit:limit + 1] != b'\0'):
            status = '选项表或原文槽位不对应'
        elif slot == japanese:
            status = '归档原文未变化'
            key = f'{Path(script).stem}:0x{ip:X}:{index}'
            if key in pending_review:
                original_text, text = pending_review.pop(key)
                if original_text != row['日文原文'] or not text:
                    raise ValueError(f'补译原文不对应: {key}')
                status = 'WebGAL 补译'
                row.update({'汉化包中文': text, '匹配状态': '唯一匹配', '编译译文来源': status})
        else:
            decoded = decode_slot(slot, reverse)
            consumed = sum(item[2] for item in decoded)
            text = ''.join(item[0] or '' for item in decoded)
            if (any(item[0] is None for item in decoded) or any(byte != 0xFF for byte in slot[consumed:])
                    or not text or any(c in text for c in ';:|\\\r\n') or '->' in text):
                status = '字码不唯一或不适合直接写入'
            else:
                status = '从汉化归档解码'
                row.update({'汉化包中文': text, '匹配状态': '唯一匹配', '编译译文来源': 'v7.4 打盘归档'})
        if not row['编译译文来源'] and engineering:
            text = engineering
            row['编译译文来源'] = 'v7.4 工程回退'
        detail.append({'script': script, 'offset': row['选项指令偏移'], 'index': index,
                       'status': status, 'source': row['编译译文来源'], 'original': row['日文原文'],
                       **({'translation': text} if text and row['编译译文来源'] else {})})
    if pending_review:
        raise ValueError(f'补译没有对应的未翻译槽位: {sorted(pending_review)}')
    return columns, rows, {
        'scope': '核对原盘与汉化归档的指令、选项表项和字符串槽位。优先采用盘内译文，单独标注工程回退及 WebGAL 补译。',
        'archive': str(PATCHED), 'sha256': hashlib.sha256(archive).hexdigest(),
        'counts': dict(Counter(row['status'] for row in detail)), 'details': detail,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--report', required=True, type=Path)
    parser.add_argument('--reviewed', type=Path, help='按剧本、指令偏移及表内序号核对的 WebGAL 补译')
    args = parser.parse_args()
    if args.output.exists() or args.report.exists() or args.output == args.report:
        parser.error('输出路径已存在或重复')
    reviewed = json.loads(args.reviewed.read_text(encoding='utf-8-sig')) if args.reviewed else {}
    columns, rows, report = fill(DATA / '选项v74地址核查.tsv', PATCHED.read_bytes(), reviewed)
    with args.output.open('x', encoding='utf-8-sig', newline='') as file:
        writer = csv.DictWriter(file, fieldnames=columns, delimiter='\t')
        writer.writeheader()
        writer.writerows(rows)
    with args.report.open('x', encoding='utf-8') as file:
        json.dump(report, file, ensure_ascii=False, indent=2)
        file.write('\n')
    print(report['counts'])


if __name__ == '__main__':
    main()
