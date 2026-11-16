"""Rebase compiled sample strings onto matching disc-build source records."""
import argparse
from collections import Counter, defaultdict
import csv
import json
from pathlib import Path
import re
import shutil
import sys

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE / '转换器'))
from mac_release import DIALOGUE_DATA, DISC_DIALOGUE, ENGINEERING_DIALOGUE

SOURCE = BASE / '历史样片/新游戏岸边告白接续/public'
TARGET = BASE / '新游戏打盘版/public'
DIALOGUE = re.compile(r'(.*?)( -VOICE_([0-9]+)\.wav)?;')


def read_rows(path):
    with path.open(encoding='utf-8-sig', newline='') as file:
        return {(row['剧本'], int(row['指令偏移'], 16)): row for row in csv.DictReader(file, delimiter='\t')
                if row['剧本'] <= 'MAC_007.bin'}


def dialogue_pairs(sample):
    old, disc = read_rows(ENGINEERING_DIALOGUE), read_rows(DISC_DIALOGUE)
    pairs = defaultdict(set)
    for address, previous in old.items():
        if not previous['v7.4中文']:
            continue
        key = (previous['v7.4中文'], int(previous['语音号']))
        current = disc.get(address)
        if (current and current['日文原文'] == previous['日文原文']
                and current['语音号'] == previous['语音号'] and current['中文（原对照表）']):
            pairs[key].add((current['中文（原对照表）'], current['译文来源']))
        else:
            pairs[key].add((None, '待核'))
    approved_report = sample.parent / '生成报告.json'
    if approved_report.exists():
        approved = json.loads(approved_report.read_text(encoding='utf-8'))
        for field, script in (('split_dialogue', 'MAC_006.bin'), ('archive_dialogue', 'MAC_007.bin')):
            patch = approved.get(field)
            if patch:
                current = disc[script, int(patch['instruction'], 16)]
                if current['译文来源'] == 'v7.4 打盘归档':
                    key = (patch['used_text'], int(current['语音号']))
                    pairs[key].add((current['中文（原对照表）'], current['译文来源']))
    return pairs


def options(line):
    for entry in line.removeprefix('choose:').removesuffix(';').split('|'):
        prefix, label = entry.rsplit(':', 1)
        condition, arrow, text = prefix.rpartition('->')
        yield condition + arrow, text, label


def option_pairs():
    old = json.loads((DIALOGUE_DATA / '全盘主线接线.json').read_text(encoding='utf-8'))['emitted']
    disc = json.loads((DIALOGUE_DATA / '全盘主线接线_打盘版.json').read_text(encoding='utf-8'))['emitted']
    pairs = defaultdict(set)
    for site, commands in old.items():
        if site.split(':', 1)[0] > 'MAC_007':
            continue
        before = next((line for line in commands if line.startswith('choose:')), None)
        if before is None:
            continue
        after = next(line for line in disc[site] if line.startswith('choose:'))
        left, right = list(options(before)), list(options(after))
        if [(condition, label) for condition, _, label in left] != [(condition, label) for condition, _, label in right]:
            raise ValueError(f'{site} 选项控制结构有变化')
        pairs[tuple(text for _, text, _ in left)].add(tuple(text for _, text, _ in right))
    return pairs


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, default=SOURCE)
    parser.add_argument('--output', type=Path, default=TARGET)
    args = parser.parse_args()
    summary = args.output.parent / '切换报告.json'
    if args.output.exists() or summary.exists():
        raise FileExistsError('样片或报告已经存在')
    dialogue, choices = dialogue_pairs(args.source), option_pairs()
    counts, examples = Counter(), defaultdict(list)
    scenes = {}
    for source in sorted((args.source / 'game/scene').glob('*.txt')):
        if source.name.startswith(('demo_', 'function_')):
            continue
        text = source.read_text(encoding='utf-8')
        lines = []
        for line in text.splitlines():
            updated = line
            if line.startswith('choose:'):
                entries = list(options(line))
                variants = choices[tuple(text for _, text, _ in entries)]
                if len(variants) == 1:
                    labels = next(iter(variants))
                    updated = 'choose:' + '|'.join(f'{condition}{text}:{label}' for (condition, _, label), text
                                                   in zip(entries, labels, strict=True)) + ';'
                    counts['已核对选项组'] += 1
                    counts['已替换选项组'] += int(updated != line)
                else:
                    counts['待复核选项组'] += 1
                    examples['待复核选项组'].append({'scene': source.name, 'line': line})
            else:
                match = DIALOGUE.fullmatch(line)
                if match and ':' not in match[1]:
                    key = (match[1], int(match[3]) if match[3] else -1)
                    variants = dialogue[key]
                    texts = {text for text, _ in variants}
                    if len(texts) == 1 and None not in texts:
                        updated = f'{next(iter(texts))}{match[2] or ""};'
                        category = ('盘内归档对白' if all(origin == 'v7.4 打盘归档' for _, origin in variants)
                                    else '工程回退对白')
                        counts[category] += 1
                        counts['已替换对白'] += int(updated != line)
                    else:
                        counts['保留原样的行'] += 1
                        if len(examples['保留原样的行']) < 30:
                            examples['保留原样的行'].append({'scene': source.name, 'line': line})
            lines.append(updated)
        scenes[source.name] = '\n'.join(lines) + ('\n' if text.endswith('\n') else '')

    shutil.copytree(args.source, args.output)
    for name, text in scenes.items():
        (args.output / 'game/scene' / name).write_text(text, encoding='utf-8')
    config = args.output / 'game/config.txt'
    config.write_text(re.sub(r'^Game_key:[^;]*;', 'Game_key:ISPv74Disc01;',
                             config.read_text(encoding='utf-8'), flags=re.M), encoding='utf-8')
    with summary.open('x', encoding='utf-8') as file:
        json.dump({'source': str(args.source), 'counts': dict(counts), 'examples': dict(examples)},
                  file, ensure_ascii=False, indent=2)
        file.write('\n')
    print(dict(counts))


if __name__ == '__main__':
    main()
