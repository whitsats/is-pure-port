"""生成受控的三选项剧情验证样片，保留零状态假设和未还原内容。"""
import csv
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE / '转换器'))
from emit_webgal import convert_program, normalize_mapping_row
from mac_reader import ROOT, load_table
from mac_state import State
from mac_jump import parse_ext_goto
from 生成选项核查场景 import build_choice

SCRIPT = 'MAC_001.bin'
SELECTION = 0x3878
TARGET = BASE / '历史样片/选项分支真实剧情样片/public'
DATA = BASE / '数据'
MANIFESTS = [DATA / '语音校验_MAC001_语音215至230.json',
             DATA / '语音校验_MAC001_语音231至281.json']
VOICE = re.compile(r'-(VOICE_\d{5}\.wav);')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--cross', action='store_true', help='在分支后接续下一剧本的可验证片段')
    parser.add_argument('--stateful', action='store_true', help='试验：将已执行的状态字节写入 WebGAL 场景变量')
    args = parser.parse_args()
    if args.stateful and not args.cross:
        raise ValueError('--stateful 需要 --cross')
    target_dir = (BASE / '历史样片/选项跨剧本状态样片/public' if args.stateful else
                  BASE / '历史样片/选项跨剧本流程样片/public' if args.cross else TARGET)
    if target_dir.exists():
        raise FileExistsError(f'拒绝覆盖已有样片: {target_dir}')
    script_data = (ROOT / '输出-保护边修复/MAC' / SCRIPT).read_bytes()
    info = json.loads((ROOT / 'MAC_命令表/脚本验证.json').read_text(encoding='utf-8'))[SCRIPT]
    with (DATA / '选项v74地址核查.tsv').open(encoding='utf-8-sig', newline='') as f:
        items = [r for r in csv.DictReader(f, delimiter='\t')
                 if r['脚本'] == SCRIPT and int(r['选项指令偏移'], 16) == SELECTION]
    translations = {int(r['表内序号']): r for r in items}
    if len(translations) != len(items):
        raise ValueError('选项翻译序号重复')
    choice_text, records = build_choice(script_data, info['boundary'], info['text_start'],
                                        SELECTION, load_table(), translations)
    choice = next(line for line in choice_text.splitlines() if line.startswith('choose:'))
    scripts = json.loads((DATA / '入口片段.json').read_text(encoding='utf-8'))['scripts']
    commands = next(item['commands'] for item in scripts if item['file'] == SCRIPT)
    with (DATA / '三版译文与汉化盘核查_补字码.tsv').open(encoding='utf-8-sig', newline='') as f:
        all_rows = [normalize_mapping_row(r) for r in csv.DictReader(f, delimiter='\t')]
    rows = {int(r['指令偏移'], 16): r for r in all_rows if r['剧本'] == SCRIPT}
    voices, source_by_name = {}, {}
    for manifest in MANIFESTS:
        for entry in json.loads(manifest.read_text(encoding='utf-8'))['entries']:
            number = entry['id']
            source = ROOT / f'输出-保护边修复/VOICE/wav/VOICE_{number:05}.wav'
            if not entry['source_equal'] or not entry['pcm_equal'] or hashlib.sha256(source.read_bytes()).hexdigest() != entry['wav_sha256']:
                raise ValueError(f'语音未通过来源校验: {number}')
            voices[number] = source.name
            source_by_name[source.name] = source
    lines = ['changeBg:is_sample.png -next;',
             '真实选项剧情流程验证：从原剧本的一处三选项开始。;',
             '初始状态假设为零，画面手工指定；选项顺序、演出和原版运行结果仍需对照。;', choice]
    reports, next_scenes = [], {}
    for index, _label, target, _field1, _field2 in records:
        state = State()
        state.write(0x6007, index)
        result = convert_program(commands, rows, SELECTION + 12, voices, state=state,
                                 data=script_data, emit_waits=True, emit_state_bytes=args.stateful)
        branch, sources, pacing, decisions, writes, displays, gotos, stop, reads, sounds, fades, waits = result
        taken = [d for d in decisions if d['result']]
        if not taken or taken[0]['target'] != target:
            raise ValueError(f'选项 {index} 的实际条件跳转与表中候选不符')
        if stop['name'] != 'ext_goto' or stop['offset'] != 0x51E4 or not sources:
            raise ValueError(f'选项 {index} 未到预期汇合点: {stop}')
        lines.append(f'label:choice_{index};')
        if args.stateful:
            # 假设本次选择的原表下标写入 0x6007；以两个字节表示其底层状态。
            lines.extend([f'setVar:mac_b_0022e={index};', 'setVar:mac_b_0022f=0;'])
        lines.extend(branch)
        target_report = None
        if args.cross:
            jump = parse_ext_goto(bytes.fromhex(stop['raw_hex']), ROOT / '输出-保护边修复/MAC')
            if jump['target_script'] != 'MAC_002.bin' or jump['target_entry'] != 0x0C:
                raise ValueError(f'下一剧本与预期不符: {jump}')
            next_script = next(item for item in scripts if item['file'] == jump['target_script'])
            next_rows = {int(r['指令偏移'], 16): r for r in all_rows if r['剧本'] == jump['target_script']}
            next_data = (ROOT / '输出-保护边修复/MAC' / jump['target_script']).read_bytes()
            following = convert_program(next_script['commands'], next_rows, jump['target_entry'], voices,
                                        state=state, data=next_data, emit_waits=True,
                                        emit_state_bytes=args.stateful)
            next_lines, next_sources, _, _, _, _, _, next_stop, _, _, _, _ = following
            if next_stop['name'] != 'reg_calc' or next_stop['offset'] != 0x74:
                raise ValueError(f'目标剧本停止位置与预期不符: {next_stop}')
            scene_name = f'mac002_after_choice_{index}.txt'
            next_scenes[scene_name] = [*next_lines,
                                       *(['本次选择编号：{mac_b_0022e}。;'] if args.stateful else []),
                                       '验证：下一剧本 MAC_002 已载入，后续状态指令尚未实现。;', 'end;']
            lines.extend([f'第 {index + 1} 条分支结束，继续验证下一剧本。;',
                          f'changeScene:{scene_name};'])
            target_report = {'script': jump['target_script'], 'entry': jump['target_entry'],
                             'scene': scene_name, 'sources': next_sources, 'stop': next_stop}
        else:
            lines.append(f'第 {index + 1} 条分支到达跨剧本跳转，验证片段在此结束。;')
        lines.append('jumpLabel:probe_end;')
        reports.append({'choice_index': index, 'hypothetical_return_value': index,
                        'target': f'0x{target:06X}', 'dialogues': len(sources),
                        'voices': sum(1 for s in sources if s['voice'] != -1),
                        'sources': sources, 'conditions': decisions, 'state_writes': writes,
                        'stop': stop, 'display_events_not_rendered': len(displays),
                        'sound_events_not_rendered': len(sounds),
                        'fade_events_not_rendered': len(fades), 'target_scene': target_report})
    lines.extend(['label:probe_end;', '提示：画面、音效和部分状态尚未完整还原。;', 'end;'])
    scene = '\n'.join(lines) + '\n'
    used = set(VOICE.findall(scene))
    if used - source_by_name.keys():
        raise ValueError(f'语音缺失: {sorted(used - source_by_name.keys())}')
    shutil.copytree(BASE / '历史样片/样片/public', target_dir)
    game = target_dir / 'game'
    (game / 'scene/start.txt').write_text(scene, encoding='utf-8', newline='\n')
    for name, next_lines in next_scenes.items():
        (game / 'scene' / name).write_text('\n'.join(next_lines) + '\n', encoding='utf-8', newline='\n')
    for name in used:
        shutil.copy2(source_by_name[name], game / 'vocal' / name)
    config = (game / 'config.txt').read_text(encoding='utf-8')
    config = config.replace('Game_name:I’s Pure 手工测试样片;', 'Game_name:I’s Pure 真实选项流程验证;')
    key = 'ISPchoiceState01' if args.stateful else 'ISPchoiceCross01' if args.cross else 'ISPchoiceReal01'
    config = config.replace('Game_key:ISPtest01;', f'Game_key:{key};')
    (game / 'config.txt').write_text(config, encoding='utf-8')
    report = {'script': SCRIPT, 'selection': f'0x{SELECTION:06X}',
              'assumption': '除选择结果寄存器外状态全零；不代表从新游戏真实抵达本选项。',
              'limitations': '画面手工指定；未映射画面、音效及淡入淡出；选项的实际返回顺序未与原版逐项对照。',
              'state_byte_emission': ('仅输出该假设轨迹中被修改的状态字节，非完整运行时状态。' if args.stateful else '未生成状态变量'),
              'branches': reports}
    (target_dir.parent / '分支生成报告.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    for item in reports:
        print(item['choice_index'], item['target'], 'dialogues', item['dialogues'], 'voices', item['voices'])
    print('Output:', target_dir)


if __name__ == '__main__':
    main()
