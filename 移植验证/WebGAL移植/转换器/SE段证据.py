"""现场复核 SE 段的 ELF 证据与全盘分布，输出 `数据/SE段ELF证据.json`。

两部分：
1. ELF：各 `se_*` 的 handler、通道结构基址/字段偏移、两张运行时表的写者与装载来源；
2. 剧本：74 个 `MAC_*.bin` 里 `0x3A/0x3C/0x3D/0x3E/0x3F` 的出现次数、通道与参数分布、
   `se_set` 对应的 staging 样本号，以及“file_read → file_wait → 五连 SE”这一形态的次数。
"""
import argparse
import glob
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mac_reader  # noqa: F401,E402
import MAC_命令表提取 as common  # noqa: E402
import 状态字证据 as ev  # noqa: E402
from mac_se import (CHANNEL_BASE, CHANNEL_BYTES, CHANNEL_FIELDS, HANDLERS, MODULE_LOAD,
                    SE_REQ, SE_SET, SE_SPEED, SE_VOL, SE_WAIT, STAGED_CODE, TABLE_WRITERS)  # noqa: E402

BASE = Path(__file__).resolve().parents[1]
SCRIPTS = BASE.parent / '输出-保护边修复' / 'MAC'


def scan_scripts(table):
    counts = Counter()
    channels = Counter()
    speeds = Counter()
    volumes = Counter()
    requests = Counter()
    waits = Counter()
    staged = Counter()
    blocks = 0
    files = 0
    for path in sorted(glob.glob(str(SCRIPTS / 'MAC_*.bin'))):
        data = Path(path).read_bytes()
        files += 1
        position = 0
        last_staged = None
        recent = []
        while position < len(data) - 1:
            opcode = data[position]
            if opcode >= len(table):
                break
            length = table[opcode]['bytes']
            if not length or position + length > len(data):
                break
            raw = data[position:position + length]
            if opcode == 0x0F:
                last_staged = raw[2] | (raw[3] << 8)
            if opcode in (SE_SET, SE_REQ, SE_WAIT, SE_SPEED, SE_VOL):
                counts[opcode] += 1
                channels[raw[1]] += 1
                value = raw[2] | (raw[3] << 8)
                {SE_SPEED: speeds, SE_VOL: volumes, SE_REQ: requests,
                 SE_WAIT: waits}.get(opcode, Counter())[value] += 1
                if opcode == SE_SET and last_staged is not None:
                    staged[last_staged] += 1
                recent.append(opcode)
                if len(recent) > 5:
                    recent.pop(0)
                if recent == [SE_SPEED, SE_VOL, SE_SET, SE_REQ, SE_WAIT]:
                    blocks += 1
            position += length
    def top(counter, limit=6):
        return [{'value': (f'0x{v:02X}' if isinstance(v, int) else v), 'count': c}
                for v, c in counter.most_common(limit)]
    return {'scripts': files, 'total': sum(counts.values()),
            'per_opcode': {f'0x{op:02X}': counts[op] for op in (SE_SPEED, SE_VOL, SE_SET, SE_REQ, SE_WAIT)},
            'channels': top(channels), 'speeds': top(speeds), 'volumes': top(volumes),
            'requests': top(requests), 'waits': top(waits),
            'staged_codes': top(staged, 8), 'five_instruction_blocks': blocks}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=BASE / '数据/SE段ELF证据.json')
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    data = common.ELF.read_bytes()
    segs = ev.segments(data)
    dis = ev.Dis(data, segs)
    table = common.load_table(data)
    handlers = {}
    for opcode, address in HANDLERS.items():
        reads = [{'at': ins['at'], 'instruction': f'{ins["mnemonic"]} {ins["op"]}'}
                 for ins in dis.read(address, 0x60)
                 if ins['mnemonic'] in ('lbu', 'lhu', 'sh', 'sb', 'jal')
                 and ('($v1)' in ins['op'] or '($a3)' in ins['op'] or '($s0)' in ins['op']
                      or ins['mnemonic'] == 'jal')][:6]
        handlers[f'0x{opcode:02X}'] = {'name': table[opcode]['name'],
                                       'handler': f'0x{address:X}', 'bytes': table[opcode]['bytes'],
                                       'first_reads': reads}
    payload = {
        'elf': str(common.ELF.relative_to(BASE.parent)),
        'channel': {'base': f'0x{CHANNEL_BASE:X}', 'bytes': CHANNEL_BYTES,
                    'fields': {k: f'0x{v:X}' for k, v in CHANNEL_FIELDS.items()}},
        'staged_code': f'0x{STAGED_CODE:X}',
        'table_writers': TABLE_WRITERS, 'module_load': MODULE_LOAD,
        'handlers': handlers,
        'scripts': scan_scripts(table),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    stats = payload['scripts']
    print(f'输出 {args.output}；SE 指令 {stats["total"]} 条 / {stats["scripts"]} 个剧本，'
          f'五连块 {stats["five_instruction_blocks"]} 次')


if __name__ == '__main__':
    main()
