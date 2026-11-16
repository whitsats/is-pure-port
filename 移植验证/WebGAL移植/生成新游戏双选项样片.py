"""在首选项样片后接入四选项及其 12 条已计算路径。"""
import csv
import json
from pathlib import Path
import re
import shutil
import sys

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE / '转换器'))
from 验证新游戏第二选项 import analyze
from 验证新游戏首选项 import DATA, MAC, VOICE_DIR
from 生成选项核查场景 import build_choice
from mac_reader import ROOT, load_table

SOURCE = BASE / '历史样片/新游戏首选项样片/public'
TARGET = BASE / '历史样片/新游戏双选项样片/public'


def main():
    if TARGET.exists():
        raise FileExistsError(f'拒绝覆盖已有样片: {TARGET}')
    if not SOURCE.is_dir():
        raise FileNotFoundError(f'请先生成首选项样片: {SOURCE}')
    report = analyze(include_scenes=True)
    info = json.loads((ROOT / 'MAC_命令表/脚本验证.json').read_text(encoding='utf-8'))['MAC_002.bin']
    with (DATA / '选项v74地址核查.tsv').open(encoding='utf-8-sig', newline='') as f:
        items = [r for r in csv.DictReader(f, delimiter='\t')
                 if r['脚本'] == 'MAC_002.bin' and int(r['选项指令偏移'], 16) == 0xA8]
    translations = {int(r['表内序号']): r for r in items}
    if len(translations) != len(items):
        raise ValueError('选项译文索引不唯一')
    choice_text, _ = build_choice((MAC / 'MAC_002.bin').read_bytes(), info['boundary'],
                                  info['text_start'], 0xA8, load_table(), translations)
    choice_command = next(line for line in choice_text.splitlines() if line.startswith('choose:'))
    for first in report['branches']:
        if [p['choice'] for p in first['paths']] != [0, 1, 2, 3]:
            raise ValueError('第二选项可见项或序号超出样片支持范围')
        for path in first['paths']:
            if [s['script'] for s in path['scene_sequences']] != ['MAC_002.bin', 'MAC_003.bin']:
                raise ValueError(f"第二选项路径不符合预期: {path['stop']}")
            if (path['stop']['script'], path['stop']['offset'], path['stop']['name']) != ('MAC_003.bin', 0x24C4, 'sel_disp4'):
                raise ValueError(f"第二选项未走到预期第三选项: {path['stop']}")
    shutil.copytree(SOURCE, TARGET)
    game = TARGET / 'game'
    scenes = game / 'scene'
    voices = set()
    for first in report['branches']:
        a = first['first_choice']
        original = (scenes / f'branch_{a}_002.txt').read_text(encoding='utf-8').splitlines()
        # 首选项样片的结尾两行是说明和 end；保留真正的三句第二章对白。
        if len(original) < 3 or not original[-2].startswith('流程验证：') or original[-1] != 'end;':
            raise ValueError('首选项样片的下一章场景格式不符合预期')
        lines = [*original[:-2], choice_command]
        for path in first['paths']:
            b = path['choice']
            name002 = f'choice_{a}_{b}_002.txt'
            name003 = f'choice_{a}_{b}_003.txt'
            lines.extend([f'label:choice_{b};', f'setVar:second_choice={b};', f'changeScene:{name002};'])
            seq = path['scene_sequences']
            (scenes / name002).write_text('\n'.join([*seq[0]['lines'], f'changeScene:{name003};', '']), encoding='utf-8')
            (scenes / name003).write_text('\n'.join([
                *seq[1]['lines'], f'流程验证：选择 {a + 1}-{b + 1} 已进入第三个选项，后续尚未接入。;',
                'end;', '']), encoding='utf-8')
            voices.update(s['voice'] for s in path['sources'] if s['voice'] >= 0)
        (scenes / f'branch_{a}_002.txt').write_text('\n'.join([*lines, '']), encoding='utf-8')
    for number in sorted(voices):
        name = f'VOICE_{number:05}.wav'
        target = game / 'vocal' / name
        if not target.exists():
            shutil.copy2(VOICE_DIR / name, target)
    config_path = game / 'config.txt'
    config = config_path.read_text(encoding='utf-8')
    config = config.replace('I’s Pure 新游戏首选项验证', 'I’s Pure 新游戏双选项验证')
    config = config.replace('Game_key:ISPfirstchoice01;', 'Game_key:ISPtwochoices01;')
    config_path.write_text(config, encoding='utf-8')
    summary = {'scope': report['scope'], 'limitations': report['limitations'],
               'paths': [{'first': first['first_choice'], 'second': p['choice'],
                          'dialogues_after_second': p['dialogues'], 'stop': p['stop']}
                         for first in report['branches'] for p in first['paths']],
               'runtime_note': '12 条路径按前两个选项预先展开，不代表全游戏动态分支已实现。'}
    (TARGET.parent / '生成报告.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n',
                                               encoding='utf-8')
    print('样片:', TARGET, '组合:', len(summary['paths']), '第二选项后用到的语音:', len(voices))


if __name__ == '__main__':
    main()
