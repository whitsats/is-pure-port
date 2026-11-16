"""Extend the batch wiring sample through MAC_004 and MAC_005 into MAC_006."""
import argparse
import json
from pathlib import Path
import re
import shutil
import sys

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE / '转换器'))
from mac_effect import PARTICLE_PHASE, PARTICLE_POLL, PARTICLE_STOP
from mac_release import DISC_WIRING
from mac_runtime_scene import compile_range, load_commands, collect_operands, OPERANDS
from mac_story_wiring import scene_name
from 验证新游戏首选项 import VOICE_DIR
from 生成新游戏MAC004样片 import check_layout

SOURCE = BASE / '历史样片/新游戏批量接线/public'
TARGET = BASE / '历史样片/新游戏特效接续扩展/public'
SCRIPT = 'MAC_004.bin'


def verify_effect_pairs(commands, graph):
    """Ensure a completion poll cannot be reached without its immediately preceding request."""
    waits = [(cmd['offset'], bytes.fromhex(cmd['raw_hex'])) for cmd in commands if cmd['name'] == 'effect_wait']
    for (stop, request), (poll, raw) in zip(waits[::2], waits[1::2], strict=True):
        poll_id = f'MAC_004:0x{poll:X}'
        incoming = [node['id'] for node in graph['nodes'] if any(edge['target'] == poll_id for edge in node['edges'])]
        if request not in PARTICLE_STOP or raw != PARTICLE_POLL or stop + len(request) != poll or incoming != [f'MAC_004:0x{stop:X}']:
            raise ValueError(f'{poll_id} 缺少唯一的前置特效结束请求')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, default=SOURCE)
    parser.add_argument('--output', type=Path, default=TARGET)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(f'拒绝覆盖已有样片: {args.output}')
    data_dir = BASE / '数据'
    wiring = json.loads(DISC_WIRING.read_text(encoding='utf-8'))['emitted']
    graph = json.loads((data_dir / '全盘剧情候选图.json').read_text(encoding='utf-8'))
    commands = load_commands(SCRIPT)
    verify_effect_pairs(commands, graph)
    opening_006 = [cmd for cmd in load_commands('MAC_006.bin') if cmd['offset'] < 0x88]
    words = tuple(sorted(set(OPERANDS) | set(collect_operands(commands))
                         | set(collect_operands(load_commands('MAC_005.bin')))
                         | set(collect_operands(opening_006))))
    check_layout(words)
    shared = scene_name('MAC_004:0x359C')
    pieces = {}
    for start, end, expected_stop in [(0xA6C, None, 0x2CBC), (0xBF0, None, 0x2CBC),
                                      (0x2CF0, 0x323C, 0x3244), (0x3244, 0x359B, 0x359C),
                                      (0x359C, None, 0x3630)]:
        site = f'MAC_004:0x{start:X}'
        result = compile_range(SCRIPT, start, end=end, words=words, particle_effects=True,
                               target_scenes={0x359C: shared} if start < 0x359C else None)
        if result.stop.offset != expected_stop or result.unresolved_targets:
            raise ValueError(f'{site} 提前停止: {result.stop.as_dict()}')
        tail = wiring.get(f'MAC_004:0x{expected_stop:X}', [])
        if start == 0x3244:
            tail = [f'changeScene:{shared};']
        if not tail and result.lines[-1] != f'changeScene:{shared};':
            raise ValueError(f'{site} 未接到下一场景')
        pieces[site] = result, tail

    chapter = compile_range('MAC_005.bin', 0xC, words=words)
    if (chapter.stop.name, chapter.stop.offset) != ('ext_goto', 0x2120) or chapter.unresolved_targets:
        raise ValueError(f'MAC_005 提前停止: {chapter.stop.as_dict()}')
    pieces['MAC_005:0xC'] = chapter, wiring['MAC_005:0x2120']

    follow = compile_range('MAC_006.bin', 0xC, words=words)
    if not follow.lines or follow.stop.offset in (None, 0xC):
        raise ValueError(f'MAC_006 缺少可玩起始内容: {follow.stop.as_dict()}')
    stop = follow.stop
    pieces['MAC_006:0xC'] = follow, [f'本版边界：{stop.script} 0x{stop.offset:X} {stop.name}（{stop.category}）。;', 'end;']

    mapped = {entry['offset']: entry for result, _ in pieces.values() if result.script == SCRIPT
              for entry in result.ignored if entry['category'] == 'particle_visual_omitted'}
    expected_effects = {cmd['offset'] for cmd in commands if cmd['name'] in ('effect_start', 'effect_wait')}
    if mapped.keys() != expected_effects:
        raise ValueError('MAC_004 存在尚未生成的粒子特效指令')

    shutil.copytree(args.source, args.output)
    scenes = args.output / 'game/scene'
    for site, (result, tail) in pieces.items():
        (scenes / scene_name(site)).write_text('\n'.join([*result.lines, *tail]) + '\n', encoding='utf-8')
    start_file = scenes / 'start.txt'
    start_text = start_file.read_text(encoding='utf-8')
    initialized = {int(value, 16) for value in re.findall(r'^setVar:mac_([0-9a-f]{4})=0 -next;$', start_text, re.M)}
    initial = [f'setVar:{PARTICLE_PHASE}=0 -next;'] + [f'setVar:mac_{word:04x}=0 -next;' for word in words if word not in initialized]
    start_file.write_text('\n'.join([*initial, start_text]), encoding='utf-8')

    for voice in sorted({voice for result, _ in pieces.values() for voice in result.used_voices}):
        wav = f'VOICE_{voice:05}.wav'
        target = args.output / 'game/vocal' / wav
        if not target.exists():
            shutil.copy2(VOICE_DIR / wav, target)
    config_file = args.output / 'game/config.txt'
    config = config_file.read_text(encoding='utf-8').replace('Game_key:ISPstorywiring01;', 'Game_key:ISPeffect01;')
    config_file.write_text(config.replace('新游戏跨剧本验证', '特效接续验证'), encoding='utf-8')
    report = {'limitation': '粒子没有渲染；已核实的结束请求和完成检查在 WebGAL 保留一帧等待。',
              'effect_count': len(mapped), 'effect_sites': [mapped[offset] for offset in sorted(mapped)],
              'pieces': {site: {'scene': scene_name(site), 'lines': len(result.lines) + len(tail),
                                'voices': len(result.used_voices), 'stop': result.stop.as_dict()}
                         for site, (result, tail) in pieces.items()}}
    (args.output.parent / '生成报告.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('特效指令:', len(mapped), '场景:', len(pieces), '实跑待验边界:', stop.as_dict())


if __name__ == '__main__':
    main()
