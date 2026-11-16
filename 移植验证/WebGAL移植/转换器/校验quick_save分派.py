"""隔离运行 quick_save 原处理函数；只验证调用条件，不执行被调用的保存函数。"""
import argparse
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile

from unicorn import Uc, UC_ARCH_MIPS, UC_HOOK_CODE, UC_MODE_LITTLE_ENDIAN, UC_MODE_MIPS64
from unicorn.mips_const import (UC_CPU_MIPS64_20KC, UC_MIPS_REG_A0, UC_MIPS_REG_GP,
                                UC_MIPS_REG_PC, UC_MIPS_REG_RA, UC_MIPS_REG_SP)
from mac_progress_snapshot import EE_SIZE, EeMemory, read_state_base
from 检查即时存档表 import elf_gp
import MAC_命令表提取 as common
import 状态字证据 as evidence

HANDLER, END = 0x11D888, 0x1F02000
CONTEXT, SCRIPT_CTX, INSTRUCTION, STACK = 0x1F04000, 0x1F05000, 0x1F06000, 0x1F10000
FLAG = 0xA98DA3
CALLEES = {0x1161C0: 'state_copy', 0x116AD0: 'save_helper', 0x117DC0: 'advance_helper'}


def execute(source, gp, mode, gate, flags):
    memory = EeMemory(bytearray(source))
    state = read_state_base(memory, gp)
    memory.data[state + 0x4C5] = gate
    memory.data[FLAG] = flags
    memory.write32(CONTEXT + 0x44, SCRIPT_CTX)
    memory.write32(SCRIPT_CTX + 8, INSTRUCTION)
    memory.data[INSTRUCTION:INSTRUCTION + 4] = bytes([0x5A, mode, 0, 0])
    machine = Uc(UC_ARCH_MIPS, UC_MODE_MIPS64 | UC_MODE_LITTLE_ENDIAN)
    machine.ctl_set_cpu_model(UC_CPU_MIPS64_20KC)
    machine.mem_map(0, EE_SIZE)
    machine.mem_write(0, bytes(memory.data))
    machine.reg_write(UC_MIPS_REG_A0, CONTEXT)
    machine.reg_write(UC_MIPS_REG_GP, gp)
    machine.reg_write(UC_MIPS_REG_SP, STACK)
    machine.reg_write(UC_MIPS_REG_RA, END)
    calls = []

    def hook(uc, address, _size, _user):
        if address in CALLEES:
            calls.append(CALLEES[address])
            # 明确桩替换：只检查处理函数怎样分派，不能证明保存函数的副作用。
            uc.reg_write(UC_MIPS_REG_PC, uc.reg_read(UC_MIPS_REG_RA))

    machine.hook_add(UC_HOOK_CODE, hook)
    machine.emu_start(HANDLER, END, count=10000)
    actual_ip = int.from_bytes(machine.mem_read(SCRIPT_CTX + 8, 4), 'little')
    expected = ([] if gate else ['state_copy'])
    if (mode == 1 and flags & 1) or (mode == 2 and flags & 2):
        expected.append('save_helper')
    expected.append('advance_helper')
    if machine.reg_read(UC_MIPS_REG_PC) != END or calls != expected or actual_ip != INSTRUCTION + 4:
        raise AssertionError((mode, gate, flags, calls, expected, hex(actual_ip)))
    return {'mode': mode, 'state_gate': gate, 'save_flags': flags, 'calls': calls,
            'ip_advance': actual_ip - INSTRUCTION, 'comparison': '匹配'}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--savestate', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    archive = args.savestate.read_bytes()
    with ZipFile(args.savestate) as z:
        source = z.read('eeMemory.bin')
    elf = common.ELF.read_bytes()
    offset = evidence.vaddr_to_offset(evidence.segments(elf), HANDLER, 0xC8)
    if source[HANDLER:HANDLER + 0xC8] != elf[offset:offset + 0xC8]:
        raise ValueError('即时存档中的处理函数与 ELF 不一致')
    gp = elf_gp(elf)
    cases = [execute(source, gp, mode, gate, flags)
             for mode in range(4) for gate in range(2) for flags in range(4)]
    payload = {'savestate_sha256': hashlib.sha256(archive).hexdigest(),
               'elf_sha256': hashlib.sha256(elf).hexdigest(), 'cases': cases,
               'scope': '处理函数执行原机器码；三个被调用函数均用立即返回桩替代。只验证调用分派及指令指针，不验证其内容、真实存档和画面行为。'}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write('\n')
    print(f'{len(cases)} cases matched; calls stubbed. Output: {args.output}')


if __name__ == '__main__':
    main()
