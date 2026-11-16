"""重新标注显然是纯控制码的候选文本；不推断其完整运行语义。"""
import csv
import re
from collections import Counter
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
SOURCE = BASE / '数据/台词对应核查.tsv'
OUTPUT = BASE / '数据/台词及控制码核查.tsv'


def main():
    if OUTPUT.exists():
        raise FileExistsError(OUTPUT)
    with SOURCE.open(encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f, delimiter='\t')
        fields = reader.fieldnames
        rows = list(reader)
    counts = Counter()
    for row in rows:
        special = (row['行号'] == '65535' and row['语音号'] == '-1'
                   and re.fullmatch(r'(?:%[NnPp])+', row['日文']) is not None)
        row['内容分类'] = '纯控制码候选' if special else '其他文本'
        counts[row['内容分类']] += 1
    with OUTPUT.open('x', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fields + ['内容分类'], delimiter='\t')
        writer.writeheader()
        writer.writerows(rows)
    print('分类:', dict(counts), '输出:', OUTPUT)


if __name__ == '__main__':
    main()
