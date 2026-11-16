"""把真实选项的静态候选分支做成可点击的核查场景，不冒充剧情移植。"""
import argparse
import csv
import json
from pathlib import Path

from mac_reader import ROOT, load_table, read_entry_zero
import MAC_批量选项分支 as original


def build_choice(data, boundary, text_start, position, table, translations=None):
    _, commands = read_entry_zero(data, boundary, table)
    starts = {c.offset for c in commands}
    matches = [c for c in commands if c.offset == position and c.opcode == 0x72]
    if len(matches) != 1:
        raise ValueError('选项偏移不是已解析的 sel_disp4')
    records = original.inspect(data, position, text_start, starts)
    labels = {}
    for index, label, target, field1, field2 in records:
        if field2 & 0xFFFF != 1:
            raise ValueError(f'第 {index} 条选项依赖状态，未处理')
        if translations is not None:
            translated = translations.get(index)
            if not translated or translated['匹配状态'] != '唯一匹配' or translated['日文原文'] != label or not translated['汉化包中文']:
                raise ValueError(f'第 {index} 条选项没有严格匹配的汉化文本')
            label = translated['汉化包中文']
        if any(char in label for char in ';:|\\\r\n'):
            raise ValueError('选项含未处理特殊字符')
        labels[index] = label
    entries = '|'.join(f'{labels[index]}:choice_{index}' for index, *_ in records)
    lines = ['这是原游戏选项的静态分支核查，目标对应关系仍待原游戏验证。;', f'choose:{entries};']
    for index, label, target, _, _ in records:
        lines += [f'label:choice_{index};', f'假设返回值 {index}，静态跳转目标 0x{target:06X}。;', 'jumpLabel:done;']
    lines += ['label:done;', '核查结束。;']
    return '\n'.join(lines) + '\n', records


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--script', required=True)
    parser.add_argument('--offset', type=lambda n: int(n, 0), required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--translations', type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    checks = json.loads((ROOT / 'MAC_命令表/脚本验证.json').read_text(encoding='utf-8'))
    info = checks[args.script]
    if info['status'] != 'ok':
        raise ValueError('剧本未通过已有结构检查')
    data = (ROOT / '输出-保护边修复/MAC' / args.script).read_bytes()
    translations = None
    if args.translations:
        with args.translations.open(encoding='utf-8-sig', newline='') as f:
            selected = [r for r in csv.DictReader(f, delimiter='\t')
                        if r['脚本'] == args.script and int(r['选项指令偏移'], 16) == args.offset]
        translations = {int(row['表内序号']): row for row in selected}
        if len(translations) != len(selected):
            raise ValueError('选项翻译序号不唯一')
    text, records = build_choice(data, info['boundary'], info['text_start'], args.offset, load_table(), translations)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8', newline='\n') as f:
        f.write(text)
    print('已生成选项核查场景:', [(n, label, hex(target)) for n, label, target, _, _ in records])


if __name__ == '__main__':
    main()
