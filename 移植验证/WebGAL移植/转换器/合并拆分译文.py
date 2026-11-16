"""按原盘字节与 v7.4 片段地址严格合并拆分文本。"""
import argparse
import bisect
import csv
import json
from pathlib import Path

from mac_reader import ROOT
from mac_release import PATCH_TEXT
import MAC_解析 as mac
from 匹配汉化包选项 import read_patch

BASE = Path(__file__).resolve().parents[1]
PATCH = PATCH_TEXT
DEFAULT_SOURCE = BASE / '数据/台词v74原始工程核查_拆分修复.tsv'


def merge_fragments(data, start, original_text, fragments, addresses):
    """要求原盘原文、每段原文字节及地址均一致，空隙仅允许日文中点。"""
    if start < 0 or start >= len(data):
        return None
    end = data.find(b'\0', start)
    if end < 0:
        return None
    raw = data[start:end]
    try:
        if raw.decode('cp932') != original_text:
            return None
    except UnicodeError:
        return None
    left, right = bisect.bisect_left(addresses, start), bisect.bisect_left(addresses, end)
    keys = addresses[left:right]
    if len(keys) < 2 or keys[0] != start:
        return None
    cursor, chunks = start, []
    for address in keys:
        pairs = fragments[address]
        if len(pairs) != 1:
            return None
        japanese, chinese = pairs[0]
        if not japanese or not chinese:
            return None
        try:
            encoded = japanese.encode('cp932')
        except UnicodeError:
            return None
        gap = data[cursor:address]
        if address < cursor or gap != b'\x81\x45' * (len(gap) // 2):
            return None
        if data[address:address + len(encoded)] != encoded or address + len(encoded) > end:
            return None
        chunks.append({'address': f'0x{address:06X}', 'japanese': japanese, 'chinese': chinese})
        cursor = address + len(encoded)
    # 汉化工程中的文本片段不包含消息结束控制码。
    if data[cursor:end] != b'%K%P':
        return None
    return {'chinese': ''.join(c['chinese'] for c in chunks), 'fragments': chunks}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, default=DEFAULT_SOURCE)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--approve', action='append', default=[], metavar='SCRIPT:OFFSET',
                        help='只接入逐条核查过的候选，可重复指定；其他候选仅报告')
    args = parser.parse_args()
    if args.output.exists() or args.report.exists():
        raise FileExistsError('输出或报告已存在')
    paths = {}
    for path in PATCH.rglob('*.BIP.bin.txt'):
        key = path.name[:-len('.bin.txt')].lower()
        if key in paths:
            raise ValueError(f'译文文件名重复: {key}')
        paths[key] = path
    names = {f"MAC_{e['i']:03}.bin": e['name'].lower() for e in mac.entries(mac.load())}
    with args.source.open(encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f, delimiter='\t')
        columns, rows = reader.fieldnames, list(reader)
    approved = set(args.approve)
    cache, candidates = {}, []
    for row in rows:
        if row['v7.4中文'] or row['匹配状态'] == '工程与地址匹配':
            continue
        filename = row['剧本']
        name = names.get(filename)
        if not name or name not in paths:
            continue
        if filename not in cache:
            fragments = read_patch(paths[name])
            cache[filename] = ((ROOT / '输出-保护边修复/MAC' / filename).read_bytes(),
                               fragments, sorted(fragments))
        data, fragments, addresses = cache[filename]
        result = merge_fragments(data, int(row['文本偏移'], 16), row['日文原文'], fragments, addresses)
        if result is None:
            continue
        key = f"{filename}:{row['指令偏移']}"
        accepted = key in approved
        if accepted:
            row['v7.4中文'] = result['chinese']
            row['匹配状态'] = '工程与地址匹配'
        candidates.append({'script': filename, 'instruction_offset': row['指令偏移'],
                           'text_offset': row['文本偏移'], 'approved': accepted, **result})
    unused = approved - {f"{c['script']}:{c['instruction_offset']}" for c in candidates}
    if unused:
        raise ValueError(f'指定的核查项不是严格匹配候选: {sorted(unused)}')
    with args.output.open('x', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=columns, delimiter='\t')
        writer.writeheader()
        writer.writerows(rows)
    with args.report.open('x', encoding='utf-8') as f:
        json.dump({'scope': '仅定位原盘字节与地址均一致的 v7.4 多片段；中文需逐条核查后接入。',
                   'source': str(args.source), 'candidate_count': len(candidates),
                   'approved_count': sum(c['approved'] for c in candidates), 'candidates': candidates},
                  f, ensure_ascii=False, indent=2)
        f.write('\n')
    print('严格匹配候选:', len(candidates), '条；核查后接入:', sum(c['approved'] for c in candidates),
          '条；输出:', args.output, '报告:', args.report)


if __name__ == '__main__':
    main()
