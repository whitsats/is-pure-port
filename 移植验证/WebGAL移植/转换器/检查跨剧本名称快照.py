"""核查一份 EE 快照的组 0 运行时名称表与原盘 MAC.AFS 名称。"""
import argparse
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile

from mac_progress_snapshot import EE_SIZE, EeMemory, SnapshotError, physical
from mac_title_snapshot import read_null_bytes
import mac_reader  # 将 移植验证/ 加入模块搜索路径
import MAC_解析 as mac
import MAC_命令表提取 as common
import 状态字证据 as evidence

TABLE_POINTER = 0xB1EC4C
COUNT_CANDIDATE = 0xB1EC48


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--savestate', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--limit', type=int, default=45)
    args = p.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    if not 0 <= args.limit <= 4096:
        raise ValueError('核查数量超出资源号索引范围')
    archive = args.savestate.read_bytes()
    with ZipFile(args.savestate) as z:
        source = z.read('eeMemory.bin')
    if len(source) != EE_SIZE:
        raise SnapshotError('EE 内存大小不符')
    elf = common.ELF.read_bytes()
    segs = evidence.segments(elf)
    for address, size in ((0x12D850, 0x10), (0x12D8F8, 0x20)):
        offset = evidence.vaddr_to_offset(segs, address, size)
        if source[address:address + size] != elf[offset:offset + size]:
            raise ValueError(f'加载器与 ELF 不符: {address:#x}')
    memory = EeMemory(bytearray(source))
    table = memory.u32(TABLE_POINTER)
    if not table:
        raise SnapshotError('名称表指针为空')
    physical(table, args.limit * 4)
    entries = mac.entries(mac.load())
    if len(entries) < args.limit:
        raise ValueError('原盘归档条目不足')
    rows = []
    for index in range(args.limit):
        ptr = memory.u32(table + index * 4)
        raw = read_null_bytes(memory, ptr, 128)
        name = raw.decode('ascii')
        expected = entries[index]['name']
        rows.append({'index': index, 'memory_name': name, 'afs_name': expected,
                     'matches': name.upper() + '.BIP' == expected.upper(),
                     'string_pointer': f'0x{ptr:08X}'})
    payload = {'savestate_sha256': hashlib.sha256(archive).hexdigest(),
               'elf_sha256': hashlib.sha256(elf).hexdigest(),
               'table_pointer_address': f'0x{TABLE_POINTER:08X}',
               'table_pointer': f'0x{table:08X}',
               'adjacent_count_candidate': memory.u32(COUNT_CANDIDATE),
               'checked': len(rows), 'matches': sum(r['matches'] for r in rows), 'entries': rows,
               'scope': '只核查这一时刻的名称表与原盘 AFS 条目顺序；相邻数值含义、其他存档和动态变化未证实。'}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write('\n')
    print('checked', payload['checked'], 'matched', payload['matches'], 'count candidate', payload['adjacent_count_candidate'])
    print('Output:', args.output)


if __name__ == '__main__':
    main()
