"""把 MAC_003 第五组选项（0x5A44）接进运行时场景链。

数据来源全部从原始盘读取，不复制猜测值：

- 选项指令 `MAC_003:0x5A44`：数量、选项表指针、结果寄存器拷贝与前四组同一套
  布局，用 `MAC_批量选项分支.inspect` 的既有约定解析；
- 选项文本：`数据/选项v74地址核查.tsv`（表内序号 + 日文原文 + 唯一匹配的译文），
  并与盘上 cp932 文本逐字核对；
- 显示条件：`mac_choice.plan_choice` 按记录 field2 的低 16 位求值；
- 分支目标：选项表里的静态跳转地址，必须是命令边界。

生成物：
`mac003_fifth.txt`（0x34B8→0x5A44 的编译结果 + 第五组选项）与
`mac003_fifth_branches.txt`（0x5A90 起的三条分支共用场景，入口用 `mac_entry` 分派）。
"""
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
from mac_runtime_scene import OPERANDS, collect_operands, compile_range, load_commands, scan_blockers
from mac_state import State
from 验证新游戏首选项 import DATA, MAC, VOICE_DIR

SOURCE = BASE / '历史样片/新游戏动态第四选项/public'
TARGET = BASE / '历史样片/新游戏动态第五选项/public'
SCRIPT = 'MAC_003.bin'
CHOSEN = 0x5A44
RANGE_START = 0x34B8
BRANCH_START = 0x5A90


def load_script():
    data = (MAC / SCRIPT).read_bytes()
    info = json.loads((ROOT / 'MAC_命令表/脚本验证.json').read_text(encoding='utf-8'))[SCRIPT]
    table = load_table()
    _, commands = read_entry_zero(data, info['boundary'], table)
    return data, info, table, commands


def read_choice(data, info, table, commands):
    choice = read_options(data, info, table, commands, CHOSEN, SCRIPT,
                          DATA / '选项v74地址核查.tsv', bytes.fromhex('72030760'))
    return choice['rows'], choice['table_pointer'], choice['options']


def main():
    if TARGET.exists():
        raise FileExistsError(f'拒绝覆盖已有样片: {TARGET}')
    data, info, table, commands = load_script()
    rows, table_pointer, options = read_choice(data, info, table, commands)
    plan = plan_choice(data, info['boundary'], info['text_start'], CHOSEN, table, State())
    if plan['visible_indices'] != [option['index'] for option in options]:
        raise ValueError(f'第五组存在按状态隐藏的选项，需要按路径分别生成: {plan}')
    if [option['target'] for option in options] != [row[2] for row in rows]:
        raise ValueError('分支目标与选项表不一致')

    words = tuple(sorted(set(OPERANDS) | set(collect_operands(load_commands(SCRIPT), RANGE_START))))
    fifth = compile_range(SCRIPT, RANGE_START, end=CHOSEN, words=words)
    if fifth.stop is None or fifth.stop.offset != CHOSEN:
        raise ValueError(f'第五组选项前未按预期停止: {fifth.stop}')

    branch = compile_range(SCRIPT, BRANCH_START, words=words,
                           extra_labels=tuple(option['target'] for option in options))
    if not set(option['target'] for option in options) <= set(branch.labels):
        raise ValueError('分支入口标签未覆盖选项表的三个目标')
    branch_scan = scan_blockers(SCRIPT, BRANCH_START, words=words)
    head_scan = scan_blockers(SCRIPT, RANGE_START, words=words)

    shutil.copytree(SOURCE, TARGET)
    scenes = TARGET / 'game/scene'
    fourth = scenes / 'mac003_to_fourth.txt'
    before = fourth.read_text(encoding='utf-8').splitlines()
    if before[-2:] != ['当前版本到此为止。;', 'end;']:
        raise ValueError('第四组场景的目标格式有变化')
    fourth.write_text('\n'.join([*before[:-2], 'changeScene:mac003_fifth.txt;']) + '\n', encoding='utf-8')

    entries = '|'.join(f"{option['text']}:fifth_{option['index']}" for option in options)
    lines = [*fifth.lines, f'choose:{entries};']
    for option in options:
        lines.extend([f"label:fifth_{option['index']} -next;",
                      f"setVar:mac_6007={option['index']} -next;",
                      f"setVar:mac_entry={option['index']} -next;",
                      'changeScene:mac003_fifth_branches.txt;'])
    (scenes / 'mac003_fifth.txt').write_text('\n'.join(lines) + '\n', encoding='utf-8')

    prologue = []
    for option in options:
        prologue.append(f"jumpLabel:mac_{option['target']:x} -when=mac_entry=={option['index']};")
    stop = branch.stop
    tail = [f'本版边界：{stop.script} 0x{stop.offset:X} {stop.name}（{stop.category}）。;', 'end;']
    (scenes / 'mac003_fifth_branches.txt').write_text(
        '\n'.join([*prologue, *branch.lines, *tail]) + '\n', encoding='utf-8')

    start = scenes / 'start.txt'
    text = start.read_text(encoding='utf-8')
    existing = {int(name, 16) for name in re.findall(r'^setVar:mac_([0-9a-f]{4})=0 -next;$', text, re.M)}
    missing = [word for word in words if word not in existing]
    initial = ''.join(f'setVar:mac_{word:04x}=0 -next;\n' for word in missing)
    # mac_entry 是分支场景开头的分派变量（不是原剧本状态字），也在这里初始化。
    if 'setVar:mac_entry=0 -next;' not in text:
        initial += 'setVar:mac_entry=0 -next;\n'
    start.write_text(initial + text, encoding='utf-8')

    used = set(fifth.used_voices) | set(branch.used_voices)
    for number in sorted(used):
        name = f'VOICE_{number:05}.wav'
        target = TARGET / 'game/vocal' / name
        if not target.exists():
            shutil.copy2(VOICE_DIR / name, target)

    config_path = TARGET / 'game/config.txt'
    config = config_path.read_text(encoding='utf-8')
    config = config.replace('Game_name:I’s Pure 新游戏三选项验证;', 'Game_name:I’s Pure 新游戏第五选项验证;')
    config = config.replace('Game_key:ISPdynamicfourth01;', 'Game_key:ISPdynamicfifth01;')
    config_path.write_text(config, encoding='utf-8')

    summary = {
        'scope': '从新游戏经四组选项走到 MAC_003:0x5A44 第五组选项并可选中进入分支；'
                 '选项表、条件与分支目标均由原盘解析，文本取 v7.4 地址表。',
        'choice': {
            'script': SCRIPT, 'offset': f'0x{CHOSEN:X}', 'count': len(rows),
            'table_pointer': f'0x{table_pointer:X}',
            'result_register': '0x6007（09 00 00 60 07 60 00 00 拷贝到 0x6000 后逐项比较）',
            'options': [{'index': option['index'], 'label_original': option['label_original'],
                         'text': option['text'], 'target': f"0x{option['target']:X}",
                         'condition': f"0x{option['condition_raw']:04X}",
                         'visible': True, 'field1': f"0x{option['field1']:08X}",
                         'field2': f"0x{option['field2']:08X}"} for option in options],
            'visibility_note': '三项的条件操作数都是立即数 1，plan_choice 在零状态下也给出 [0,1,2]，'
                               '所以本组不按前序路径隐藏；若将来出现按状态隐藏的组，需按路径分别生成。'},
        'scenes': {
            'mac003_fifth.txt': {'range': f'0x{RANGE_START:X}→0x{CHOSEN:X}', 'lines': len(lines),
                                 'voices': len(fifth.used_voices)},
            'mac003_fifth_branches.txt': {'range': f'0x{BRANCH_START:X} 起', 'lines': len(branch.lines) + len(prologue) + len(tail),
                                          'voices': len(branch.used_voices),
                                          'labels': [f'0x{offset:X}' for offset in sorted(branch.labels)],
                                          'stop': stop.as_dict()},
            'entry': 'mac_entry 由第五组选项写入 0/1/2，分支场景开头的 jumpLabel 分派到对应原偏移'},
        'blockers': {'fifth_range': head_scan['blockers'], 'branch_range': branch_scan['blockers']},
        'tracked_operands': [f'0x{word:04X}' for word in words],
        'limitations': ['画面、音效、淡入淡出仍是记账而非映射。',
                        f"分支结尾停在 {stop.script} 0x{stop.offset:X} 的 {stop.name}，"
                        '跨剧本目标与后续特效尚未接入。',
                        '原版从新游戏到第五组的完整实机轨迹仍未逐句对照。'],
    }
    (TARGET.parent / '生成报告.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n',
                                              encoding='utf-8')
    print('样片:', TARGET)
    print('第五组选项:', len(rows), '项 →', [f"0x{o['target']:X}" for o in options])
    print('第五场行数:', len(lines), '分支场行数:', len(branch.lines) + len(prologue) + len(tail),
          '停止:', stop.as_dict())
    print('初始化状态字:', len(words), '新增:', len(missing))


if __name__ == '__main__':
    main()
