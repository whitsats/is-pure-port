"""从首选项三条路径的状态继续探索 MAC_002 四选项。"""
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


def analyze(max_steps=20000, include_scenes=False, webgal_words=(), first=None):
    if first is None:
        first = json.loads((DATA / '新游戏首选项真实路径分析.json').read_text(encoding='utf-8'))
    scripts = {s['file']: s for s in json.loads((DATA / '入口片段.json').read_text(encoding='utf-8'))['scripts']}
    with (DATA / '台词v74原始工程核查_批量拆分修复.tsv').open(encoding='utf-8-sig', newline='') as f:
        rows = [normalize_mapping_row(r) for r in csv.DictReader(f, delimiter='\t')]
    by_script = {}
    for row in rows:
        by_script.setdefault(row['剧本'], {})[int(row['指令偏移'], 16)] = row
    titles = json.loads((DATA / '章节标题静态表.json').read_text(encoding='utf-8'))['records']
    info = json.loads((ROOT / 'MAC_命令表/脚本验证.json').read_text(encoding='utf-8'))['MAC_002.bin']
    cache = {}

    def load(name):
        if name not in cache:
            cache[name] = (MAC / name).read_bytes()
        return cache[name]

    voices = verified_voices()
    output = []
    for branch in first['branches']:
        if (branch['stop']['script'], branch['stop']['offset'], branch['stop']['name']) != ('MAC_002.bin', 0xA8, 'sel_disp4'):
            raise ValueError('首选项路径未到达预期第二选项')
        runtime = NewGameRuntime(titles)
        runtime.state.memory_bytes = {int(k, 16): v for k, v in branch['state_bytes_at_stop'].items()}
        runtime.visited_bits = bytearray.fromhex(branch['visited_bits_after'])
        plan = plan_choice(load('MAC_002.bin'), info['boundary'], info['text_start'], 0xA8,
                           load_table(), runtime.state)
        raw = bytes.fromhex(branch['stop']['raw_hex'])
        register = int.from_bytes(raw[2:4], 'little')
        results = []
        for option in plan['options']:
            if not option['visible']:
                continue
            state = copy.deepcopy(runtime)
            state.state.write(register, option['index'])
            result = convert_chain(scripts, by_script, 'MAC_002.bin', 0xA8 + len(raw),
                                   voices, load, MAC, runtime=state, titles=titles,
                                   max_gotos=3, max_steps=max_steps, webgal_words=webgal_words)
            taken = next((x for x in result['decisions'] if x['result']), None)
            if not taken or taken['target'] != option['target']:
                raise ValueError(f"第二选项 {option['index']} 的条件跳转与选项表不一致: {taken}")
            path = {'choice': option['index'], 'label_original': option['label_original'],
                            'target': option['target'], 'dialogues': len(result['sources']),
                            'stop': result['stop'], 'segments': result['segments'],
                            'visited_bits_after': state.report()['visited_bits_hex'],
                            'state_bytes_at_stop': {f'{k:05X}': v for k, v in
                                                    sorted(state.state.memory_bytes.items())},
                            'sources': result['sources']}
            if include_scenes:
                path['scene_sequences'] = result['scene_sequences']
            results.append(path)
        output.append({'first_choice': branch['index'], 'second_choice': plan, 'paths': results})
    return {'scope': '从首选项报告中的开头计算状态继续；采用已验证子集，非原版逐条对照。',
            'limitations': ['使用首选项报告中的状态字节与章节位表；原版 quick_save 副作用仍未完全实现。',
                            '只使用已经校验的语音；遇到未知指令、缺译或未校验语音即停。'],
            'first_report': '新游戏首选项真实路径分析.json', 'branches': output}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--max-steps', type=int, default=20000)
    args = parser.parse_args()
    if args.max_steps < 1:
        parser.error('--max-steps 必须大于 0')
    report = analyze(args.max_steps)
    with args.output.open('x', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
        f.write('\n')
    for first in report['branches']:
        for path in first['paths']:
            print(first['first_choice'], path['choice'], '对白', path['dialogues'], '停止', path['stop'])
    print('报告:', args.output)


if __name__ == '__main__':
    main()
