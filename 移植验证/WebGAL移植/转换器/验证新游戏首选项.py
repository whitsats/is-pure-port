"""从新游戏执行到首个选项，复制真实路径状态后探索各选项。

只生成研究报告，不改动游戏或生成可发布的场景。状态与执行语义仍是
当前已核实的转换器子集；路径结果不能替代原游戏选项逐项对照。
"""
import argparse
import copy
import csv
import hashlib
import json
from pathlib import Path

from emit_webgal import convert_chain, normalize_mapping_row
from mac_choice import plan_choice
from mac_new_game import NewGameRuntime
from mac_reader import ROOT, load_table

BASE = Path(__file__).resolve().parents[1]
DATA = BASE / '数据'
MAC = ROOT / '输出-保护边修复/MAC'
VOICE_DIR = ROOT / '输出-保护边修复/VOICE/wav'
MANIFESTS = ('语音样本校验.json', '语音校验_MAC000_语音2至16.json',
             '语音校验_MAC000_语音17至25.json', '语音校验_MAC000_语音26至40.json',
             '语音校验_MAC001_语音41至214.json', '语音校验_MAC001_语音215至230.json',
             '语音校验_MAC001_语音231至281.json', '语音校验_MAC002_语音282至336.json',
             '语音校验_MAC003_语音337至801.json', '语音校验_MAC004_语音802至960.json',
             '语音校验_MAC005_语音961至1136.json')


def verified_voices(additional_manifests=()):
    voices = {}
    for name in (*MANIFESTS, *additional_manifests):
        manifest = json.loads((DATA / name).read_text(encoding='utf-8'))
        for entry in manifest['entries']:
            number = entry['id']
            if not isinstance(number, int) or number < 0 or not entry['source_equal'] or not entry['pcm_equal']:
                raise ValueError(f'语音校验记录无效: {name}, {number}')
            filename = f'VOICE_{number:05}.wav'
            if hashlib.sha256((VOICE_DIR / filename).read_bytes()).hexdigest() != entry['wav_sha256']:
                raise ValueError(f'语音校验哈希不符: {filename}')
            voices[number] = filename
    return voices


def analyze(max_steps=20000, include_scenes=False, webgal_words=()):
    scripts = json.loads((DATA / '入口片段.json').read_text(encoding='utf-8'))['scripts']
    by_file = {s['file']: s for s in scripts}
    with (DATA / '台词v74原始工程核查_拆分修复.tsv').open(encoding='utf-8-sig', newline='') as f:
        rows = [normalize_mapping_row(row) for row in csv.DictReader(f, delimiter='\t')]
    rows_by_script = {}
    for row in rows:
        rows_by_script.setdefault(row['剧本'], {})[int(row['指令偏移'], 16)] = row
    titles = json.loads((DATA / '章节标题静态表.json').read_text(encoding='utf-8'))['records']
    voices = verified_voices()
    cache = {}

    def load(name):
        if name not in cache:
            cache[name] = (MAC / name).read_bytes()
        return cache[name]

    runtime = NewGameRuntime(titles)
    opening = convert_chain(by_file, rows_by_script, 'MAC_000.bin', 0x0C, voices, load, MAC,
                            runtime=runtime, titles=titles, max_steps=max_steps, webgal_words=webgal_words)
    stop = opening['stop']
    if (stop['script'], stop['offset'], stop['name']) != ('MAC_001.bin', 0x3878, 'sel_disp4'):
        raise ValueError(f'新游戏未到预期首选项: {stop}')
    info = json.loads((ROOT / 'MAC_命令表/脚本验证.json').read_text(encoding='utf-8'))[stop['script']]
    choice = plan_choice(load(stop['script']), info['boundary'], info['text_start'],
                         stop['offset'], load_table(), runtime.state)
    raw = bytes.fromhex(stop['raw_hex'])
    result_register = int.from_bytes(raw[2:4], 'little')
    branches = []
    for option in choice['options']:
        if not option['visible']:
            continue
        branch_runtime = copy.deepcopy(runtime)
        branch_runtime.state.write(result_register, option['index'])
        result = convert_chain(by_file, rows_by_script, stop['script'], stop['offset'] + len(raw),
                               voices, load, MAC, runtime=branch_runtime, titles=titles,
                               max_gotos=3, max_steps=max_steps, webgal_words=webgal_words)
        taken = next((x for x in result['decisions'] if x['result']), None)
        if not taken or taken['target'] != option['target']:
            raise ValueError(f"选项 {option['index']} 条件跳转与选项表不一致: {taken}")
        branch = {'index': option['index'], 'original_label': option['label_original'],
                         'target': option['target'], 'first_taken_condition': taken,
                         'dialogues': len(result['sources']), 'stop': result['stop'],
                         'segments': result['segments'], 'jumps': result['jumps'],
                         'visited_bits_after': branch_runtime.report()['visited_bits_hex'],
                         'state_bytes_at_stop': {f'{k:05X}': v for k, v in
                                                 sorted(branch_runtime.state.memory_bytes.items())},
                         'sources': result['sources']}
        if include_scenes:
            branch['scene_sequences'] = result['scene_sequences']
        branches.append(branch)
    report = {'scope': '开头路径采用零初始状态；按已核实的选项返回值模拟分支，非原版逐项实测。',
            'limitations': ['未还原画面、音效与全部指令；只含已校验的语音。',
                            '脚本入口片段是候选范围；路径依赖转换器已有语义，不代表已通关。'],
            'opening': {'dialogues': len(opening['sources']), 'stop': stop,
                        'segments': opening['segments'],
                        'visited_bits': runtime.report()['visited_bits_hex'],
                        'state_bytes': {f'{k:05X}': v for k, v in sorted(runtime.state.memory_bytes.items())}},
            'choice': choice, 'result_register': f'0x{result_register:04X}', 'branches': branches}
    if include_scenes:
        report['opening']['scene_sequences'] = opening['scene_sequences']
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--max-steps', type=int, default=20000)
    args = parser.parse_args()
    if args.max_steps < 1:
        parser.error('--max-steps 必须大于 0')
    result = analyze(args.max_steps)
    with args.output.open('x', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
        f.write('\n')
    print('开头对白:', result['opening']['dialogues'], '选项:', len(result['branches']))
    for branch in result['branches']:
        print(branch['index'], '对白', branch['dialogues'], '停止:', branch['stop'])
    print('报告:', args.output)


if __name__ == '__main__':
    main()
