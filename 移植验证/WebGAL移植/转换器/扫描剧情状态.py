"""Index directly decoded state references for subsequent branch verification."""
import argparse
from collections import defaultdict
import json
from pathlib import Path

from mac_state import State, UnsupportedCommand, parse_if, parse_reg_calc

DATA = Path(__file__).resolve().parents[1] / '数据'


def scan(ir, choice_report):
    state = State()
    choices = {(item['script'], item['offset']): item for item in choice_report['plans']}
    references = defaultdict(list)
    operands_at_byte = defaultdict(set)
    pending = []
    for script in ir['scripts']:
        for command in script['commands']:
            raw = bytes.fromhex(command['raw_hex'])
            opcode = command['opcode']
            site = {'script': script['file'], 'offset': command['offset'], 'raw_hex': raw.hex()}
            target = None
            try:
                if opcode == 2:
                    target, left, right, _ = parse_if(raw)
                    accesses = [('compare', left), ('compare', right)]
                elif opcode == 9 and raw[1] != 0x17:
                    operation, destination, source = parse_reg_calc(raw)
                    accesses = [('write', destination)]
                    if operation not in (0, 0x0E):
                        accesses.append(('read', destination))
                    if operation != 0x0E:
                        accesses.append(('read', source))
                elif opcode == 0x72:
                    plan = choices.get((site['script'], site['offset']))
                    if plan is None:
                        raise UnsupportedCommand('未解析选项条件表')
                    accesses = [('choice_result', int.from_bytes(raw[2:4], 'little'))]
                    accesses += [('choice_visibility', int(o['condition']['raw'], 16)) for o in plan['options']]
                else:
                    continue
            except UnsupportedCommand as error:
                pending.append({**site, 'reason': str(error)})
                continue
            for role, operand in dict.fromkeys(accesses):
                description = state.describe(operand)
                kind = description['kind']
                if kind == 'value':
                    continue
                name = description['raw']
                references[name].append({**site, 'role': role, **({'target': target} if target is not None else {})})
                start = description['offset']
                for address in range(start, start + (2 if kind == 'word' else 1)):
                    operands_at_byte[address].add((kind, name))
    aliases = {f'0x{address:X}': sorted(name for _, name in entries)
               for address, entries in sorted(operands_at_byte.items())
               if len({kind for kind, _ in entries}) > 1}
    return {'scope': '候选剧本中的直接 if、reg_calc 和已解析选项表。未跟踪间接或原生读写、章节位表及可达性。',
            'script_count': len(ir['scripts']), 'script_gaps': ir['skipped'],
            'references': dict(sorted(references.items())), 'word_bit_aliases': aliases, 'pending': pending}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    ir = json.loads((DATA / '入口片段_扩展候选.json').read_text(encoding='utf-8'))
    choices = json.loads((DATA / '批量选项规划_零状态试验.json').read_text(encoding='utf-8'))
    report = scan(ir, choices)
    with args.output.open('x', encoding='utf-8') as out:
        json.dump(report, out, ensure_ascii=False, separators=(',', ':'))
        out.write('\n')
    print(f"状态操作数 {len(report['references'])}，已识别字位重叠 {len(report['word_bit_aliases'])}，待核查 {len(report['pending'])}")


if __name__ == '__main__':
    main()
