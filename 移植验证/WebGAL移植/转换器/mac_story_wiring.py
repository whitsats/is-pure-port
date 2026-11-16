"""Emit WebGAL transitions from traced MAC choice and cross-script edges."""
import csv
from pathlib import Path


def scene_name(node_id):
    script, offset = node_id.split(':')
    return f'{script.lower()}_0x{int(offset, 16):06x}.txt'


def read_translations(path):
    with path.open(encoding='utf-8-sig', newline='') as file:
        rows = {}
        for row in csv.DictReader(file, delimiter='\t'):
            site = f"{Path(row['脚本']).stem}:0x{int(row['选项指令偏移'], 16):X}"
            key = (site, int(row['表内序号']))
            if key in rows:
                raise ValueError(f'选项译文地址重复: {key}')
            rows[key] = row
    return rows


def emit_choice(node, translations, resolve_scene=scene_name):
    """Keep source indices and the original no-visible-choice return."""
    active = []
    for option in node['options']:
        condition = option['condition']
        if condition['kind'] == 'value' and not condition['value']:
            continue
        row = translations.get((node['id'], option['index']))
        text = row['汉化包中文'] if row else ''
        if (not row or row['匹配状态'] != '唯一匹配' or row['日文原文'] != option['label_original']
                or not text or any(c in text for c in ';:|\\\r\n') or '->' in text):
            raise ValueError(f"{node['id']} 第 {option['index']} 项缺少可用的唯一译文")
        address = None if condition['kind'] == 'value' else int(condition['raw'], 16)
        name = None if address is None else f'mac_{address:04x}'
        active.append((option, text, name))

    def transition(value, target):
        return [
            f'setVar:mac_{int(node[key], 16):04x}={value} -next;'
            for key in ('result_operand', 'dispatch_operand')
        ] + [f'changeScene:{resolve_scene(target)};']

    lines = []
    fallback = next((edge for edge in node['edges'] if edge['kind'] == 'no_visible_option'), None)
    if not active:
        if fallback is None:
            raise ValueError(f"{node['id']} 缺少无可见项的跳转")
        return transition(fallback['result'], fallback['target'])
    if fallback:
        checks = '&&'.join(f'{name}==0' for _, _, name in active)
        lines.append(f'jumpLabel:no_visible_option -when={checks};')
    entries = []
    handlers = []
    for option, text, name in active:
        index = option['index']
        label = f'option_{index}'
        condition = f'({name}!=0)->' if name else ''
        entries.append(f'{condition}{text}:{label}')
        handlers.extend([f'label:{label} -next;', *transition(index, option['target'])])
    lines.extend([f"choose:{'|'.join(entries)};", *handlers])
    if fallback:
        lines.extend(['label:no_visible_option -next;', *transition(fallback['result'], fallback['target'])])
    return lines


def emit_transitions(graph, translations):
    emitted, missing = {}, []
    for node in graph['nodes']:
        edges = node['edges']
        if 'options' not in node and not any(edge['kind'] == 'cross_script' for edge in edges):
            continue
        if any(edge.get('unresolved') for edge in edges):
            missing.append({'site': node['id'], 'reason': '目标未解析'})
            continue
        if 'options' in node:
            try:
                emitted[node['id']] = emit_choice(node, translations)
            except ValueError as error:
                missing.append({'site': node['id'], 'reason': str(error)})
        else:
            emitted[node['id']] = [f"changeScene:{scene_name(edges[0]['target'])};"]
    return {'scope': '已生成的向下接线脚本片段。需与目标场景和 WebGAL 运行时状态合并。',
            'emitted': emitted, 'missing': missing}
