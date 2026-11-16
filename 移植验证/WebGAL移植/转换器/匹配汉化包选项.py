"""以原始文本地址和日文原文严格匹配 v7 汉化包中的选项翻译。"""
import csv
import argparse
from pathlib import Path
import re

from mac_reader import ROOT
import MAC_解析 as mac
from 本地路径 import ZH_ROOT

BASE = Path(__file__).resolve().parents[1]
PATCH = ZH_ROOT / '_archive/汉化旧版/汉化包-v7/最终汉化结果-20261113-v7/补丁'
SOURCE = ROOT / 'MAC_命令表/选项文本_原文.tsv'
OUTPUT = BASE / '数据/选项中文地址核查.tsv'
BLOCK = re.compile(r'^No\.\d+\s*\n([0-9A-Fa-f]{8}),\d+\s*\n－+\s*\n(.*?)\n－+\s*\n(.*?)\n－+', re.M | re.S)


def read_patch(path):
    records = {}
    for match in BLOCK.finditer(path.read_text(encoding='utf-16')):
        address = int(match.group(1), 16)
        records.setdefault(address, []).append((match.group(2).strip(), match.group(3).strip()))
    return records


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--patch', type=Path, default=PATCH)
    parser.add_argument('--output', type=Path, default=OUTPUT)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    files = {}
    for path in args.patch.rglob('*.BIP.bin.txt'):
        key = path.name[:-len('.bin.txt')].lower()
        if key in files:
            raise ValueError(f'汉化文件名不唯一: {key}')
        files[key] = path
    names = {f"MAC_{e['i']:03}.bin": e['name'].lower() for e in mac.entries(mac.load())}
    with SOURCE.open(encoding='utf-8-sig', newline='') as f:
        source = list(csv.DictReader(f, delimiter='\t'))
    cache, output = {}, []
    for row in source:
        name = names[row['脚本']]
        path = files.get(name)
        address = int(row['文本偏移'], 16)
        if path and name not in cache:
            cache[name] = read_patch(path)
        candidates = cache.get(name, {}).get(address, [])
        matched = [translated for original, translated in candidates if original == row['日文原文']]
        status = ('唯一匹配' if len(matched) == 1 else '地址或原文不匹配' if not matched else '重复匹配')
        output.append([row['脚本'], name, row['指令偏移'], row['表内序号'], row['文本偏移'],
                       row['日文原文'], matched[0] if len(matched) == 1 else '', status])
    with args.output.open('x', encoding='utf-8-sig', newline='') as f:
        w = csv.writer(f, delimiter='\t')
        w.writerow(['脚本', '原剧本名', '选项指令偏移', '表内序号', '文本偏移', '日文原文', '汉化包中文', '匹配状态'])
        w.writerows(output)
    print('选项:', len(output), '地址和原文唯一匹配:', sum(r[-1] == '唯一匹配' for r in output),
          '其中中文非空:', sum(r[-1] == '唯一匹配' and bool(r[-2]) for r in output))
    print('输出:', args.output)


if __name__ == '__main__':
    main()
