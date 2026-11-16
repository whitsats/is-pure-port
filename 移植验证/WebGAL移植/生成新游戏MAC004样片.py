"""把 MAC_003 分支结尾的 ext_goto 接到 MAC_004 开头，并接上该剧本第一组选项。

接续依据（全部可复核）：

- `MAC_003:0x6790` 的 `06 00 04 00` 是 4 字节 `ext_goto`；`mac_jump.parse_ext_goto`
  按 `MAC_命令表/跨剧本跳转候选.tsv` 的候选规则解析为组 0 索引 4 → `MAC_004.bin`，
  入口取该文件头 `u32@8` = `0x0C`。
- `MAC_004:0x5C` 的 `09 17 04 00` 是 `reg_calc 0x17`(4)：按 `mac_new_game` 里
  `0x00118FD0` 的实际顺序，写 `+0x440`（u16 下标）、`+0x4B0`（u32 旧位）并置位。
- `MAC_004:0x68` 的 `title_disp` 由 `mac_title_table.resolve_title_disp` 用静态
  57 条标题表解析出第 4 条 → `intro:新生欢迎晚会;`。
- `MAC_004:0xA38` 的 `72 02 07 60 08 3F 00 00` 是第一组选项：2 项、结果寄存器
  `0x6007`、表指针 `0x3F08`；两项条件字都是立即数 `0x0001`，目标 `0xA6C`/`0xBF0`
  都是命令边界；文本取 `数据/选项v74地址核查.tsv` 的唯一匹配并与盘上 cp932 逐字核对。

生成物：
- `mac_004_0x00000c.txt`：MAC_004 开头 → 第一组选项 → 两个分支入口；
- `mac_004_0x00000a6c.txt` / `mac_004_0x00000bf0.txt`：两条分支各自编译到 `0x1AA8` 特效；
- `mac003_fifth_branches.txt` 段末改为 `changeScene:mac_004_0x00000c.txt;`。
"""
import argparse
import json
from pathlib import Path
import re
import shutil
import sys

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE / '转换器'))
sys.path.insert(0, str(BASE.parent))
from mac_choice import plan_choice, read_options
from mac_reader import ROOT, load_table, read_entry_zero
from mac_runtime_scene import (OPERANDS, collect_operands, compile_range, load_commands,
                               scan_blockers)
from mac_state import State
from 验证新游戏首选项 import DATA, MAC, VOICE_DIR

SOURCE = BASE / '历史样片/新游戏动态第五选项/public'
TARGET = BASE / '历史样片/新游戏动态MAC004/public'
MAC003_SCRIPT = 'MAC_003.bin'
MAC004_SCRIPT = 'MAC_004.bin'
BRANCH_START = 0x5A90
BRANCH_TARGETS = (0x5A90, 0x5EB4, 0x626C)
MAC004_START = 0x0C
CHOICE = 0xA38


def scene_name(script, entry):
    return f'{Path(script).stem.lower()}_0x{entry:06x}.txt'


def check_layout(words):
    layout = State()
    described = {}
    for word in words:
        item = layout.describe(word)
        if item['kind'] == 'value':
            raise ValueError(f'跟踪列表里出现立即数: {word:#06x}')
        described[word] = (item['kind'], item['offset'],
                           item['offset'] + (1 if item['kind'] == 'word' else 0))
    for word, (kind, low, high) in sorted(described.items()):
        conflicts = [other for other, (other_kind, other_low, other_high) in described.items()
                     if other != word and other_low <= high and low <= other_high
                     and (kind != 'bit' or other_kind != 'bit')]
        if conflicts:
            raise ValueError(f'跨剧本状态操作数共享地址: {word:#06x} 与 '
                             + ', '.join(f'{other:#06x}' for other in sorted(conflicts)))


def read_choice(data, info, table, commands):
    """按第五组同一套约定解析 MAC_004:0xA38（解析逻辑在 `mac_choice.read_options`）。"""
    choice = read_options(data, info, table, commands, CHOICE, MAC004_SCRIPT,
                          DATA / '选项v74地址核查.tsv', bytes.fromhex('72020760'))
    plan = plan_choice(data, info['boundary'], info['text_start'], CHOICE, table, State())
    if plan['visible_indices'] != [option['index'] for option in choice['options']]:
        raise ValueError(f'MAC_004 第一组存在按状态隐藏的选项，需要按路径分别生成: {plan}')
    for option in choice['options']:
        option['scene'] = scene_name(MAC004_SCRIPT, option['target'])
    return choice['table_pointer'], choice['options']


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=TARGET)
    parser.add_argument('--wiring', type=Path, help='用全盘候选图输出的接线片段')
    args = parser.parse_args()
    target_root = args.output
    if target_root.exists():
        raise FileExistsError(f'拒绝覆盖已有样片: {target_root}')
    wiring = json.loads(args.wiring.read_text(encoding='utf-8'))['emitted'] if args.wiring else None
    data = (MAC / MAC004_SCRIPT).read_bytes()
    info = json.loads((ROOT / 'MAC_命令表/脚本验证.json').read_text(encoding='utf-8'))[MAC004_SCRIPT]
    table = load_table()
    _, commands = read_entry_zero(data, info['boundary'], table)
    pointer, options = read_choice(data, info, table, commands)
    words = tuple(sorted(set(OPERANDS)
                         | set(collect_operands(load_commands(MAC003_SCRIPT), 0x34B8))
                         | set(collect_operands(load_commands(MAC004_SCRIPT), MAC004_START))))
    check_layout(words)

    branch = compile_range(MAC003_SCRIPT, BRANCH_START, words=words,
                           extra_labels=BRANCH_TARGETS, ext_scene=scene_name)
    if not branch.ext_jumps or branch.stop.name != 'ext_goto':
        raise ValueError(f'分支段末没有按预期写成场景切换: {branch.stop}')
    jump = branch.ext_jumps[0]
    if jump['target_script'] != MAC004_SCRIPT or jump['target_entry'] != MAC004_START:
        raise ValueError(f'ext_goto 目标与预期不符: {jump}')
    if wiring is not None and wiring['MAC_003:0x6790'] != [branch.lines[-1]]:
        raise ValueError('批量生成的跨剧本接线与编译结果不一致')

    opening = compile_range(MAC004_SCRIPT, MAC004_START, end=CHOICE - 1, words=words)
    if opening.stop.offset != CHOICE:
        raise ValueError(f'MAC_004 开头未停在选项: {opening.stop}')
    titles = [line for line in opening.lines if line.startswith('intro:')]
    if len(titles) != 1:
        raise ValueError(f'MAC_004 开头应只有一个章节标题: {titles}')

    branches = []
    for option in options:
        result = compile_range(MAC004_SCRIPT, option['target'], words=words)
        if not result.lines:
            raise ValueError(f'MAC_004 分支 {option["index"]} 没有可生成的内容')
        boundary = (f'本版边界：{result.stop.script} 0x{result.stop.offset:X} '
                    f'{result.stop.name}（{result.stop.category}）。;')
        branches.append({'option': option, 'result': result, 'boundary': boundary})
    scan = scan_blockers(MAC004_SCRIPT, MAC004_START, words=words)

    shutil.copytree(SOURCE, target_root)
    scenes = target_root / 'game/scene'

    prologue = [f"jumpLabel:mac_{target:x} -when=mac_entry=={index};"
                for index, target in enumerate(BRANCH_TARGETS)]
    (scenes / 'mac003_fifth_branches.txt').write_text(
        '\n'.join([*prologue, *branch.lines]) + '\n', encoding='utf-8')

    entries = '|'.join(f"{option['text']}:mac004_choice_{option['index']}" for option in options)
    if wiring is not None:
        opening_lines = [*opening.lines, *wiring['MAC_004:0xA38']]
    else:
        opening_lines = [*opening.lines, f'choose:{entries};']
        for option in options:
            opening_lines.extend([f"label:mac004_choice_{option['index']} -next;",
                                  f"setVar:mac_6007={option['index']} -next;",
                                  f"changeScene:{option['scene']};"])
    (scenes / scene_name(MAC004_SCRIPT, MAC004_START)).write_text(
        '\n'.join(opening_lines) + '\n', encoding='utf-8')

    for entry in branches:
        result = entry['result']
        (scenes / entry['option']['scene']).write_text(
            '\n'.join([*result.lines, entry['boundary'], 'end;']) + '\n', encoding='utf-8')

    start = scenes / 'start.txt'
    text = start.read_text(encoding='utf-8')
    existing = {int(name, 16) for name in re.findall(r'^setVar:mac_([0-9a-f]{4})=0 -next;$', text, re.M)}
    initial = ''.join(f'setVar:mac_{word:04x}=0 -next;\n' for word in words if word not in existing)
    start.write_text(initial + text, encoding='utf-8')

    used = set(branch.used_voices) | set(opening.used_voices)
    for entry in branches:
        used |= set(entry['result'].used_voices)
    for number in sorted(used):
        name = f'VOICE_{number:05}.wav'
        target = target_root / 'game/vocal' / name
        if not target.exists():
            shutil.copy2(VOICE_DIR / name, target)

    config_path = target_root / 'game/config.txt'
    config = config_path.read_text(encoding='utf-8')
    config = config.replace('Game_name:I’s Pure 新游戏第五选项验证;',
                            'Game_name:I’s Pure 新游戏跨剧本验证;')
    game_key = 'ISPstorywiring01' if wiring is not None else 'ISPdynamicmac00401'
    config = config.replace('Game_key:ISPdynamicfifth01;', f'Game_key:{game_key};')
    config_path.write_text(config, encoding='utf-8')

    summary = {
        'scope': '第五组三条分支越过 MAC_003:0x6790 的 ext_goto，在 MAC_004.bin 开头执行，'
                 '到 0xA38 第一组选项并可选入两条分支，各自推进到 0x1AA8 特效边界。',
        'batch_wiring': str(args.wiring) if args.wiring else None,
        'ext_goto': {key: jump[key] for key in ('resource', 'group', 'index', 'target_script',
                                                'target_entry_hex', 'target_header',
                                                'mapping_source', 'effect', 'scene')},
        'mac004': {
            'scene': scene_name(MAC004_SCRIPT, MAC004_START),
            'start': f'0x{MAC004_START:X}',
            'lines': len(opening_lines),
            'voices': len(opening.used_voices),
            'chapter_title': titles[0],
            'progress_bits': [entry for entry in opening.ignored if entry['category'] == 'progress_bit'],
        },
        'choice': {
            'script': MAC004_SCRIPT, 'offset': f'0x{CHOICE:X}', 'count': len(options),
            'table_pointer': f'0x{pointer:X}',
            'result_register': '0x6007（0xA44 先拷到 0x6000，再由 0xA4C/0xA5C 比较）',
            'options': [{key: value for key, value in option.items() if key != 'condition_raw'}
                        | {'condition': f"0x{option['condition_raw']:04X}"} for option in options],
            'visibility_note': '两项条件操作数都是立即数 1，plan_choice 在零状态给出 [0,1]，不按前序隐藏。',
        },
        'branch_scenes': [{
            'option': entry['option']['index'],
            'scene': entry['option']['scene'],
            'start': f"0x{entry['option']['target']:X}",
            'lines': len(entry['result'].lines) + 2,
            'voices': len(entry['result'].used_voices),
            'stop': entry['result'].stop.as_dict(),
        } for entry in branches],
        'mac003_branch_scene': {'scene': 'mac003_fifth_branches.txt',
                                'lines': len(prologue) + len(branch.lines),
                                'voices': len(branch.used_voices),
                                'tail': branch.lines[-1]},
        'mac004_scan': {'blockers': scan['blockers'], 'blocker_total': scan['blocker_total'],
                        'wired': scan['wired'], 'wired_total': scan['wired_total']},
        'tracked_operands': [f'0x{word:04X}' for word in words],
        'limitations': [
            '两条分支都停在 0x1AA8 的 effect_start；后面的 16 处特效与第二组选项 0x2CBC 未接入。',
            '0x17 只置原程序进度位与标题下标，WebGAL 侧不持久化；章节解锁界面也未实现。',
            '画面、音效与淡入淡出仍按 pass_through 记账，没有映射。',
        ],
    }
    (target_root.parent / '生成报告.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n',
                                              encoding='utf-8')
    print('样片:', target_root)
    print('选项:', [(option['text'], f"0x{option['target']:X}") for option in options])
    print('MAC_004 开头:', len(opening_lines), '行', len(opening.used_voices), '条语音', titles[0])
    for entry in branches:
        print('  分支', entry['option']['index'], len(entry['result'].lines) + 2, '行',
              len(entry['result'].used_voices), '条语音', entry['result'].stop.name,
              f"0x{entry['result'].stop.offset:X}")
    print('MAC_004 阻塞:', [(b['category'], b['count']) for b in scan['blockers']],
          '合计', scan['blocker_total'])


if __name__ == '__main__':
    main()
