"""Replay a fixed series of choices against MAC state rules, without rendering."""
import argparse
import json
from pathlib import Path
import struct

from mac_new_game import NewGameRuntime
from mac_state import UnsupportedCommand, apply_reg_calc, evaluate_if
from mac_title_table import unpack_init

DATA = Path(__file__).resolve().parents[1] / '数据'
PROVISIONAL_EDGES = {
    'effect_continuation_candidate', 'media_continuation_candidate', 'save_continuation_candidate',
}


def read_scene_table(path):
    """Read the single type-0 record verified in original-disc cold boot memory."""
    data = unpack_init(path)
    offset = struct.unpack_from('<I', data, 0x64)[0]  # ELF 0x103B68–0x103BA0
    if not 0x80 <= offset <= len(data) - 16:
        raise ValueError(f'INIT 场景表越界: {offset:#x}')
    first, second, kind, _, sentinel = struct.unpack_from('<IIHHI', data, offset)
    if not (offset + 16 <= first < len(data) and offset + 16 <= second < len(data)
            and kind == 0 and sentinel == 0):
        raise ValueError('INIT 场景表布局与空白卡冷启动取证不符')
    return (bytes(data[offset:offset + 12]),)


def replay(graph, titles, positions, diagnostic=False, max_steps=200000, scene_table=None):
    nodes = {node['id']: node for node in graph['nodes']}
    current = graph['root']
    runtime = NewGameRuntime(titles, scene_table=scene_table)
    choices, crossings, omissions = [], [], []
    for step in range(max_steps):
        node = nodes[current]
        raw = bytes.fromhex(node['raw_hex'])
        edges = node['edges']
        name = node['name']
        try:
            if name == 'end':
                return result('end_candidate', current, step, choices, crossings, omissions, mode=node['end_mode'])
            if name == 'reg_calc':
                if raw[:2] == b'\x09\x17':
                    runtime.apply_reg17(raw)
                else:
                    apply_reg_calc(raw, runtime.state)
            if name == 'if':
                take, _, _ = evaluate_if(raw, runtime.state)
                edge = next((edge for edge in edges if edge['kind'] == ('true' if take else 'false')), None)
            elif 'options' in node:
                visible = [option['index'] for option in node['options']
                           if runtime.state.read(int(option['condition']['raw'], 16))]
                if visible:
                    position = positions[len(choices) % len(positions)]
                    value = visible[position % len(visible)]
                    edge = next((edge for edge in edges if edge['kind'] == 'option' and edge['index'] == value), None)
                else:
                    value = len(node['options'])
                    edge = next((edge for edge in edges if edge['kind'] == 'no_visible_option'), None)
                for key in ('result_operand', 'dispatch_operand'):
                    runtime.state.write(int(node[key], 16), value)
                choices.append({'site': current, 'visible': visible, 'result': value})
            elif len(edges) == 1:
                edge = edges[0]
            else:
                edge = None
        except UnsupportedCommand as error:
            return result('state_operation', current, step, choices, crossings, omissions, reason=str(error))
        if edge is None or edge.get('unresolved'):
            return result('control_flow', current, step, choices, crossings, omissions)
        if edge['kind'] in PROVISIONAL_EDGES:
            if not diagnostic:
                return result('presentation_or_save', current, step, choices, crossings, omissions, instruction=name)
            omissions.append({'site': current, 'instruction': name})
        if edge['kind'] == 'cross_script':
            crossings.append({'site': current, 'target': edge['target']})
        current = edge['target']
    return result('step_limit', current, max_steps, choices, crossings, omissions)


def result(status, last, steps, choices, crossings, omissions, **details):
    return {'status': status, 'site': last, 'steps': steps, 'choices': choices, 'crossings': crossings,
            'omissions': omissions, **details}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--graph', type=Path, default=DATA / '全盘剧情候选图.json')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--diagnostic', action='store_true', help='记录并略过尚未核实的演出及存档副作用')
    parser.add_argument('--disc-init', type=Path, help='从对应原盘 INIT 装载核实过的场景表')
    args = parser.parse_args()
    graph = json.loads(args.graph.read_text(encoding='utf-8'))
    titles = json.loads((DATA / '章节标题静态表.json').read_text(encoding='utf-8'))['records']
    patterns = [(0,), (1,), (2,), (0, 1, 2), (2, 1, 0)]
    table = read_scene_table(args.disc_init) if args.disc_init else None
    rows = [{'visible_position_pattern': positions,
             **replay(graph, titles, positions, args.diagnostic, scene_table=table)}
            for positions in patterns]
    with args.output.open('x', encoding='utf-8') as output:
        json.dump({'scope': '仅回放选择与状态。省略项见 omissions，结果需要原盘及 WebGAL 核查。',
                   'diagnostic': args.diagnostic,
                   'scene_table': {'source': str(args.disc_init), 'records': [record.hex() for record in table]}
                   if table else None,
                   'routes': rows}, output, ensure_ascii=False, indent=2)
        output.write('\n')
    for row in rows:
        print(row['visible_position_pattern'], row['status'], row['site'], len(row['choices']), '组选项')


if __name__ == '__main__':
    main()
