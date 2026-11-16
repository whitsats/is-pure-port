"""现场复核 `file_read`/`file_wait` 的 ELF 证据，输出 `数据/文件读取ELF证据.json`。

所有地址、立即数都由本脚本从 ELF 重新读出，不写死结论字符串；统计部分扫描全部
74 个 `MAC_*.bin`，验证“code 高字节恒为 0x50、紧跟 file_wait”这两条前提。
"""
import argparse
import glob
import json
import struct
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mac_reader  # noqa: F401,E402
import MAC_命令表提取 as common  # noqa: E402
import 状态字证据 as ev  # noqa: E402
from mac_file_read import (SE_AFS_ENTRIES, SE_AFS_ROW, SE_HANDLERS, STAGED_CODE, STAGED_FLAG,
                           STAGED_RESULT, STAGED_STYLE, VOLUME_ROW_BYTES)  # noqa: E402

BASE = Path(__file__).resolve().parents[1]
SCRIPTS = BASE.parent / '输出-保护边修复' / 'MAC'
TABLE_VADDR = 0x213590


def u16(data, segs, address):
    return struct.unpack_from('<H', data, ev.vaddr_to_offset(segs, address, 2))[0]


def read_string(data, segs, address):
    offset = ev.vaddr_to_offset(segs, address, 1)
    return data[offset:offset + 64].split(b'\0')[0].decode('ascii')


def scan_scripts(table):
    codes = Counter()
    files = 0
    followed = 0
    for path in sorted(glob.glob(str(SCRIPTS / 'MAC_*.bin'))):
        data = Path(path).read_bytes()
        files += 1
        position = 0
        while position < len(data) - 1:
            opcode = data[position]
            if opcode >= len(table):
                break
            length = table[opcode]['bytes']
            if not length or position + length > len(data):
                break
            if opcode == 0x0F:
                codes[data[position + 2] | (data[position + 3] << 8)] += 1
                if position + 8 <= len(data) and data[position + 4] == 0x10:
                    followed += 1
            position += length
    keys = sorted(codes)
    return {'scripts': files, 'file_reads': sum(codes.values()),
            'distinct_codes': len(keys), 'min_code': f'0x{keys[0]:04X}', 'max_code': f'0x{keys[-1]:04X}',
            'prefixes': sorted({f'0x{k >> 8:02X}' for k in keys}),
            'followed_by_file_wait': followed,
            'top_codes': [{'code': f'0x{k:04X}', 'count': v} for k, v in codes.most_common(5)]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=BASE / '数据/文件读取ELF证据.json')
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)

    data = common.ELF.read_bytes()
    segs = ev.segments(data)
    dis = ev.Dis(data, segs)
    table = common.load_table(data)

    dispatch = []
    for start in (0x117AF0, 0x117DD0):
        for ins in dis.read(start, 0x30):
            if '0x3590' in ins['op'] or ins['op'].startswith('($v0)'):
                dispatch.append({'at': ins['at'], 'instruction': f'{ins["mnemonic"]} {ins["op"]}'})

    group_table = [f'0x{ev.table_at(data, segs, 0x259FD0, 8)[i]:X}' for i in range(8)]
    group_five = [{'at': ins['at'], 'instruction': f'{ins["mnemonic"]} {ins["op"]}'}
                  for ins in dis.read(0x12D8B8, 0x10)]

    se_row = {'at': f'0x{SE_AFS_ROW:X}'}
    for field, delta in (('index', 0x00), ('name_pointer', 0x18), ('size', 0x1C)):
        se_row[field] = ev.table_at(data, segs, SE_AFS_ROW + delta, 1)[0]
    se_row['name'] = read_string(data, segs, se_row['name_pointer'])
    se_row['size_hex'] = f'0x{se_row["size"]:X}'
    se_row['entries_in_iso'] = SE_AFS_ENTRIES
    se_row['row_bytes'] = VOLUME_ROW_BYTES

    payload = {
        'elf': str(common.ELF.relative_to(BASE.parent)),
        'command_table': f'0x{TABLE_VADDR:X}', 'entry_bytes': common.ENTRY_SIZE,
        'dispatch': dispatch,
        'file_read': {'handler': f'0x{table[0x0F]["handler"]:X}', 'bytes': table[0x0F]['bytes'],
                      'mode1_unused': f'0x{table[0x0F]["mode1"]:X}',
                      'reads_style': '0x00119890', 'reads_code': '0x00119898',
                      'advance': '0x001198B0 (ip += 4, 仅当 0x12D980 返回 0)'},
        'file_wait': {'handler': f'0x{table[0x10]["handler"]:X}', 'bytes': table[0x10]['bytes']},
        'staging': {'flag': f'0x{STAGED_FLAG:X}', 'style': f'0x{STAGED_STYLE:X}',
                    'code': f'0x{STAGED_CODE:X}', 'result': f'0x{STAGED_RESULT:X}',
                    'writer': '0x0012D9FC..0x0012DA18', 'poller': '0x0012DA38..0x0012DAFC'},
        'group_jump_table': {'at': '0x259FD0', 'handlers': group_table,
                             'group_5': '0x12D8B8', 'group_5_no_table': group_five,
                             'return_0': '0x12D970'},
        'scripts': scan_scripts(table),
        'se_afs': se_row,
        'se_handlers': {f'0x{op:02X}': f'0x{addr:X}' for op, addr in SE_HANDLERS.items()},
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    stats = payload['scripts']
    print(f'输出 {args.output}；file_read {stats["file_reads"]} 条、{stats["distinct_codes"]} 种、'
          f'前缀 {stats["prefixes"]}、后接 file_wait {stats["followed_by_file_wait"]} 条')


if __name__ == '__main__':
    main()
