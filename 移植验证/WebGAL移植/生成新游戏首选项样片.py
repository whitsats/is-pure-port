"""生成新游戏到首选项、三条分支及下一章开头的受控样片。"""
import csv
import json
from pathlib import Path
import shutil
import sys

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE / '转换器'))
from 验证新游戏首选项 import analyze, DATA, MAC, VOICE_DIR
from 生成选项核查场景 import build_choice
from mac_reader import ROOT, load_table

TARGET = BASE / '历史样片/新游戏首选项样片/public'
SOURCE = BASE / '历史样片/样片/public'


def main():
    if TARGET.exists():
        raise FileExistsError(f'拒绝覆盖已有样片: {TARGET}')
    report = analyze(include_scenes=True)
    info = json.loads((ROOT / 'MAC_命令表/脚本验证.json').read_text(encoding='utf-8'))['MAC_001.bin']
    with (DATA / '选项v74地址核查.tsv').open(encoding='utf-8-sig', newline='') as f:
        items = [r for r in csv.DictReader(f, delimiter='\t')
                 if r['脚本'] == 'MAC_001.bin' and int(r['选项指令偏移'], 16) == 0x3878]
    translations = {int(r['表内序号']): r for r in items}
    if len(translations) != len(items):
        raise ValueError('选项译文索引不唯一')
    choice_text, _ = build_choice((MAC / 'MAC_001.bin').read_bytes(), info['boundary'],
                                  info['text_start'], 0x3878, load_table(), translations)
    choice_command = next(line for line in choice_text.splitlines() if line.startswith('choose:'))
    opening = report['opening']['scene_sequences']
    if [s['script'] for s in opening] != ['MAC_000.bin', 'MAC_001.bin']:
        raise ValueError('开头场景序列不符合预期')
    for branch in report['branches']:
        if [s['script'] for s in branch['scene_sequences']] != ['MAC_001.bin', 'MAC_002.bin']:
            raise ValueError(f"分支场景序列不符合预期: {branch['index']}")
    shutil.copytree(SOURCE, TARGET)
    game = TARGET / 'game'
    scenes = game / 'scene'
    (scenes / 'start.txt').write_text('\n'.join([
        'changeBg:is_sample.png -next;',
        '剧情流程验证样片：背景为占位图，画面和音效尚未按原版接入。;',
        *opening[0]['lines'], 'changeScene:opening_001.txt;', '']), encoding='utf-8')
    # MAC_001:0x28 的 BG_0016 与空白卡原版截图相符；只接入这处已对照背景。
    choice_lines = ['changeBg:verified_corridor.png -next;', *opening[1]['lines'], choice_command]
    for branch in report['branches']:
        index = branch['index']
        choice_lines.extend([f'label:choice_{index};', f'setVar:first_choice={index};',
                             f'changeScene:branch_{index}_001.txt;'])
        seq = branch['scene_sequences']
        (scenes / f'branch_{index}_001.txt').write_text(
            '\n'.join([*seq[0]['lines'], f'changeScene:branch_{index}_002.txt;', '']), encoding='utf-8')
        (scenes / f'branch_{index}_002.txt').write_text('\n'.join([
            *seq[1]['lines'],
            f'流程验证：第 {index + 1} 条分支已进入下一章，后续选项尚未接入。;',
            'end;', '']), encoding='utf-8')
    (scenes / 'opening_001.txt').write_text('\n'.join([*choice_lines, '']), encoding='utf-8')
    shutil.copy2(ROOT / '输出-保护边修复/BG/BG_0016.png', game / 'background/verified_corridor.png')
    used_voices = {s['voice'] for b in report['branches'] for s in b['sources'] if s['voice'] >= 0}
    # 开头命令中含已校验的语音文件名；只复制实际引用的资源。
    import re
    for sequence in opening:
        for line in sequence['lines']:
            used_voices.update(int(n) for n in re.findall(r'VOICE_(\d{5})\.wav', line))
    (game / 'vocal').mkdir(exist_ok=True)
    for number in sorted(used_voices):
        name = f'VOICE_{number:05}.wav'
        shutil.copy2(VOICE_DIR / name, game / 'vocal' / name)
    config_path = game / 'config.txt'
    config = config_path.read_text(encoding='utf-8')
    config = config.replace('Game_name:I’s Pure 手工测试样片;', 'Game_name:I’s Pure 新游戏首选项验证;')
    config = config.replace('Game_key:ISPtest01;', 'Game_key:ISPfirstchoice01;')
    config_path.write_text(config, encoding='utf-8')
    summary = {'scope': report['scope'], 'limitations': report['limitations'],
               'opening_dialogues': report['opening']['dialogues'],
               'branches': [{k: b[k] for k in ('index', 'dialogues', 'stop', 'visited_bits_after')}
                            for b in report['branches']], 'voice_files': len(used_voices),
               'runtime_note': '本样片将三条路径预先展开，只覆盖首个选项；不代表通用动态分支已实现。'}
    (TARGET.parent / '生成报告.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n',
                                               encoding='utf-8')
    print('样片:', TARGET, '开头对白:', summary['opening_dialogues'], '语音:', len(used_voices))


if __name__ == '__main__':
    main()
