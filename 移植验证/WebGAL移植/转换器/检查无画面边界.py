"""对无 graph_disp 候选边界的脚本，报告入口后首次 8 字节 FF 标记前的片段。"""
import argparse
import json
import struct
from pathlib import Path

from mac_reader import ROOT, load_table, read_linear_range


def inspect(data, upper, table):
    if len(data) < 12 or data[:8] != bytes.fromhex('09 11 00 60 08 00 00 00'):
        raise ValueError('未知入口格式')
    start = struct.unpack_from('<I', data, 8)[0]
    if not 12 <= start < upper <= len(data):
        raise ValueError('入口或上界不合法')
    pos, count = start, 0
    while pos < upper:
        if data[pos:pos + 8] == b'\xff' * 8:
            commands = read_linear_range(data, start, pos, table)
            targets = []
            starts = {x.offset for x in commands}
            for c in commands:
                if c.opcode in (2, 3, 4):
                    target = struct.unpack_from('<I', c.data, 4)[0]
                    targets.append({'source': c.offset, 'target': target, 'in_fragment': target in starts})
            return {'entry': start, 'candidate_end': pos, 'count': count, 'targets': targets,
                    'last_opcodes': [x.name for x in commands[-4:]]}
        op = data[pos]
        if op >= len(table) or not table[op]['bytes'] or pos + table[op]['bytes'] > upper:
            raise ValueError(f'未到标记前遇到未知命令或数据: {pos:#x}/{op:#x}')
        pos += table[op]['bytes']
        count += 1
    raise ValueError('到达上界仍未发现 FF 标记')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    checks = json.loads((ROOT / 'MAC_命令表/脚本验证.json').read_text(encoding='utf-8'))
    table, output = load_table(), {}
    for name, info in checks.items():
        if info['status'] != 'no_33_boundary':
            continue
        data = (ROOT / '输出-保护边修复/MAC' / name).read_bytes()
        try:
            output[name] = {'status': 'candidate', **inspect(data, info['text_start'], table)}
        except (ValueError, struct.error) as exc:
            output[name] = {'status': 'unresolved', 'reason': str(exc)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
        f.write('\n')
    for name, item in output.items():
        print(name, item['status'], item.get('count', ''), item.get('reason', ''))


if __name__ == '__main__':
    main()
