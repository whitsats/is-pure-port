"""对比 v7 原始对照和现有汇总表，保留两份译文，不自动判定最终版本。"""
import csv
import argparse
from collections import Counter
from pathlib import Path

BASE = Path(__file__).resolve().parents[1] / '数据'


def read(name):
    with (BASE / name).open(encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f, delimiter='\t'))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', default='台词中文地址核查_去尾控制符.tsv')
    parser.add_argument('--output', type=Path, default=BASE / '中文来源差异.tsv')
    args = parser.parse_args()
    output = args.output
    if output.exists():
        raise FileExistsError(output)
    prior = read('台词对应核查.tsv')
    keyed = {(r['剧本'], r['指令偏移']): r for r in prior}
    if len(keyed) != len(prior):
        raise ValueError('汇总表存在重复的剧本/指令偏移')
    results = []
    counts = Counter()
    for row in read(args.source):
        if row['匹配状态'] != '唯一匹配':
            continue
        key = (row['剧本'], row['指令偏移'])
        other = keyed.get(key)
        existing = other['中文（原对照表）'] if other else ''
        kind = '汇总表无中文' if not existing else '一致' if row['汉化包中文'] == existing else '不同'
        counts[kind] += 1
        if kind != '一致':
            results.append([*key, row['文本偏移'], kind, row['日文原文'], row['汉化包中文'], existing])
    with output.open('x', encoding='utf-8-sig', newline='') as f:
        w = csv.writer(f, delimiter='\t')
        w.writerow(['剧本', '指令偏移', '文本偏移', '状态', '原日文', 'v7汉化包对照中文', '现有汇总中文'])
        w.writerows(results)
    print('对比统计:', dict(counts), '差异清单:', output)


if __name__ == '__main__':
    main()
