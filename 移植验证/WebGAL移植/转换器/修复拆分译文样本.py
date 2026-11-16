"""按原文、地址核验并合并 MAC_001 的一条拆分译文。"""
import csv
from pathlib import Path
import sys

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / '转换器'))
from 匹配汉化包选项 import read_patch


def main():
    source = BASE / '数据/台词v74原始工程核查.tsv'
    output = BASE / '数据/台词v74原始工程核查_拆分修复.tsv'
    from 本地路径 import V74_RELEASE
    patch = V74_RELEASE / '补丁/IS01/IS01_2.BIP.bin.txt'
    if output.exists():
        raise FileExistsError(output)
    fragments = read_patch(patch)
    pairs = []
    for address in (0x7D3A, 0x7D4C, 0x7D50):
        if len(fragments.get(address, [])) != 1:
            raise ValueError(f'片段地址不唯一: {address:#x}')
        pairs.append(fragments[address][0])
    with source.open(encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f, delimiter='\t')
        columns, rows = reader.fieldnames, list(reader)
    matches = [r for r in rows if r['剧本'] == 'MAC_001.bin' and r['指令偏移'] == '0x001134']
    if len(matches) != 1:
        raise ValueError('目标指令不唯一')
    row = matches[0]
    expected = row['日文原文'].replace('%K', '').replace('%P', '').replace('・', '')
    if ''.join(x[0] for x in pairs) != expected:
        raise ValueError('拼接日文与原文不一致')
    row['v7.4中文'] = ''.join(x[1] for x in pairs)
    row['匹配状态'] = '工程与地址匹配'
    with output.open('x', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=columns, delimiter='\t')
        writer.writeheader()
        writer.writerows(rows)
    print('已核对拆分译文:', row['v7.4中文'])
    print('输出:', output)


if __name__ == '__main__':
    main()
