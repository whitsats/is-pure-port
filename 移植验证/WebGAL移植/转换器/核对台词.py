"""将入口片段的 msg_disp2 与已有对照表按行号及日文原文核验。"""
import csv
import json
import struct
from pathlib import Path

from mac_reader import ROOT
import MAC_解析 as mac

BASE = Path(__file__).resolve().parents[1]
IR = BASE / '数据/入口片段.json'
OUT = BASE / '数据/台词对应核查.tsv'


def main():
    if OUT.exists():
        raise FileExistsError(OUT)
    scripts = json.loads(IR.read_text(encoding='utf-8'))['scripts']
    names = {f"MAC_{entry['i']:03}.bin": entry for entry in mac.entries(mac.load())}
    results = []
    for script in scripts:
        name = script['file']
        item = names[name]
        translations = ROOT / 'MAC_文本语音' / f"{item['i']:02}_{item['name']}.tsv"
        if not translations.exists():
            continue
        with translations.open(encoding='utf-8-sig', newline='') as f:
            rows = list(csv.DictReader(f, delimiter='\t'))
        by_line = {}
        for row in rows:
            by_line.setdefault(int(row['行号']), []).append(row)
        raw_script = (ROOT / '输出-保护边修复/MAC' / name).read_bytes()
        for cmd in script['commands']:
            if cmd['opcode'] != 0x60:
                continue
            raw = bytes.fromhex(cmd['raw_hex'])
            if len(raw) != 12:
                raise ValueError(f'{name}: 非预期的 msg_disp2 长度')
            ptr, line, voice = struct.unpack_from('<IHH', raw, 4)
            if not 0 < ptr < len(raw_script):
                raise ValueError(f'{name}: 文本地址越界 {ptr:#x}')
            end = raw_script.find(b'\x00', ptr)
            if end < 0:
                raise ValueError(f'{name}: 文本没有结束符 {ptr:#x}')
            japanese = raw_script[ptr:end].decode('cp932')
            matches = [r for r in by_line.get(line, []) if r['日文'] == japanese
                       and int(r['语音号']) == (-1 if voice == 0xFFFF else voice)]
            status = '唯一匹配' if len(matches) == 1 else ('无匹配' if not matches else '重复匹配')
            chinese = matches[0]['中文'] if len(matches) == 1 else ''
            results.append([name, f"0x{cmd['offset']:06X}", line,
                            -1 if voice == 0xFFFF else voice, status, japanese, chinese])
    with OUT.open('x', encoding='utf-8-sig', newline='') as f:
        writer = csv.writer(f, delimiter='\t')
        writer.writerow(['剧本', '指令偏移', '行号', '语音号', '匹配状态', '日文', '中文（原对照表）'])
        writer.writerows(results)
    print('台词', len(results), '唯一匹配', sum(row[4] == '唯一匹配' for row in results),
          '唯一匹配且有中文', sum(row[4] == '唯一匹配' and bool(row[6]) for row in results))
    print('结果:', OUT)


if __name__ == '__main__':
    main()
