"""对已识别的 0x72 模式评估选项条件；保留原始表序号。"""
import csv

from mac_state import UnsupportedCommand
from mac_reader import read_entry_zero
import MAC_批量选项分支 as original

# 选项可安全写进 WebGAL 的行内分隔符；含这些字符的译文会被拒绝而不是转义后猜测。
FORBIDDEN_CHARACTERS = ';:|\\\r\n'


def read_options(data, info, table, commands, position, script, translations_path, opcode):
    """把一组选项读成可直接生成场景的清单（生成器共用这一处约定）。

    `opcode` 是该组的 4 字节指令头（例如 `72 03 07 60`），用来确认布局没变；
    文本取自 `translations_path` 里与盘上原文逐字匹配的唯一译文，跳转目标必须是
    命令边界。条件字段原样返回，可见性由 `plan_choice` 另行求值。
    """
    if data[position:position + 4] != opcode:
        raise ValueError(f'{script} 0x{position:X} 的选项指令头有变化')
    starts = {command.offset for command in commands}
    rows = original.inspect(data, position, info['text_start'], starts)
    pointer = int.from_bytes(data[position + 4:position + 8], 'little')
    if pointer + 12 * len(rows) > info['text_start']:
        raise ValueError(f'{script} 0x{position:X} 选项表越界')
    with open(translations_path, encoding='utf-8-sig', newline='') as file:
        translations = {int(row['表内序号']): row for row in csv.DictReader(file, delimiter='\t')
                        if row['脚本'] == script and int(row['选项指令偏移'], 16) == position}
    options = []
    for index, label_original, target, field1, field2 in rows:
        translated = translations.get(index)
        if not translated or translated['匹配状态'] != '唯一匹配':
            raise ValueError(f'{script} 0x{position:X} 第 {index} 项没有唯一匹配的 v7.4 译文')
        if translated['日文原文'] != label_original:
            raise ValueError(f'{script} 0x{position:X} 第 {index} 项的盘上原文与译文表不一致')
        text = translated['汉化包中文']
        if not text or any(char in text for char in FORBIDDEN_CHARACTERS):
            raise ValueError(f'{script} 0x{position:X} 第 {index} 项译文含未处理字符')
        if target not in starts:
            raise ValueError(f'{script} 0x{position:X} 第 {index} 项跳转目标不是命令边界: {target:#x}')
        options.append({'index': index, 'label_original': label_original, 'text': text,
                        'target': target, 'field1': field1, 'field2': field2,
                        'condition_raw': field2 & 0xFFFF})
    return {'rows': rows, 'table_pointer': pointer, 'options': options}


def plan_choice(data, boundary, text_start, position, table, state):
    """解析并求值可见性，不修改状态；遇到不符合已识别模式的内容明确失败。

    状态应由调用者提供，其初值和可靠性不可由此函数推断。
    """
    _, commands = read_entry_zero(data, boundary, table)
    starts = {c.offset for c in commands}
    if not any(c.offset == position and c.opcode == 0x72 for c in commands):
        raise UnsupportedCommand('指定位置不是已识别的 sel_disp4')
    try:
        records = original.inspect(data, position, text_start, starts)
    except (ValueError, UnicodeError, IndexError) as exc:
        raise UnsupportedCommand(f'未识别的选项格式: {exc}') from exc
    options = []
    for index, label, target, field1, field2 in records:
        condition = field2 & 0xFFFF
        value = state.read(condition)
        options.append({'index': index, 'label_original': label, 'target': target,
                        'condition': state.describe(condition), 'condition_value': value,
                        'visible': value != 0, 'field1': field1, 'field2': field2})
    return {'offset': position, 'options': options,
            'visible_indices': [o['index'] for o in options if o['visible']],
            # 0x11AE68–0x11AE78：无可见项时写入原始选项总数。
            'no_visible_result': len(options),
            'note': '保留原表索引；状态初值与 UI 点击行为需由调用方验证。'}
