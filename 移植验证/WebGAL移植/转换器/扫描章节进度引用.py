"""扫描已解析候选片段里的 0x17 和相关状态引用，不推断可达性。"""
import argparse
import collections
import json
from pathlib import Path

from mac_state import State, UnsupportedCommand, parse_if, parse_reg_calc

DATA = Path(__file__).resolve().parents[1] / '数据'
WINDOWS = ((0x440, 0x442, '章节索引'), (0x4B0, 0x4B4, '该章节旧进度'))


def context_overlap(raw):
    state = State()
    operand = state.describe(raw)
    if operand['kind'] == 'value':
        return None
    start = operand['offset']
    end = start + (2 if operand['kind'] == 'word' else 1)
    overlap = [name for low, high, name in WINDOWS if start < high and end > low]
    return {'operand': operand, 'overlap': overlap} if overlap else None


def scan(ir, titles):
    writes, refs, unknown, total_if = [], [], [], 0
    grouped = collections.defaultdict(list)
    for script in ir['scripts']:
        commands = script['commands']
        for i, cmd in enumerate(commands):
            raw = bytes.fromhex(cmd['raw_hex'])
            if raw[:2] == b'\x09\x17' and len(raw) == 8:
                index = int.from_bytes(raw[2:4], 'little')
                following = [{'offset': c['offset'], 'name': c['name'], 'raw_hex': c['raw_hex']}
                             for c in commands[i + 1:i + 9] if c['name'] in ('if', 'title_disp', 'ext_goto')]
                item = {'script': script['file'], 'offset': cmd['offset'], 'index': index,
                        'raw_hex': cmd['raw_hex'], 'nearby_commands': following}
                writes.append(item)
                grouped[index].append(item)
                continue
            operands = []
            try:
                if cmd['opcode'] == 0x02:
                    total_if += 1
                    target, left, right, code = parse_if(raw)
                    operands = [('if_left', left), ('if_right', right)]
                elif cmd['opcode'] == 0x09:
                    op, left, right = parse_reg_calc(raw)
                    # 赋值/立即数等不一定读取目的；这里记录“出现过”，不推断数据流。
                    operands = [('calc_left', left)]
                    if op != 0x0E:
                        operands.append(('calc_right', right))
            except UnsupportedCommand as exc:
                unknown.append({'script': script['file'], 'offset': cmd['offset'],
                                'name': cmd['name'], 'raw_hex': cmd['raw_hex'], 'reason': str(exc)})
            for role, operand in operands:
                overlap = context_overlap(operand)
                if overlap:
                    refs.append({'script': script['file'], 'offset': cmd['offset'], 'name': cmd['name'],
                                 'role': role, 'raw_hex': cmd['raw_hex'], **overlap})
    return {'scope': '仅扫描 73 个候选线性片段，不证明指令可达或覆盖全部剧本；MAC_068 未包含。',
            'limitations': ['直接检查 if/reg_calc 的已解码操作数，未追踪间接读写、别名传播、选项表和原生代码。',
                            '相邻指令只是静态距离，不证明控制流连续；标题是同索引关联，不证明所有业务含义。'],
            'scripts': len(ir['scripts']), 'skipped': ir.get('skipped', []),
            'counts': {'reg17': len(writes), 'distinct_indices': len(grouped), 'if': total_if,
                       'context_operand_mentions': len(refs), 'unsupported_if_or_calc': len(unknown)},
            'indices': [{'index': i, 'title': t['title'], 'first_text': t['first_text'],
                         'write_sites': grouped.get(i, [])} for i, t in enumerate(titles)],
            'out_of_range_writes': [w for w in writes if w['index'] >= len(titles)],
            'context_operand_mentions': refs, 'unsupported_if_or_calc': unknown}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    ir = json.loads((DATA / '入口片段_扩展候选.json').read_text(encoding='utf-8'))
    titles = json.loads((DATA / '章节标题静态表.json').read_text(encoding='utf-8'))['records']
    report = scan(ir, titles)
    with args.output.open('x', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
        f.write('\n')
    print('扫描统计:', report['counts'])
    print('输出:', args.output)


if __name__ == '__main__':
    main()
