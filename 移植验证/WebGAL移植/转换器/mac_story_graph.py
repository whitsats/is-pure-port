"""Trace candidate control flow from the original new-game entry."""
from collections import Counter, deque
from functools import cache
import struct

from mac_jump import parse_ext_goto, parse_int_call, parse_int_goto
from mac_reader import ROOT
from mac_state import COMPARISONS, State, UnsupportedCommand, parse_if
from MAC_批量选项分支 import inspect as inspect_choice

LINEAR = {
    'nop', 'msg_disp2', 'msg_disp', 'msg_mode', 'msg_view', 'msg_wait', 'msg_clear',
    'title_disp', 'reg_calc', 'quick_save', 'vib_set', 'time_wait',
    'file_read', 'file_wait', 'graph_disp', 'graph_pos', 'graph_prio',
    'fade_start', 'fade_wait', 'se_set', 'se_req', 'se_wait', 'se_speed', 'se_vol', 'se_del',
}
EFFECTS = {'effect_start', 'effect_wait', 'graph_pal', 'graph_anim', 'mask_load'}
# graph_pal/graph_anim advance IP by four bytes at 0x11B634/0x11C980.
# mask_load advances by four at 0x11F35C after a successful load.
SAVE_COMMANDS = {'save_lock', 'save_check'}
MEDIA_WAIT = {'movie_play'}  # successful path advances four bytes at 0x11DD74


def node_id(site):
    script, offset = site
    return f'{script.removesuffix(".bin")}:0x{offset:X}'


def trace(index, checks, mac_dir, start=('MAC_000.bin', 0x0C)):
    scripts = {
        s['file']: {c['offset']: c for c in s['commands']}
        for s in index['scripts']
    }
    if start[1] not in scripts.get(start[0], {}):
        raise ValueError(f'新游戏入口不在命令索引: {node_id(start)}')
    pending = deque([start])
    by_node = {}
    pending_controls = []
    effect_sites = []

    @cache
    def load_raw(script):
        return (mac_dir / script).read_bytes()

    def enqueue(source, target, edge, **details):
        entry = {'kind': edge, 'target': node_id(target), **details}
        source['edges'].append(entry)
        if target[1] not in scripts.get(target[0], {}):
            entry['unresolved'] = True
            pending_controls.append({'source': source['id'], **entry, 'reason': '目标不在已解析命令边界'})
        else:
            pending.append(target)

    state = State()
    while pending:
        script, offset = site = pending.popleft()
        if site in by_node:
            continue
        command = scripts[script][offset]
        raw = bytes.fromhex(command['raw_hex'])
        name = command['name']
        node = {'id': node_id(site), 'script': script, 'offset': offset, 'name': name,
                'raw_hex': command['raw_hex'], 'edges': []}
        by_node[site] = node
        following = (script, offset + len(raw))

        try:
            if name == 'if':
                target, left, right, comparison = parse_if(raw)
                lhs, rhs = state.describe(left), state.describe(right)
                node['condition'] = {'left': lhs, 'right': rhs, 'comparison': comparison}
                if lhs['kind'] == rhs['kind'] == 'value':
                    taken = COMPARISONS[comparison][1](lhs['value'], rhs['value'])
                    enqueue(node, (script, target) if taken else following, 'true' if taken else 'false')
                else:
                    enqueue(node, (script, target), 'true')
                    enqueue(node, following, 'false')
            elif name == 'int_goto':
                enqueue(node, (script, parse_int_goto(raw)), 'goto')
            elif name == 'ext_goto':
                jump = parse_ext_goto(raw, mac_dir)
                enqueue(node, (jump['target_script'], jump['target_entry']), 'cross_script', resource=jump['resource'])
            elif name == 'int_call':
                enqueue(node, (script, parse_int_call(raw)), 'call')
                enqueue(node, following, 'candidate_return_site')
            elif name == 'sel_disp4':
                data = load_raw(script)
                if data[offset:following[1]] != raw:
                    raise ValueError('索引里的选项原字节与剧本不一致')
                options = inspect_choice(data, offset, checks[script]['text_start'], scripts[script].keys())
                node['result_operand'] = f'0x{int.from_bytes(raw[2:4], "little"):04X}'
                node['dispatch_operand'] = '0x6000'  # verified by inspect_choice
                node['options'] = []
                always_visible = False
                for option_index, label, target, _, field in options:
                    condition = state.describe(field & 0xFFFF)
                    constant = condition['kind'] == 'value'
                    always_visible |= constant and condition['value'] != 0
                    node['options'].append({'index': option_index, 'label_original': label,
                                            'condition': condition, 'target': node_id((script, target))})
                    if not constant or condition['value'] != 0:
                        enqueue(node, (script, target), 'option', index=option_index)
                if not always_visible:
                    post_checks = (script, following[1] + 8 + 16 * len(options))
                    enqueue(node, post_checks, 'no_visible_option', result=len(options))
            elif name == 'end':
                node['end_mode'] = raw[1]
                node['terminal'] = 'end_candidate'
            elif name in EFFECTS:
                effect_sites.append(node['id'])
                enqueue(node, following, 'effect_continuation_candidate')
            elif name in SAVE_COMMANDS:
                # Both handlers advance four bytes. Their save side effects still need runtime handling.
                enqueue(node, following, 'save_continuation_candidate')
            elif name in MEDIA_WAIT:
                enqueue(node, following, 'media_continuation_candidate')
            elif name in LINEAR:
                enqueue(node, following, 'next')
            else:
                raise UnsupportedCommand(f'尚未验证控制流: {name}')
        except (KeyError, ValueError, IndexError, OSError, struct.error) as error:
            pending_controls.append({'source': node['id'], 'name': name, 'raw_hex': raw.hex(), 'reason': str(error)})

    nodes = sorted(by_node.values(), key=lambda node: (node['script'], node['offset']))
    endings = [node['id'] for node in nodes if node.get('terminal') == 'end_candidate']
    reached_scripts = sorted({node['script'] for node in nodes})
    return {
        'scope': '静态候选控制流。选项边汇总原序号的分派关系。实际执行需保留分派指令及写入。特效后继和调用返回点仍需运行期验证。',
        'root': node_id(start),
        'indexed_scripts': len(scripts),
        'skipped_scripts': index.get('skipped', []),
        'reached_scripts': reached_scripts,
        'other_indexed_scripts': sorted(set(scripts) - set(reached_scripts)),
        'reached_nodes': len(nodes),
        'choice_groups': sum('options' in node for node in nodes),
        'edge_counts': dict(sorted(Counter(edge['kind'] for node in nodes for edge in node['edges']).items())),
        'reached_end_candidates': endings,
        'all_indexed_end_candidates': [
            node_id((script, c['offset'])) for script, commands in sorted(scripts.items())
            for c in commands.values() if c['name'] == 'end'
        ],
        'pending_controls': sorted(pending_controls, key=lambda item: item['source']),
        'effect_sites': sorted(effect_sites),
        'nodes': nodes,
    }
