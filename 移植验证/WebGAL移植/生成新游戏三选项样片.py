"""继续接入第三组选项，使用 WebGAL 条件显示已确认的状态依赖项。"""
import argparse
import csv
import json
from pathlib import Path
import re
import shutil
import sys

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE / '转换器'))
from 探索后续选项 import analyze
from 验证新游戏首选项 import DATA, MAC, VOICE_DIR, analyze as analyze_first
from 验证新游戏第二选项 import analyze as analyze_second
from mac_state import COMPARISONS, parse_if
from mac_reader import ROOT, load_table
from mac_runtime_scene import OPERANDS, continuation
from mac_webgal_state import emit_word_write, variable
from 生成选项核查场景 import build_choice

SOURCE = BASE / '历史样片/新游戏双选项样片/public'
TARGET = BASE / '历史样片/新游戏三选项样片/public'
PREVIOUS = DATA / '新游戏第二选项路径分析_拆分修复2.json'


def dynamic_condition():
    data = (MAC / 'MAC_003.bin').read_bytes()
    target, left, right, comparison = parse_if(data[0x24AC:0x24BC])
    if (target, left, right, comparison) != (0x24C4, 0x602C, 21, 4):
        raise ValueError('第三组选项的比较指令有变化')
    return [
        *emit_word_write(data[0x24A4:0x24AC], (0x6010,), 'third_set'),
        f'jumpLabel:third_ready -when={variable(left)}{COMPARISONS[comparison][0]}{right};',
        *emit_word_write(data[0x24BC:0x24C4], (0x6010,), 'third_clear'),
        'label:third_ready;',
    ]


def write_runtime_scenes(scenes, words):
    first = analyze_first(include_scenes=True, webgal_words=words)
    second = analyze_second(include_scenes=True, webgal_words=words, first=first)

    def replace(name, original, new):
        path = scenes / name
        scene = path.read_text(encoding='utf-8')
        start = '\n'.join(original) + '\n'
        if scene.count(start) != 1:
            raise ValueError(f'场景与转换器输出不一致: {name}')
        path.write_text(scene.replace(start, '\n'.join(new) + '\n', 1), encoding='utf-8')

    # Locate the state commands by comparing a fresh conversion against the existing scenes.
    plain_first = analyze_first(include_scenes=True)
    plain_second = analyze_second(include_scenes=True, first=plain_first)
    replace('start.txt', plain_first['opening']['scene_sequences'][0]['lines'],
            first['opening']['scene_sequences'][0]['lines'])
    for old, new in zip(plain_first['branches'], first['branches'], strict=True):
        replace(f"branch_{new['index']}_001.txt", old['scene_sequences'][0]['lines'],
                new['scene_sequences'][0]['lines'])
    for old, new in zip(plain_second['branches'], second['branches'], strict=True):
        for previous, current in zip(old['paths'], new['paths'], strict=True):
            for segment, chapter in enumerate((2, 3)):
                name = f"choice_{new['first_choice']}_{current['choice']}_{chapter:03d}.txt"
                replace(name, previous['scene_sequences'][segment]['lines'],
                        current['scene_sequences'][segment]['lines'])


def write_fourth_selection(scenes):
    data = (MAC / 'MAC_003.bin').read_bytes()
    offset = 0x34AC
    if data[offset:offset + 4] != bytes.fromhex('72020760'):
        raise ValueError('第四组选项原始编号寄存器有变化')
    info = json.loads((ROOT / 'MAC_命令表/脚本验证.json').read_text(encoding='utf-8'))['MAC_003.bin']
    with (DATA / '选项v74地址核查.tsv').open(encoding='utf-8-sig', newline='') as file:
        rows = {int(r['表内序号']): r for r in csv.DictReader(file, delimiter='\t')
                if r['脚本'] == 'MAC_003.bin' and int(r['选项指令偏移'], 16) == offset}
    choice_text, records = build_choice(data, info['boundary'], info['text_start'], offset, load_table(), rows)
    choice = next(line for line in choice_text.splitlines() if line.startswith('choose:'))
    lines, voices = continuation()
    lines.append(choice)
    for index, *_ in records:
        lines.extend([f'label:choice_{index} -next;', f'setVar:mac_6007={index} -next;', 'jumpLabel:fourth_done;'])
    lines.extend(['label:fourth_done -next;', '当前版本到此为止。;', 'end;'])
    (scenes / 'mac003_to_fourth.txt').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    for file in ['opening_001.txt', *(f'branch_{a}_002.txt' for a in range(3))]:
        scene = scenes / file
        source = scene.read_text(encoding='utf-8')
        output, count = re.subn(r'^(setVar:(?:first|second)_choice=(\d+));$',
                                r'\1 -next;\nsetVar:mac_6007=\2 -next;', source, flags=re.M)
        if count == 0:
            raise ValueError(f'未找到前组选项结果: {file}')
        scene.write_text(output, encoding='utf-8')
    start = scenes / 'start.txt'
    initial = ''.join(f'setVar:{variable(word)}=0 -next;\n' for word in OPERANDS)
    start.write_text(initial + start.read_text(encoding='utf-8'), encoding='utf-8')
    return voices


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--runtime-state', action='store_true')
    parser.add_argument('--through-fourth', action='store_true')
    args = parser.parse_args()
    if args.through_fourth:
        args.runtime_state = True
        target = BASE / '历史样片/新游戏动态第四选项/public'
    else:
        target = BASE / '历史样片/新游戏动态状态/public' if args.runtime_state else TARGET
    if target.exists():
        raise FileExistsError(f'拒绝覆盖已有样片: {target}')
    report = analyze(PREVIOUS, include_scenes=True)
    if report['blocked_predecessors'] or len(report['choice_plans']) != 12 or len(report['paths']) != 33:
        raise ValueError('第三选项探索范围与样片假设不符')
    with (DATA / '选项v74地址核查.tsv').open(encoding='utf-8-sig', newline='') as f:
        items = [r for r in csv.DictReader(f, delimiter='\t')
                 if r['脚本'] == 'MAC_003.bin' and int(r['选项指令偏移'], 16) == 0x24C4]
    translations = {int(r['表内序号']): r for r in items}
    if len(items) != 3 or len(translations) != 3:
        raise ValueError('第三选项译文数量或索引不符')
    for item in report['choice_plans']:
        options = item['choice']['options']
        for option in options:
            translated = translations[option['index']]
            if translated['匹配状态'] != '唯一匹配' or translated['日文原文'] != option['label_original']:
                raise ValueError('第三选项的地址、原文或译文不匹配')
            if any(c in translated['汉化包中文'] for c in ';:|\\\r\n'):
                raise ValueError('第三选项译文含未处理特殊字符')
        if [o['condition']['raw'] for o in options] != ['0x6010', '0x0001', '0x0001']:
            raise ValueError('第三选项显示条件有变化')
    for path in report['paths']:
        if len(path['scene_sequences']) != 1 or (path['stop']['script'], path['stop']['offset'],
                                                 path['stop']['name']) != ('MAC_003.bin', 0x34AC, 'sel_disp4'):
            raise ValueError(f"第三选项路径未抵达预期第四选项: {path['stop']}")
    shutil.copytree(SOURCE, target)
    game = target / 'game'
    scenes = game / 'scene'
    if args.runtime_state:
        write_runtime_scenes(scenes, OPERANDS if args.through_fourth else (0x602C,))
    voices = write_fourth_selection(scenes) if args.through_fourth else set()
    grouped = {}
    for path in report['paths']:
        a, b, c = path['history']
        grouped.setdefault((a, b), []).append(path)
        if args.through_fourth:
            continue
        scene_name = f'choice_{a}_{b}_{c}_003.txt'
        (scenes / scene_name).write_text('\n'.join([
            *path['scene_sequences'][0]['lines'],
            f'流程验证：选择 {a + 1}-{b + 1}-{c + 1} 已进入第四个选项，后续尚未接入。;',
            'end;', '']), encoding='utf-8')
        voices.update(s['voice'] for s in path['sources'] if s['voice'] >= 0)
    for item in report['choice_plans']:
        a, b = item['history']
        options = item['choice']['options']
        flag = options[0]['condition_value']
        path = scenes / f'choice_{a}_{b}_003.txt'
        existing = path.read_text(encoding='utf-8').splitlines()
        if len(existing) < 2 or not existing[-2].startswith('流程验证：') or existing[-1] != 'end;':
            raise ValueError('双选项样片的终点格式不符')
        labels = [translations[i]['汉化包中文'] for i in range(3)]
        choice = (f'choose:(mac_6010!=0)->{labels[0]}:third_0|'
                  f'{labels[1]}:third_1|{labels[2]}:third_2;')
        condition = dynamic_condition() if args.runtime_state else [f'setVar:mac_6010={flag};']
        lines = [*existing[:-2], *condition, choice]
        for path_result in grouped[(a, b)]:
            c = path_result['history'][2]
            if args.through_fourth:
                lines.extend([f'label:third_{c} -next;', f'setVar:third_choice={c} -next;',
                              f'setVar:mac_6007={c} -next;', 'changeScene:mac003_to_fourth.txt;'])
            else:
                lines.extend([f'label:third_{c};', f'setVar:third_choice={c};',
                              f'changeScene:choice_{a}_{b}_{c}_003.txt;'])
        path.write_text('\n'.join([*lines, '']), encoding='utf-8')
    for number in sorted(voices):
        name = f'VOICE_{number:05}.wav'
        voice_target = game / 'vocal' / name
        if not voice_target.exists():
            shutil.copy2(VOICE_DIR / name, voice_target)
    config_path = game / 'config.txt'
    config = config_path.read_text(encoding='utf-8')
    config = config.replace('I’s Pure 新游戏双选项验证', 'I’s Pure 新游戏三选项验证')
    config = config.replace('Game_key:ISPtwochoices01;', 'Game_key:ISPthreechoices01;')
    if args.runtime_state:
        config = config.replace('Game_key:ISPthreechoices01;', 'Game_key:ISPdynamicstate01;')
    if args.through_fourth:
        config = config.replace('Game_key:ISPdynamicstate01;', 'Game_key:ISPdynamicfourth01;')
    config_path.write_text(config, encoding='utf-8')
    summary = {'scope': report['scope'], 'limitations': report['limitations'],
               'paths': [{'history': p['history'], 'dialogues': p['dialogues'], 'stop': p['stop']}
                         for p in report['paths']],
               'runtime_note': '第三选项使用 WebGAL 变量判断 0x6010 的显示条件；'
                               '变量值按前两组选项的模拟状态设置，路径仍预先展开。'}
    if args.runtime_state:
        summary['runtime_note'] = '0x602C 的初始化及加减由 WebGAL 执行，0x6010 从当前值重新判断。其余剧情仍复用已展开场景。'
    if args.through_fourth:
        summary['runtime_note'] = '第三组选项写入原编号，直到第四组选项的对白、状态和跳转由共享 WebGAL 场景执行。'
    (target.parent / '生成报告.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n',
                                               encoding='utf-8')
    print('样片:', target, '组合:', len(summary['paths']), '第三选项后用到的语音:', len(voices))


if __name__ == '__main__':
    main()
