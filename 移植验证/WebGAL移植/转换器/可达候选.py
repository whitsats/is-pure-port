"""保守遍历已知固定跳转，不执行状态，也不声称恢复动态跳转。"""
import argparse
from collections import Counter
import json
import struct
from pathlib import Path

from mac_reader import ROOT, load_table


def explore(data, entry, upper, table):
    todo, seen, owners = [entry], {}, {}
    issues, stops = [], []
    while todo:
        p = todo.pop()
        if p in seen:
            continue
        if not 12 <= p < upper <= len(data):
            issues.append({'offset': p, 'reason': '超出候选代码上界'})
            continue
        opcode = data[p]
        if opcode >= len(table) or not table[opcode]['bytes'] or p + table[opcode]['bytes'] > upper:
            issues.append({'offset': p, 'reason': '未知、变长或越界命令', 'opcode': opcode})
            continue
        length = table[opcode]['bytes']
        overlap = next((i for i in range(p, p + length) if i in owners), None)
        if overlap is not None:
            issues.append({'offset': p, 'reason': '与另一条指令重叠', 'existing': owners[overlap]})
            continue
        for i in range(p, p + length):
            owners[i] = p
        name = table[opcode]['name']
        seen[p] = {'offset': p, 'opcode': opcode, 'name': name, 'raw_hex': data[p:p + length].hex()}
        if opcode in (1, 5, 6, 7, 8):
            stops.append({'offset': p, 'reason': f'{name} 的后继需要上下文'})
            continue
        if opcode == 9 and data[p + 1] in (16, 17):
            stops.append({'offset': p, 'reason': '动态跳转未展开'})
            continue
        if opcode in (2, 3, 4):
            target = struct.unpack_from('<I', data, p + 4)[0]
            todo.append(target)
            if opcode == 3:
                continue
        todo.append(p + length)
    return {'entry': entry, 'upper': upper, 'instructions': [seen[p] for p in sorted(seen)],
            'issues': issues, 'stops': stops,
            'scope': '固定分支两侧均遍历；未计算条件、外部调用、返回栈或动态跳转，结果是候选而非运行轨迹'}


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--script', required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    checks = json.loads((ROOT / 'MAC_命令表/脚本验证.json').read_text(encoding='utf-8'))
    data = (ROOT / '输出-保护边修复/MAC' / args.script).read_bytes()
    if data[:8] != bytes.fromhex('09 11 00 60 08 00 00 00'):
        raise ValueError('入口格式不匹配')
    entry = struct.unpack_from('<I', data, 8)[0]
    result = explore(data, entry, checks[args.script]['text_start'], load_table())
    result['file'] = args.script
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
        f.write('\n')
    print('候选指令:', len(result['instructions']), '冲突:', len(result['issues']),
          '上下文停止:', len(result['stops']),
          '类型:', dict(Counter(x['name'] for x in result['instructions'])))


if __name__ == '__main__':
    main()
