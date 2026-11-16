"""从已有选项路径快照批量探索下一组；保留每个停止点。"""
import argparse
import copy
import csv
import json
from pathlib import Path

from emit_webgal import convert_chain, normalize_mapping_row
from mac_choice import plan_choice
from mac_new_game import NewGameRuntime
from mac_reader import ROOT, load_table
from 验证新游戏首选项 import DATA, MAC, verified_voices


def analyze(source, max_steps=20000, include_scenes=False, diagnostic_effects=False):
    prior = json.loads(source.read_text(encoding='utf-8'))
    scripts = {s['file']: s for s in json.loads((DATA / '入口片段.json').read_text(encoding='utf-8'))['scripts']}
    checks = json.loads((ROOT / 'MAC_命令表/脚本验证.json').read_text(encoding='utf-8'))
    with (DATA / '台词v74原始工程核查_批量拆分修复.tsv').open(encoding='utf-8-sig', newline='') as f:
        rows = [normalize_mapping_row(r) for r in csv.DictReader(f, delimiter='\t')]
    by_script = {}
    for row in rows:
        by_script.setdefault(row['剧本'], {})[int(row['指令偏移'], 16)] = row
    titles = json.loads((DATA / '章节标题静态表.json').read_text(encoding='utf-8'))['records']
    voices, table, cache = verified_voices(), load_table(), {}

    def load(name):
        if name not in cache:
            cache[name] = (MAC / name).read_bytes()
        return cache[name]

    output, blocked, plans = [], [], []
    if 'branches' in prior:
        predecessors = [([first['first_choice'], previous['choice']], previous)
                        for first in prior['branches'] for previous in first['paths']]
    elif 'paths' in prior:
        predecessors = [(previous['history'], previous) for previous in prior['paths']]
    else:
        raise ValueError('输入报告没有可识别的路径')
    for history, previous in predecessors:
        stop = previous['stop']
        if stop['name'] != 'sel_disp4':
            blocked.append({'history': history, 'stop': stop})
            continue
        runtime = NewGameRuntime(titles)
        runtime.state.memory_bytes = {int(k, 16): v for k, v in previous['state_bytes_at_stop'].items()}
        runtime.visited_bits = bytearray.fromhex(previous['visited_bits_after'])
        script, offset = stop['script'], stop['offset']
        info = checks[script]
        plan = plan_choice(load(script), info['boundary'], info['text_start'], offset, table, runtime.state)
        plans.append({'history': history, 'script': script, 'choice': plan})
        raw = bytes.fromhex(stop['raw_hex'])
        register = int.from_bytes(raw[2:4], 'little')
        for option in plan['options']:
            if not option['visible']:
                continue
            state = copy.deepcopy(runtime)
            state.state.write(register, option['index'])
            result = convert_chain(scripts, by_script, script, offset + len(raw), voices, load, MAC,
                                   runtime=state, titles=titles, max_gotos=3, max_steps=max_steps,
                                   diagnostic_effects=diagnostic_effects)
            taken = next((x for x in result['decisions'] if x['result']), None)
            if not taken or taken['target'] != option['target']:
                raise ValueError(f"路径 {history + [option['index']]} 的跳转不匹配: {taken}")
            path = {'history': history + [option['index']],
                    'choice_label_original': option['label_original'],
                    'dialogues': len(result['sources']), 'stop': result['stop'],
                    'segments': result['segments'],
                    'diagnostic_omissions': [e for e in result['displays']
                                             if e['name'] == 'diagnostic_effect_start_omitted'],
                    'visited_bits_after': state.report()['visited_bits_hex'],
                    'state_bytes_at_stop': {f'{k:05X}': v for k, v in
                                            sorted(state.state.memory_bytes.items())},
                    'sources': result['sources']}
            if include_scenes:
                path['scene_sequences'] = result['scene_sequences']
            output.append(path)
    return {'scope': '从前序选项的状态字节与章节位表继续模拟；未进行原游戏逐项对照。',
            'limitations': ['只使用当前已校验语音与转换器已实现指令；遇未知项即停。',
                            '原 quick_save 的所有副作用和画面演出尚未还原。',
                            '诊断模式可省略指定特效及其未知副作用；启用时后续状态不能视为原版等价。'],
            'diagnostic_effects': diagnostic_effects,
            'input': str(source), 'choice_plans': plans,
            'paths': output, 'blocked_predecessors': blocked}


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--input', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--max-steps', type=int, default=20000)
    p.add_argument('--diagnostic-effects', action='store_true',
                   help='仅诊断：省略指定特效及未知状态副作用，结果不代表原版等价')
    args = p.parse_args()
    if args.max_steps < 1:
        p.error('--max-steps 必须大于 0')
    report = analyze(args.input, args.max_steps, diagnostic_effects=args.diagnostic_effects)
    with args.output.open('x', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
        f.write('\n')
    print('已探索:', len(report['paths']), '未到选项:', len(report['blocked_predecessors']))
    from collections import Counter
    print('停止点:', Counter((p['stop']['script'], p['stop']['offset'], p['stop']['reason']) for p in report['paths']))
    print('报告:', args.output)


if __name__ == '__main__':
    main()
