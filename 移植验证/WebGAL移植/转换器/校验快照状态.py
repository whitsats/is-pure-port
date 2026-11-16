"""用原始 MIPS 读写函数验证 SnapshotState；只执行即时存档内存副本。"""
import argparse
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile

from unicorn import Uc, UC_ARCH_MIPS, UC_MODE_LITTLE_ENDIAN, UC_MODE_MIPS64
from unicorn.mips_const import (UC_CPU_MIPS64_20KC, UC_MIPS_REG_A0, UC_MIPS_REG_A1,
                                UC_MIPS_REG_GP, UC_MIPS_REG_RA, UC_MIPS_REG_SP, UC_MIPS_REG_V0)
from mac_progress_snapshot import EeMemory, EE_SIZE
from mac_state import to_s16
from mac_state_snapshot import SnapshotState
from 检查即时存档表 import elf_gp
import MAC_命令表提取 as common
import 状态字证据 as evidence

RETURN = 0x1F20000


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--savestate', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    raw = args.savestate.read_bytes()
    with ZipFile(args.savestate) as archive:
        source = archive.read('eeMemory.bin')
    if len(source) != EE_SIZE:
        raise ValueError('EE 内存大小不符')
    elf = common.ELF.read_bytes()
    segs = evidence.segments(elf)
    for address, size in ((0x115730, 0xC0), (0x1157F8, 0x140)):
        off = evidence.vaddr_to_offset(segs, address, size)
        if source[address:address + size] != elf[off:off + size]:
            raise ValueError(f'快照中的状态函数与 ELF 不一致: {address:#x}')
    gp = elf_gp(elf)
    state = SnapshotState(EeMemory(bytearray(source)), gp, hashlib.sha256(raw).hexdigest())
    machine = Uc(UC_ARCH_MIPS, UC_MODE_MIPS64 | UC_MODE_LITTLE_ENDIAN)
    machine.ctl_set_cpu_model(UC_CPU_MIPS64_20KC)
    machine.mem_map(0, EE_SIZE)
    machine.mem_write(0, source)
    machine.reg_write(UC_MIPS_REG_GP, gp)
    machine.reg_write(UC_MIPS_REG_SP, 0x1F10000)
    results = []
    for operand in (0x0000, 0xFFFF, 0x4000, 0x6000, 0x600E, 0x6110, 0x6148, 0x8001, 0xA01A):
        machine.reg_write(UC_MIPS_REG_RA, RETURN)
        machine.reg_write(UC_MIPS_REG_A0, operand)
        machine.emu_start(0x115730, RETURN, count=2000)
        actual = to_s16(machine.reg_read(UC_MIPS_REG_V0))
        expected = state.read(operand)
        if actual != expected:
            raise ValueError(f'读状态不一致: {operand:#x} {actual} != {expected}')
        results.append({'operation': 'read', 'operand': f'0x{operand:04X}', 'value': actual})
    for operand, value in ((0x6000, 42), (0x600E, -7), (0x6110, 1), (0x6148, 0),
                           (0x8010, 1), (0x8010, 2), (0x8010, -1), (0xA010, 1),
                           (0xA010, 0), (0xA015, 3), (0xA015, -2)):
        machine.reg_write(UC_MIPS_REG_RA, RETURN)
        machine.reg_write(UC_MIPS_REG_A0, operand)
        machine.reg_write(UC_MIPS_REG_A1, value & 0xFFFF)
        machine.emu_start(0x1157F8, RETURN, count=2000)
        before, after = state.write(operand, value)
        kind, bank, index = state.address_of(operand)
        address = state.state_base + state.offset_of(kind, bank, index)
        length = 2 if kind == 'word' else 1
        actual = bytes(machine.mem_read(address, length))
        expected = bytes(state.memory.data[address:address + length])
        if actual != expected:
            raise ValueError(f'写状态不一致: {operand:#x}')
        results.append({'operation': 'write', 'operand': f'0x{operand:04X}', 'before': before, 'after': after})
    report = {'savestate_sha256': hashlib.sha256(raw).hexdigest(), 'elf_sha256': hashlib.sha256(elf).hexdigest(),
              'scope': '原始 MIPS 函数与 Python 在同一内存副本上的样本对照；非 PCSX2 游戏实时操作。',
              'comparisons': results}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
        f.write('\n')
    print('原函数与快照状态模型匹配:', len(results), '项；输出:', args.output)


if __name__ == '__main__':
    main()
