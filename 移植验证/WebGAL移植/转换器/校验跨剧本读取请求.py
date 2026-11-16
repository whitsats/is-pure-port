"""执行资源分派与队列构建；单条 R5900 乘法由等价算术替代，不执行后续异步读盘。"""
import argparse
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile

from unicorn import Uc, UC_ARCH_MIPS, UC_HOOK_CODE, UC_MODE_LITTLE_ENDIAN, UC_MODE_MIPS64
from unicorn.mips_const import (UC_CPU_MIPS64_20KC, UC_MIPS_REG_A0, UC_MIPS_REG_A1,
                                UC_MIPS_REG_A2, UC_MIPS_REG_A3, UC_MIPS_REG_GP,
                                UC_MIPS_REG_PC, UC_MIPS_REG_RA, UC_MIPS_REG_SP,
                                UC_MIPS_REG_T1, UC_MIPS_REG_V0)
from mac_progress_snapshot import EE_SIZE
from 检查即时存档表 import elf_gp
import MAC_命令表提取 as common
import 状态字证据 as evidence

START, END = 0x12D810, 0x1F02000
MULT, REQUEST_HELPER = 0x101C48, 0x101BF0
GROUPS, REQUESTS = 0x1B7423C, 0x1B75484


def execute(source, gp, index):
    uc = Uc(UC_ARCH_MIPS, UC_MODE_MIPS64 | UC_MODE_LITTLE_ENDIAN)
    uc.ctl_set_cpu_model(UC_CPU_MIPS64_20KC)
    uc.mem_map(0, EE_SIZE)
    uc.mem_write(0, source)
    uc.reg_write(UC_MIPS_REG_A0, index)
    uc.reg_write(UC_MIPS_REG_GP, gp)
    uc.reg_write(UC_MIPS_REG_SP, 0x1F10000)
    uc.reg_write(UC_MIPS_REG_RA, END)
    calls, replaced = [], []

    def hook(machine, address, _size, _user):
        if address == REQUEST_HELPER:
            calls.append([machine.reg_read(r) & 0xFFFFFFFF
                          for r in (UC_MIPS_REG_A0, UC_MIPS_REG_A1, UC_MIPS_REG_A2, UC_MIPS_REG_A3)])
        if address == MULT:
            # R5900 的 mult $a0,$t1,$a0：仅模拟结果寄存器，后续路径不读取 HI/LO。
            lhs, rhs = machine.reg_read(UC_MIPS_REG_T1), machine.reg_read(UC_MIPS_REG_A0)
            machine.reg_write(UC_MIPS_REG_A0, (lhs * rhs) & 0xFFFFFFFF)
            machine.reg_write(UC_MIPS_REG_PC, MULT + 4)
            replaced.append(True)

    uc.hook_add(UC_HOOK_CODE, hook)
    uc.emu_start(START, END, count=5000)
    if uc.reg_read(UC_MIPS_REG_PC) != END or len(calls) != 1 or len(replaced) != 1:
        raise ValueError(f'未到预期返回或调用次数异常: {calls} {replaced}')
    slot = uc.reg_read(UC_MIPS_REG_V0) & 0xFFFFFFFF
    if slot >= 10:
        raise ValueError(f'无可用异步请求槽: {slot}')
    request = REQUESTS + slot * 0x16C
    def u32(a): return int.from_bytes(uc.mem_read(a, 4), 'little')
    descriptor = u32(request)
    entry = u32(request + 0x108)
    handler = u32(request + 0x10C)
    status = uc.mem_read(request + 0x119, 1)[0]
    group_type = u32(descriptor)
    name = bytes(uc.mem_read(descriptor + 8, 32)).split(b'\0', 1)[0].decode('ascii')
    if calls[0][:2] != [0, index] or descriptor != GROUPS or entry != index or name.lower() != 'mac.afs' or group_type != 2 or status != 1:
        raise ValueError(f'异步请求字段不匹配: {index=} {calls=} {descriptor=:x} {entry=} {name=} {group_type=} {status=}')
    return {'resource_id': index, 'request_slot': slot, 'archive': name, 'archive_type': group_type,
            'archive_entry': entry, 'request_handler': f'0x{handler:08X}', 'request_flag': status,
            'request_arg2': f'0x{u32(request + 0x15C):08X}', 'request_arg3': f'0x{u32(request + 0x160):08X}'}


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
    for address, size in ((START, 0x170), (REQUEST_HELPER, 0x130), (0x259FD0, 0x40)):
        off = evidence.vaddr_to_offset(segs, address, size)
        if source[address:address + size] != elf[off:off + size]:
            raise ValueError(f'快照代码与 ELF 不一致: {address:#x}')
    if source[MULT:MULT + 4] != bytes.fromhex('18202401') or source[0x1B741F8] != 1:
        raise ValueError('R5900 乘法指令或当前资源分派模式不符合实验条件')
    cases = [execute(source, elf_gp(elf), index) for index in (0, 1, 2, 44)]
    result = {'savestate_sha256': hashlib.sha256(archive).hexdigest(),
              'elf_sha256': hashlib.sha256(elf).hexdigest(), 'cases': cases,
              'scope': '分派和异步请求构建执行原机器码；一条 R5900 三操作数乘法在 Unicorn 中模拟，未运行后续异步读取及解压。'}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
        f.write('\n')
    print('original request construction cases matched:', len(cases), 'output:', args.output)


if __name__ == '__main__':
    main()
