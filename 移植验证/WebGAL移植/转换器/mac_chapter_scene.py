"""Compile chapter scenes across choice cut points using original jump targets."""
from bisect import bisect_left
from collections import deque
from pathlib import Path

from mac_jump import parse_int_goto
from mac_runtime_scene import compile_range, load_commands, scan_blockers
from mac_state import parse_if
from mac_story_wiring import scene_name


def compile_chapter(script, entry, graph, wiring, words, rows, voices, *, screen_effects=False,
                    particle_effects=False, linked_targets=(), graphics=None):
    commands = load_commands(script)
    offsets = {c['offset']: index for index, c in enumerate(commands)}
    name = Path(script).stem
    nodes = {node['offset']: node for node in graph['nodes'] if node['script'] == script}

    def site(offset):
        return f'{name}:0x{offset:X}'

    scan = scan_blockers(script, entry, words=words, sample_limit=len(commands), rows=rows, voices=voices,
                         screen_effects=screen_effects, particle_effects=particle_effects)
    stops = sorted({int(offset, 16) for blocker in scan['blockers'] for offset in blocker['offsets']}
                   | {offset for offset, node in nodes.items()
                      if 'options' in node or node['name'] == 'ext_goto'})
    todo, scenes = deque([entry]), {}
    while todo:
        start = todo.popleft()
        source = site(start)
        if source in scenes:
            continue
        position = bisect_left(stops, start)
        if position == len(stops):
            raise ValueError(f'{source} 后找不到可核实的场景边界')
        boundary = stops[position]
        external = {}
        for command in commands[offsets[start]:offsets[boundary]]:
            name_of_command = command['name']
            if name_of_command not in ('if', 'int_goto'):
                continue
            raw = bytes.fromhex(command['raw_hex'])
            target = parse_if(raw)[0] if name_of_command == 'if' else parse_int_goto(raw)
            if target < start or target > boundary:
                external[target] = scene_name(site(target))
        todo.extend(external)
        result = compile_range(script, start, end=boundary, words=words, target_scenes=external,
                               rows=rows, voices=voices, screen_effects=screen_effects,
                               particle_effects=particle_effects, graphics=graphics)
        if result.stop.offset != boundary or result.unresolved_targets:
            raise ValueError(f'{source} 编译边界不一致: {result.stop.as_dict()}')
        terminal = site(boundary)
        if result.stop.name == 'sel_disp4' and terminal in wiring:
            target_nodes = [edge['target'] for edge in nodes[boundary]['edges']]
            if any(not target.startswith(f'{name}:') for target in target_nodes):
                raise ValueError(f'{terminal} 的选项目标超出当前剧本')
            todo.extend(int(target.split(':')[1], 16) for target in target_nodes)
            tail = wiring[terminal]
        elif (result.stop.name == 'ext_goto' and terminal in wiring
              and nodes[boundary]['edges'][0]['target'] in linked_targets):
            tail = wiring[terminal]
        elif result.stop.name == 'end' and result.stop.raw_hex == '01010000':
            tail = ['end;']
        else:
            tail = [f'本版边界：{script} 0x{boundary:X} {result.stop.name}（{result.stop.category}）。;', 'end;']
        scenes[source] = (result, tail)
    return scenes
