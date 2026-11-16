"""Extend the v7.4 disc sample from MAC_007:0x4314 into MAC_008, MAC_009 and the MAC_010 opening.

Dialogue and choices come from `数据/v74打盘优先对白.tsv` and
`数据/全盘主线接线_打盘版.json`; control flow from the original scripts. The
three MAC_007 scenes that used to stop at the `0x4314 ext_goto` boundary are
rewritten to `changeScene:mac_008_0x00000c.txt;`. MAC_010 is only opened up to
`0xB98`, because the `if` there targets `0xF30`, whose original bytes are control
codes only (`%P`) and still need to be confirmed.
"""
import argparse
import json
from pathlib import Path
import re
import shutil
import sys

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE / '转换器'))
from mac_chapter_scene import compile_chapter
from mac_release import DISC_WIRING
from mac_runtime_scene import collect_operands, compile_range, load_commands, load_rows
from mac_story_wiring import scene_name
from 生成新游戏MAC004样片 import check_layout
from 验证新游戏首选项 import DATA, VOICE_DIR, verified_voices

SAMPLE = BASE / '新游戏打盘版/public'
MANIFESTS = ('语音校验_MAC007_语音1391至1723.json',
             '语音校验_MAC008至MAC009_语音新增.json',
             '语音校验_MAC010开篇_语音1851至1915.json')
MAC007_BOUNDARY = '本版边界：MAC_007.bin 0x4314 ext_goto（cross_script）。;'
MAC007_CHANGE = 'changeScene:mac_008_0x00000c.txt;'
MAC010_END = 0xB8C       # 最后一条可编译指令；下一处 0xB98 的 if 目标 0xF30 未核实
MAC010_BOUNDARY = '本版边界：MAC_010.bin 0xB98 if→0xF30（目标原文只有控制码，待核实）。'


def tracked_words(scripts, initialized):
    graph = json.loads((DATA / '全盘剧情候选图.json').read_text(encoding='utf-8'))
    conditions = {int(option['condition']['raw'], 16) for node in graph['nodes']
                  if node['script'] in scripts for option in node.get('options', [])
                  if option['condition']['kind'] != 'value'}
    words = tuple(sorted(initialized.union(conditions, *(collect_operands(load_commands(script))
                                                        for script in scripts))))
    check_layout(words)
    return words, graph


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--sample', type=Path, default=SAMPLE, help='现行打盘版样片的 public 目录')
    args = parser.parse_args()
    sample = args.sample
    report_path = sample.parent / '生成报告_008至010.json'
    if report_path.exists():
        raise FileExistsError(f'本章已经接续过: {report_path}')
    if (sample / 'game/scene/mac_008_0x00000c.txt').exists():
        raise FileExistsError('样片里已经有 MAC_008 场景，请换一份未接续的输出')
    stale = sorted(path.name for pattern in ('mac_008_*.txt', 'mac_009_*.txt', 'mac_010_*.txt')
                   for path in (sample / 'game/scene').glob(pattern))
    if stale:
        raise FileExistsError(f'样片里已有本次要生成的章节场景: {stale}')

    start_text = (sample / 'game/scene/start.txt').read_text(encoding='utf-8')
    initialized = {int(word, 16) for word in
                   re.findall(r'^setVar:mac_([0-9a-f]{4})=0 -next;$', start_text, re.M)}
    scripts = ['MAC_008.bin', 'MAC_009.bin', 'MAC_010.bin']
    words, graph = tracked_words(scripts, initialized)
    wiring = json.loads(DISC_WIRING.read_text(encoding='utf-8'))['emitted']
    voices = verified_voices(MANIFESTS)

    scenes = compile_chapter('MAC_008.bin', 0xC, graph, wiring, words,
                             load_rows('MAC_008.bin'), voices, linked_targets=('MAC_009:0xC',))
    scenes.update(compile_chapter('MAC_009.bin', 0xC, graph, wiring, words,
                                  load_rows('MAC_009.bin'), voices, linked_targets=('MAC_010:0xC',)))
    opening = compile_range('MAC_010.bin', 0xC, end=MAC010_END, words=words,
                            rows=load_rows('MAC_010.bin'), voices=voices)
    if opening.stop.offset != MAC010_END + 0xC or opening.unresolved_targets:
        raise ValueError(f'MAC_010 开篇边界与预期不符: {opening.stop.as_dict()}')
    opening_tail = [MAC010_BOUNDARY, 'end;']

    scene_dir = sample / 'game/scene'
    written = {}
    for entry, (result, tail) in scenes.items():
        text = '\n'.join([*result.lines, *tail]) + '\n'
        (scene_dir / scene_name(entry)).write_text(text, encoding='utf-8')
        written[entry] = {'scene': scene_name(entry), 'stop': result.stop.as_dict(),
                          'lines': len(result.lines), 'voices': len(result.used_voices)}
    opening_name = scene_name('MAC_010:0xC')
    (scene_dir / opening_name).write_text(
        '\n'.join([*opening.lines, *opening_tail]) + '\n', encoding='utf-8')
    written['MAC_010:0xC'] = {'scene': opening_name, 'stop': opening.stop.as_dict(),
                              'lines': len(opening.lines), 'voices': len(opening.used_voices),
                              'note': '只接开篇；停点原因见 stop 与 MAC010_BOUNDARY'}

    # 原先停在 MAC_007 章末的三条剧情都改接下一章。
    rewired = []
    for path in sorted(scene_dir.glob('mac_007_*.txt')):
        lines = path.read_text(encoding='utf-8').splitlines()
        if lines[-1:] == [MAC007_CHANGE]:
            rewired.append(path.name)
            continue
        if lines[-2:] != [MAC007_BOUNDARY, 'end;']:
            continue
        path.write_text('\n'.join([*lines[:-2], MAC007_CHANGE]) + '\n', encoding='utf-8')
        rewired.append(path.name)
    if len(rewired) != 3:
        raise ValueError(f'接到 MAC_008 的 MAC_007 场景应为 3 个，实际 {rewired}')

    used = {number for result, _ in scenes.values() for number in result.used_voices}
    used |= opening.used_voices
    unverified = used - voices.keys()
    if unverified:
        raise ValueError(f'有语音未经校验: {sorted(unverified)}')
    copied = []
    for number in sorted(used):
        wav = f'VOICE_{number:05}.wav'
        target = sample / 'game/vocal' / wav
        if not target.exists():
            shutil.copy2(VOICE_DIR / wav, target)
            copied.append(wav)

    chapter_scenes = [path for pattern in ('mac_008_*.txt', 'mac_009_*.txt', 'mac_010_*.txt')
                      for path in scene_dir.glob(pattern)]
    missing = sorted({line.split('changeScene:', 1)[1].rstrip(';') for path in chapter_scenes
                      for line in path.read_text(encoding='utf-8').splitlines()
                      if line.startswith('changeScene:')} - {path.name for path in scene_dir.glob('*.txt')})
    if missing:
        raise ValueError(f'changeScene 目标场景不存在: {missing}')
    absent = sorted({name for path in chapter_scenes
                     for name in re.findall(r'-(VOICE_\d{5}\.wav)', path.read_text(encoding='utf-8'))
                     if not (sample / 'game/vocal' / name).exists()})
    if absent:
        raise ValueError(f'场景引用的语音文件不存在: {absent}')

    config = sample / 'game/config.txt'
    config.write_text(re.sub(r'^Game_key:[^;]*;', 'Game_key:ISPv74Disc02;',
                             config.read_text(encoding='utf-8'), flags=re.M), encoding='utf-8')
    report = {
        'scope': '从 MAC_007 章末接 MAC_008、MAC_009 两章，并只接 MAC_010 开篇用于核验下一章标题与对白。',
        'dialogue_source': '数据/v74打盘优先对白.tsv（v7.4 打盘归档）',
        'wiring_source': str(DISC_WIRING.relative_to(BASE)),
        'voice_manifests': list(MANIFESTS),
        'rewired_mac007': rewired,
        'used_voices': len(used),
        'copied_voices': copied,
        'scenes': written,
        'mac010_cut': {'end': f'0x{MAC010_END:X}', 'next': '0xB98 if → 0xF30',
                       'pending': '0xF30 的 msg_disp2 原文为 %P 控制码，译文与语义待核'},
    }
    with report_path.open('x', encoding='utf-8') as file:
        json.dump(report, file, ensure_ascii=False, indent=2)
        file.write('\n')
    for entry, info in written.items():
        print(entry, info['stop']['name'], f"{info['stop']['offset']:#x}", info['lines'], '行',
              info['voices'], '语音')
    print('改接 MAC_007 场景:', rewired)
    print('语音: 本次使用', len(used), '个，新复制', len(copied))
    print('报告:', report_path)


if __name__ == '__main__':
    main()
