"""统计线性片段中相邻 msg_disp2，不把相邻字节当作完整控制流。"""
import csv
import json
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
OUT = BASE / '数据/连续台词片段清单.tsv'


def read_tsv(name):
    with (BASE / '数据' / name).open(encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f, delimiter='\t'))


def main():
    if OUT.exists():
        raise FileExistsError(OUT)
    scripts = json.loads((BASE / '数据/入口片段.json').read_text(encoding='utf-8'))['scripts']
    disk = read_tsv('三版译文与汉化盘核查.tsv')
    indexed = {(r['剧本'], int(r['指令偏移'], 16)): r for r in disk}
    if len(indexed) != len(disk):
        raise ValueError('盘内译文表有重复位置')
    rows = []
    for script in scripts:
        commands = script['commands']
        i = 0
        while i < len(commands):
            if commands[i]['opcode'] != 0x60:
                i += 1
                continue
            start = i
            while i < len(commands) and commands[i]['opcode'] == 0x60:
                i += 1
            group = commands[start:i]
            verified = 0
            for item in group:
                match = indexed.get((script['file'], item['offset']), {})
                verified += any(match.get(k) == '逐字节一致' for k in ('v7.4工程文本对盘', '汇总文本对盘', 'v7工程文本对盘'))
            following = commands[i] if i < len(commands) else None
            rows.append([script['file'], f"0x{group[0]['offset']:06X}", f"0x{group[-1]['offset']:06X}",
                         len(group), verified, f"0x{following['offset']:06X}" if following else '',
                         following['name'] if following else '入口片段结束'])
    with OUT.open('x', encoding='utf-8-sig', newline='') as f:
        writer = csv.writer(f, delimiter='\t')
        writer.writerow(['剧本', '首条偏移', '末条偏移', '台词数', '与所核验汉化盘一致的译文数', '后继偏移', '后继指令'])
        writer.writerows(rows)
    print('片段:', len(rows), '指令:', sum(x[3] for x in rows),
          '整段译文已核验:', sum(x[3] == x[4] for x in rows), '输出:', OUT)


if __name__ == '__main__':
    main()
