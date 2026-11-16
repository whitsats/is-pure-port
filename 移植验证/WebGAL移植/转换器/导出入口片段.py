"""导出已知边界内的第零入口线性片段；不表示代码可达性或完整剧本。"""
from pathlib import Path
import argparse
import json
import struct

from mac_reader import ROOT, load_table, read_entry_zero
from 检查无画面边界 import inspect as inspect_ff_boundary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--candidate-boundaries', type=Path,
                        help='附加 FF 标记候选，导出前重新核验')
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    checks = json.loads((ROOT / 'MAC_命令表/脚本验证.json').read_text(encoding='utf-8'))
    extra = json.loads(args.candidate_boundaries.read_text(encoding='utf-8')) if args.candidate_boundaries else {}
    table = load_table()
    scripts, skipped = [], []
    for name, check in sorted(checks.items()):
        candidate = extra.get(name, {})
        if 'boundary' not in check and candidate.get('status') != 'candidate':
            skipped.append({'file': name, 'reason': '无候选边界'})
            continue
        try:
            data = (ROOT / '输出-保护边修复/MAC' / name).read_bytes()
            if 'boundary' in check:
                boundary, boundary_source = check['boundary'], 'graph_disp 目标候选'
            else:
                renewed = inspect_ff_boundary(data, check['text_start'], table)
                if renewed['candidate_end'] != candidate['candidate_end'] or renewed['entry'] != candidate['entry']:
                    raise ValueError('FF 候选边界与复核不一致')
                boundary, boundary_source = renewed['candidate_end'], '连续 FF 标记候选'
            entry, commands = read_entry_zero(data, boundary, table)
        except (ValueError, OSError, struct.error) as exc:
            skipped.append({'file': name, 'reason': str(exc)})
            continue
        scripts.append({'file': name, 'entry_0': entry, 'candidate_boundary': boundary,
                        'boundary_source': boundary_source,
                        'scope': '第零入口至候选边界的线性片段；非可达性证明',
                        'commands': [{'offset': c.offset, 'opcode': c.opcode, 'name': c.name,
                                      'raw_hex': c.data.hex()} for c in commands]})
    result = {'scripts': scripts, 'skipped': skipped}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
        f.write('\n')
    print('片段:', len(scripts), '未导出:', len(skipped), '命令:', sum(len(s['commands']) for s in scripts))
    for item in skipped:
        print(item['file'], item['reason'])
    print('输出:', args.output)


if __name__ == '__main__':
    main()
