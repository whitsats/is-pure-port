"""Run the original MAC_006 effect timing and palette writes in isolated EE memory."""
import argparse
import json
from pathlib import Path
import struct
from zipfile import ZipFile

from 隔离核查effect_start import (CTX, VM, STACK, SCRIPT, END, HANDLER, DISPATCH_REFRESH,
                                    ROOT, common, elf_gp, Uc, UC_ARCH_MIPS, UC_MODE_MIPS64,
                                    UC_MODE_LITTLE_ENDIAN, UC_CPU_MIPS64_20KC, UC_HOOK_CODE,
                                    UC_MIPS_REG_GP, UC_MIPS_REG_SP, UC_MIPS_REG_A0, UC_MIPS_REG_RA,
                                    UC_MIPS_REG_PC)


def inspect(snapshot):
    with ZipFile(snapshot) as archive:
        source = archive.read('eeMemory.bin')
    gp = elf_gp(common.ELF.read_bytes())
    state = struct.unpack_from('<I', source, gp - 0x6D44)[0]
    machine = Uc(UC_ARCH_MIPS, UC_MODE_MIPS64 | UC_MODE_LITTLE_ENDIAN)
    machine.ctl_set_cpu_model(UC_CPU_MIPS64_20KC)
    machine.mem_map(0, len(source))
    machine.mem_write(0, source)

    def read(address, count=4, *, signed=False):
        return int.from_bytes(machine.mem_read(address, count), 'little', signed=signed)

    def put(address, value, count=4):
        machine.mem_write(address, value.to_bytes(count, 'little'))

    def invoke(address, context):
        for register, value in ((UC_MIPS_REG_GP, gp), (UC_MIPS_REG_SP, STACK),
                                (UC_MIPS_REG_A0, context), (UC_MIPS_REG_RA, END)):
            machine.reg_write(register, value)
        machine.emu_start(address, END, count=100000)
        if machine.reg_read(UC_MIPS_REG_PC) != END:
            raise ValueError(f'原处理函数没有按时返回: {address:#x}')

    def command(handler, offset, length, phase=0):
        machine.mem_write(SCRIPT, raw[offset:offset + length])
        put(VM + 8, SCRIPT)
        put(CTX + 0x10, phase, 2)
        invoke(handler, CTX)
        return read(VM + 8) - SCRIPT

    def skip(uc, address, size, target):
        uc.reg_write(UC_MIPS_REG_PC, target if target else uc.reg_read(UC_MIPS_REG_RA))

    raw = (ROOT / '输出-保护边修复/MAC/MAC_006.bin').read_bytes()
    machine.hook_add(UC_HOOK_CODE, skip, None, begin=DISPATCH_REFRESH, end=DISPATCH_REFRESH)
    machine.hook_add(UC_HOOK_CODE, skip, 0x132B38, begin=0x132A24, end=0x132A24)
    machine.mem_write(CTX, bytes(0x100))
    machine.mem_write(VM, bytes(0x200))
    put(CTX + 0x44, VM)

    record = state + 0x3F18C
    started = command(HANDLER, 0x3BA4, 40)
    object_context = read(record + 4)
    put(object_context + 0x44, record)
    put(object_context + 0x10, 0, 2)
    rise = []
    for _ in range(8):
        invoke(0x132888, object_context)
        rise.append(read(record + 0x1C))
    request = command(0x11E110, 0x3BE4, 8)
    first_poll = command(0x11E110, 0x3BEC, 8)
    frames = []
    for _ in range(8):
        invoke(0x132888, object_context)
        frames.append({'level': read(record + 0x1C, signed=True), 'busy': read(record + 0x10),
                       'advance': command(0x11E110, 0x3BEC, 8, phase=1)})

    palettes = []
    for offset in (0x4050, 0x4054, 0x40A4):
        slot = raw[offset + 1]
        address = state + 0x3DEFB + 264 * slot
        put(address, 0, 1)
        advance = command(0x11B570, offset, 4)
        palettes.append({'offset': hex(offset), 'slot': slot, 'advance': advance, 'value': read(address, 1)})

    return {'scope': '空白卡存档内存副本。跳过图形坐标提交尾段 0x132A24 及解释器刷新，执行原计时分支与调色板写入。',
            'start_advance': started, 'rise': rise, 'request_advance': request, 'first_poll_advance': first_poll,
            'completion_frames': frames, 'palettes': palettes}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--snapshot', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = inspect(args.snapshot)
    with args.output.open('x', encoding='utf-8') as file:
        json.dump(report, file, ensure_ascii=False, indent=2)
        file.write('\n')
    print(report)
