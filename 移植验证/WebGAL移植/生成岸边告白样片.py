"""Add the voiced MAC_006 dialogue and original choice routing to the previous build."""
import argparse
import json
from pathlib import Path
import re
import shutil
import sys

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE / '转换器'))
from mac_chapter_scene import compile_chapter
from mac_effect import SCREEN_START, PARTICLE_POLL
from mac_release import DISC_WIRING
from mac_runtime_scene import collect_operands, load_commands, load_rows
from mac_story_wiring import scene_name
from 合并拆分译文 import PATCH, merge_fragments
from 匹配汉化包选项 import read_patch
from 生成新游戏MAC004样片 import check_layout
from 验证新游戏首选项 import DATA, MAC, VOICE_DIR, verified_voices

SCRIPT = 'MAC_006.bin'
SOURCE = BASE / '历史样片/新游戏特效接续扩展/public'
TARGET = BASE / '历史样片/新游戏岸边告白/public'
CONTINUED_TARGET = BASE / '历史样片/新游戏岸边告白接续/public'


def dialogue_rows():
    rows = load_rows(SCRIPT)
    offset = 0x253C
    row = rows[offset]
    if row.get('译文来源') == 'v7.4 打盘归档':
        return rows, {'instruction': '0x253C', 'source': row['译文来源'], 'used_text': row['中文（原对照表）']}
    patch = PATCH / 'IS02/IS02_2.BIP.bin.txt'
    fragments = read_patch(patch)
    recovered = merge_fragments((MAC / SCRIPT).read_bytes(), int(row['文本偏移'], 16),
                                row['日文原文'], fragments, sorted(fragments))
    if recovered is None:
        raise ValueError('拆分对白 0x253C 没有逐字节匹配')
    first, second, rest = recovered['fragments']
    if first['chinese'] + second['chinese'] != '大人' or '大人' not in rest['chinese']:
        raise ValueError('拆分对白 0x253C 的译文结构已变化，请重新审读')
    # The last fragment contains the full Chinese sentence, including the two characters
    # repeated by the first two fragments as a result of the original emphasis split.
    text = rest['chinese']
    rows[offset] = {**row, '中文（原对照表）': text, '匹配状态': '唯一匹配'}
    return rows, {**recovered, 'used_text': text, 'instruction': f'0x{offset:X}', 'source': str(patch)}


def next_dialogue_rows():
    from 校验实际汉化盘 import PATCHED, mac

    script = 'MAC_007.bin'
    rows = load_rows(script)
    row = rows[0x360]
    if row.get('译文来源') == 'v7.4 打盘归档':
        return rows, {'instruction': '0x360', 'source': row['译文来源'], 'used_text': row['中文（原对照表）']}
    offset = int(row['文本偏移'], 16)
    original = (MAC / script).read_bytes()
    archive = PATCHED.read_bytes()
    entry = mac.entries(archive)[7]
    patched = mac.script(archive, entry)
    slot = bytes.fromhex('88a088a7817588b48163816388a681458140814588a88176254b255000')
    if (entry['name'].lower() != 'is02_3.bip' or original[0x360:0x36C] != patched[0x360:0x36C]
            or original[offset:offset + len(slot)] != row['日文原文'].encode('cp932') + b'\0'
            or patched[offset:offset + len(slot)] != slot):
        raise ValueError('MAC_007 确认过的汉化槽与输入不符')
    text = '一贵「什……伊织」'
    rows[0x360] = {**row, '中文（原对照表）': text, '匹配状态': '唯一匹配'}
    return rows, {'instruction': '0x360', 'source': str(PATCHED), 'slot': slot.hex(), 'used_text': text}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, default=SOURCE)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--continue-chapter', action='store_true', help='使用经验证的演出简化并接入 MAC_007')
    args = parser.parse_args()
    args.output = args.output or (CONTINUED_TARGET if args.continue_chapter else TARGET)
    if args.output.exists():
        raise FileExistsError(f'拒绝覆盖已有样片: {args.output}')
    graph = json.loads((DATA / '全盘剧情候选图.json').read_text(encoding='utf-8'))
    wiring = json.loads(DISC_WIRING.read_text(encoding='utf-8'))['emitted']
    rows, recovery = dialogue_rows()
    scripts = [SCRIPT]
    manifests = ['语音校验_MAC006_语音1137至1389.json']
    if args.continue_chapter:
        scripts.append('MAC_007.bin')
        manifests.append('语音校验_MAC007_语音1391至1723.json')
        indexed = {node['id']: node for node in graph['nodes']}
        poll = 'MAC_006:0x3BEC'
        predecessors = [node['id'] for node in graph['nodes'] if any(edge['target'] == poll for edge in node['edges'])]
        if (bytes.fromhex(indexed['MAC_006:0x3BA4']['raw_hex']) != SCREEN_START
                or bytes.fromhex(indexed[poll]['raw_hex']) != PARTICLE_POLL or predecessors != ['MAC_006:0x3BE4']):
            raise ValueError('类型 3 特效及其结束流程与取证不符')
    voices = verified_voices(manifests)
    start = (args.source / 'game/scene/start.txt').read_text(encoding='utf-8')
    initialized = {int(word, 16) for word in re.findall(r'^setVar:mac_([0-9a-f]{4})=0 -next;$', start, re.M)}
    conditions = {int(option['condition']['raw'], 16) for node in graph['nodes'] if node['script'] in scripts
                  for option in node.get('options', []) if option['condition']['kind'] != 'value'}
    words = tuple(sorted(initialized.union(conditions, *(collect_operands(load_commands(script)) for script in scripts))))
    check_layout(words)
    scenes = compile_chapter(SCRIPT, 0xC, graph, wiring, words, rows, voices,
                             screen_effects=args.continue_chapter,
                             linked_targets=('MAC_007:0xC',) if args.continue_chapter else ())
    next_recovery = None
    if args.continue_chapter:
        next_rows, next_recovery = next_dialogue_rows()
        scenes.update(compile_chapter('MAC_007.bin', 0xC, graph, wiring, words, next_rows, voices))
    shutil.copytree(args.source, args.output)
    destination = args.output / 'game'
    for entry, (result, tail) in scenes.items():
        (destination / 'scene' / scene_name(entry)).write_text('\n'.join([*result.lines, *tail]) + '\n',
                                                               encoding='utf-8')
    initial = ''.join(f'setVar:mac_{word:04x}=0 -next;\n' for word in words if word not in initialized)
    (destination / 'scene/start.txt').write_text(initial + start, encoding='utf-8')
    config = destination / 'config.txt'
    key = 'ISPmac00701' if args.continue_chapter else 'ISPmac00601'
    config.write_text(config.read_text(encoding='utf-8').replace('Game_key:ISPeffect01;', f'Game_key:{key};'),
                      encoding='utf-8')
    voice_ids = {number for result, _ in scenes.values() for number in result.used_voices}
    for number in sorted(voice_ids):
        wav = f'VOICE_{number:05}.wav'
        target = destination / 'vocal' / wav
        if not target.exists():
            shutil.copy2(VOICE_DIR / wav, target)
    report = {'split_dialogue': recovery, 'scene_count': len(scenes), 'used_voices': len(voice_ids),
              'scenes': {entry: result.stop.as_dict() for entry, (result, _) in scenes.items()}}
    if args.continue_chapter:
        effects = {record['offset']: record for result, _ in scenes.values() if result.script == SCRIPT
                   for record in result.ignored if record['category'] == 'screen_visual_omitted'}
        report.update(archive_dialogue=next_recovery, visual_changes=list(effects.values()),
                      limits='类型 3 结束等待近似 134 ms，特效画面和调色板变化暂不绘制。')
    with (args.output.parent / '生成报告.json').open('x', encoding='utf-8') as file:
        json.dump(report, file, ensure_ascii=False, indent=2)
        file.write('\n')
    for entry, (result, _) in scenes.items():
        print(entry, result.stop.name, f'{result.stop.offset:#x}', len(result.used_voices))


if __name__ == '__main__':
    main()
