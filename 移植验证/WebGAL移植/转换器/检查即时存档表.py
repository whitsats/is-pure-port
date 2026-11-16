"""只读检查用户现有 PCSX2 即时存档，单独保存汇总，不更改存档。"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
from zipfile import ZipFile

from mac_progress_snapshot import (EeMemory, EE_SIZE, SCENE_FLAGS, SCENE_TABLE_COUNT,
                                   SCENE_TABLE_PTR, STORY_COUNT, VISITED_BITS,
                                   physical, read_state_base, simulate_reg17)
from mac_reader import ROOT  # 初始化既有解析模块路径
import MAC_命令表提取 as common


def elf_gp(data):
    header = struct.unpack_from('<16sHHIIIIIHHHHHH', data)
    if header[0][:6] != b'\x7fELF\x01\x01':
        raise ValueError('不是预期的 32 位小端 ELF')
    for i in range(header[10]):
        kind, off, _, _, size, _, _, _ = struct.unpack_from('<8I', data, header[5] + i * header[9])
        if kind == 0x70000000 and size >= 24:
            return struct.unpack_from('<I', data, off + 20)[0]
    raise ValueError('ELF 没有预期的 MIPS REGINFO')


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--savestate', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--operand', type=lambda n: int(n, 0), default=1)
    args = p.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    saved_bytes = args.savestate.read_bytes()
    with ZipFile(args.savestate) as archive:
        info = archive.getinfo('eeMemory.bin')
        if info.file_size != EE_SIZE:
            raise ValueError('即时存档的 EE 内存大小不符')
        source = archive.read(info)
    gp = elf_gp(common.ELF.read_bytes())
    before = EeMemory(bytearray(source))
    state = read_state_base(before, gp)
    count = before.u32(STORY_COUNT)
    if count > 0x10000:
        raise ValueError('快照中的剧本计数超出保守上限')
    table_ptr = before.u32(SCENE_TABLE_PTR)
    table_count = before.u32(SCENE_TABLE_COUNT)
    if table_count > 0x10000:
        raise ValueError('快照中的场景表计数超出保守上限')
    if table_count:
        physical(table_ptr, table_count * 12)
    result = simulate_reg17(EeMemory(bytearray(source)), gp, args.operand)
    payload = {
        'savestate': str(args.savestate), 'savestate_sha256': hashlib.sha256(saved_bytes).hexdigest(),
        'elf_sha256': hashlib.sha256(common.ELF.read_bytes()).hexdigest(),
        'gp': f'0x{gp:08X}', 'state_base': f'0x{state:08X}',
        'state_before': {'script_number': before.u16(state + 0x440), 'prior_bit': before.u32(state + 0x4B0),
                         'current_resource': before.u32(state + 0x52E0)},
        'story_count': count, 'visited_bits_prefix_hex': source[VISITED_BITS:VISITED_BITS + (count + 7) // 8].hex(),
        'visited_set_before': sum(before.bit(VISITED_BITS, i) for i in range(count)),
        'scene_table_pointer': f'0x{table_ptr:08X}', 'scene_table_count': table_count,
        'scene_table_type_values': [before.u16(table_ptr + 12 * i + 8) for i in range(table_count)],
        'scene_flag_prefix_hex': source[SCENE_FLAGS:SCENE_FLAGS + (table_count + 7) // 8].hex(),
        'hypothetical_simulation': result,
        'scope': '这是现有即时存档某一时刻的单个快照；模拟结果不是原游戏执行前后实测，也不是新游戏初值。',
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write('\n')
    print('场景总数', count, '已置位', payload['visited_set_before'], '场景表项目', table_count)
    print('快照内假设运行:', result)
    print('只读汇总:', args.output)


if __name__ == '__main__':
    main()
