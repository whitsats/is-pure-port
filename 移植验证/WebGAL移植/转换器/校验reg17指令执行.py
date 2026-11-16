"""在隔离 Unicorn 内执行原 ELF 的 0x17 指令路径，与独立 Python 模型比较。

输入为 PCSX2 即时存档中的内存副本；不会运行 PCSX2、修改存档或写回进程。
三个场景包括真实快照、模拟未完成、模拟最后一位置位。后两者是构造数据。
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
from zipfile import ZipFile

from unicorn import Uc, UC_ARCH_MIPS, UC_HOOK_MEM_WRITE, UC_MODE_LITTLE_ENDIAN, UC_MODE_MIPS64
from unicorn.mips_const import (UC_CPU_MIPS64_20KC, UC_MIPS_REG_GP, UC_MIPS_REG_PC,
                                UC_MIPS_REG_S2, UC_MIPS_REG_S3, UC_MIPS_REG_SP)
from mac_progress_snapshot import (EE_SIZE, EeMemory, SCENE_FLAGS, SCENE_TABLE_COUNT,
                                   SCENE_TABLE_PTR, STORY_COUNT, VISITED_BITS,
                                   read_state_base, simulate_reg17)
from 检查即时存档表 import elf_gp
import MAC_命令表提取 as common
import 状态字证据 as evidence

START, STOP = 0x118FD0, 0x119078
SCRATCH, STACK = 0x1F00000, 0x1F10000
CODE_RANGES = ((0x118FD0, 0x28), (0x117270, 0x18), (0x117288, 0x90),
               (0x105200, 0xC8), (0x1174B8, 0x78), (0x105818, 0x20),
               (0x117638, 0x18), (0x105698, 0xB0))


def verify_code(memory, elf):
    segments = evidence.segments(elf)
    for address, size in CODE_RANGES:
        offset = evidence.vaddr_to_offset(segments, address, size)
        if memory[address:address + size] != elf[offset:offset + size]:
            raise ValueError(f'快照中的代码与 ELF 不一致: {address:#x}')


def run_case(source, gp, operand):
    expected = EeMemory(bytearray(source))
    effect = simulate_reg17(expected, gp, operand)
    state = read_state_base(EeMemory(bytearray(source)), gp)
    machine = Uc(UC_ARCH_MIPS, UC_MODE_MIPS64 | UC_MODE_LITTLE_ENDIAN)
    machine.ctl_set_cpu_model(UC_CPU_MIPS64_20KC)
    machine.mem_map(0, EE_SIZE)
    machine.mem_write(0, bytes(source))
    machine.mem_write(SCRATCH, bytes([0x09, 0x17, operand & 255, operand >> 8, 0, 0, 0, 0]))
    machine.reg_write(UC_MIPS_REG_S2, SCRATCH)
    machine.reg_write(UC_MIPS_REG_S3, SCRATCH + 0x1000)
    machine.reg_write(UC_MIPS_REG_SP, STACK)
    machine.reg_write(UC_MIPS_REG_GP, gp)
    writes = []

    def track(_machine, _access, address, size, _value, _user):
        if STACK - 0x1000 <= address < STACK + 0x1000:
            return
        writes.append((address, size))

    machine.hook_add(UC_HOOK_MEM_WRITE, track)
    machine.emu_start(START, STOP, count=100000)
    if machine.reg_read(UC_MIPS_REG_PC) != STOP:
        raise ValueError('原指令未在步数限制内到达预期结束位置')
    allowed = {state + 0x440, state + 0x441, *(state + 0x4B0 + i for i in range(4)),
               VISITED_BITS + operand // 8}
    allowed.update(SCENE_FLAGS + i // 8 for i in effect['scene_flag_indices_set'])
    touched = {address + i for address, size in writes for i in range(size)}
    if touched - allowed:
        raise ValueError(f'原指令存在未建模的写入: {sorted(touched - allowed)}')
    for address in sorted(touched | allowed):
        if bytes(machine.mem_read(address, 1)) != bytes(expected.data[address:address + 1]):
            raise ValueError(f'Python 模型与原指令不一致: {address:#x}')
    return {'operand': operand, 'model': effect,
            'writes': [{'address': f'0x{a:08X}', 'size': n} for a, n in writes],
            'touched_bytes_compared': len(touched | allowed), 'comparison': '匹配'}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--savestate', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    archive_bytes = args.savestate.read_bytes()
    with ZipFile(args.savestate) as z:
        source = z.read('eeMemory.bin')
    if len(source) != EE_SIZE:
        raise ValueError('EE 内存大小不是 32 MiB')
    elf = common.ELF.read_bytes()
    verify_code(source, elf)
    gp = elf_gp(elf)
    snapshot = run_case(source, gp, 1)
    snapshot['scenario'] = '现有快照，重复访问编号 1'
    incomplete = bytearray(source)
    incomplete[VISITED_BITS:VISITED_BITS + 8] = bytes(8)
    incomplete[SCENE_FLAGS] = 0
    incomplete_case = run_case(incomplete, gp, 1)
    incomplete_case['scenario'] = '构造：前 57 位未完成'
    completed = bytearray(source)
    if struct.unpack_from('<I', completed, STORY_COUNT)[0] != 57:
        raise ValueError('样本的剧本计数已变化')
    completed[VISITED_BITS:VISITED_BITS + 7] = b'\xff' * 7
    completed[VISITED_BITS + 7] &= 0xFE
    completed[SCENE_FLAGS] = 0
    ptr, n = struct.unpack_from('<II', completed, SCENE_TABLE_PTR)
    if n < 1:
        raise ValueError('样本没有可构造的场景记录')
    struct.pack_into('<H', completed, ptr + 8, 3)
    completed_case = run_case(completed, gp, 56)
    completed_case['scenario'] = '构造：补上第 57 位，场景第 0 项类型改为 3'
    payload = {'savestate': str(args.savestate), 'savestate_sha256': hashlib.sha256(archive_bytes).hexdigest(),
               'elf_sha256': hashlib.sha256(elf).hexdigest(), 'cpu': 'Unicorn MIPS64 20KC little-endian',
               'checked_code_ranges': [{'start': f'0x{a:08X}', 'length': n} for a, n in CODE_RANGES],
               'cases': [snapshot, incomplete_case, completed_case],
               'scope': '只验证当前指令路径与内存副本，不是 PCSX2 原机前后实测；构造场景不代表真实游戏状态。'}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write('\n')
    for case in payload['cases']:
        print(case['scenario'], case['comparison'], case['model'])
    print('证据:', args.output)


if __name__ == '__main__':
    main()
