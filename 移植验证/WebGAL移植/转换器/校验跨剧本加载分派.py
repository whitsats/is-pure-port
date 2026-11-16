"""隔离运行资源加载分派；桩替换底层读取，只验证实际传入的组和条目号。"""
import argparse
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile

from unicorn import Uc, UC_ARCH_MIPS, UC_HOOK_CODE, UC_MODE_LITTLE_ENDIAN, UC_MODE_MIPS64
from unicorn.mips_const import (UC_CPU_MIPS64_20KC, UC_MIPS_REG_A0, UC_MIPS_REG_A1,
                                UC_MIPS_REG_A2, UC_MIPS_REG_A3, UC_MIPS_REG_GP,
                                UC_MIPS_REG_PC, UC_MIPS_REG_RA, UC_MIPS_REG_SP)
from mac_progress_snapshot import EE_SIZE
from 检查即时存档表 import elf_gp
import MAC_命令表提取 as common
import 状态字证据 as evidence

START, END, HELPER = 0x12D810, 0x1F02000, 0x101BF0


def run(source, gp, index):
    machine = Uc(UC_ARCH_MIPS, UC_MODE_MIPS64 | UC_MODE_LITTLE_ENDIAN)
    machine.ctl_set_cpu_model(UC_CPU_MIPS64_20KC)
    machine.mem_map(0, EE_SIZE)
    machine.mem_write(0, source)
    machine.reg_write(UC_MIPS_REG_A0, index)
    machine.reg_write(UC_MIPS_REG_GP, gp)
    machine.reg_write(UC_MIPS_REG_SP, 0x1F10000)
    machine.reg_write(UC_MIPS_REG_RA, END)
    calls = []

    def hook(uc, address, _size, _user):
        if address == HELPER:
            calls.append([uc.reg_read(reg) & 0xFFFFFFFF
                          for reg in (UC_MIPS_REG_A0, UC_MIPS_REG_A1, UC_MIPS_REG_A2, UC_MIPS_REG_A3)])
            uc.reg_write(UC_MIPS_REG_PC, uc.reg_read(UC_MIPS_REG_RA))

    machine.hook_add(UC_HOOK_CODE, hook)
    machine.emu_start(START, END, count=2000)
    if machine.reg_read(UC_MIPS_REG_PC) != END or len(calls) != 1 or calls[0][:2] != [0, index]:
        raise ValueError(f'加载分派不匹配: {index}, calls={calls}')
    return {'resource_id': f'0x{index:04X}', 'helper': '0x00101BF0',
            'group': calls[0][0], 'index': calls[0][1],
            'arg2': f'0x{calls[0][2]:08X}', 'arg3': f'0x{calls[0][3]:08X}'}


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--savestate', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    archive = args.savestate.read_bytes()
    with ZipFile(args.savestate) as z:
        source = z.read('eeMemory.bin')
    if len(source) != EE_SIZE:
        raise ValueError('EE 内存大小不符')
    elf = common.ELF.read_bytes()
    segs = evidence.segments(elf)
    for address, size in ((START, 0x170), (0x259FD0, 0x40)):
        off = evidence.vaddr_to_offset(segs, address, size)
        if source[address:address + size] != elf[off:off + size]:
            raise ValueError(f'快照加载器与 ELF 不一致: {address:#x}')
    selector = source[0x1B741F8]
    if selector != 1:
        raise ValueError(f'此实验仅支持快照加载类型 1，实际 {selector}')
    cases = [run(source, elf_gp(elf), i) for i in (0, 1, 2, 44)]
    payload = {'savestate_sha256': hashlib.sha256(archive).hexdigest(),
               'elf_sha256': hashlib.sha256(elf).hexdigest(), 'selector': selector,
               'cases': cases,
               'scope': '仅在现有快照的内存副本执行分派函数；底层读取函数用立即返回桩替换。未实际读取光盘或验证异步加载与跳转后的状态。'}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write('\n')
    print('resource dispatch cases matched:', len(cases), 'output:', args.output)


if __name__ == '__main__':
    main()
