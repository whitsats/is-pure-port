"""隔离执行同剧本调用与返回的原指令；只替换派发器刷新函数。"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
from zipfile import ZipFile

from unicorn import Uc, UC_ARCH_MIPS, UC_HOOK_CODE, UC_MODE_LITTLE_ENDIAN, UC_MODE_MIPS64
from unicorn.mips_const import (UC_CPU_MIPS64_20KC, UC_MIPS_REG_A0, UC_MIPS_REG_GP,
                                UC_MIPS_REG_PC, UC_MIPS_REG_RA, UC_MIPS_REG_SP)
from mac_progress_snapshot import EE_SIZE
from mac_reader import ROOT
from 检查即时存档表 import elf_gp
import MAC_命令表提取 as common
import 状态字证据 as evidence

CALL, RETURN, HELPER = 0x1195C8, 0x119650, 0x117DC0
END, SCRIPT, CTX, VM, STACK = 0x1FF0000, 0x1E00000, 0x1F40000, 0x1F41000, 0x1FD0000


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
    off = evidence.vaddr_to_offset(segs, CALL, 0xF0)
    if source[CALL:CALL + 0xF0] != elf[off:off + 0xF0]:
        raise ValueError('快照与 ELF 代码不一致')
    script = (ROOT / '输出-保护边修复/MAC/MAC_069.bin').read_bytes()
    if script[0xA4:0xAC] != bytes.fromhex('040000000c000000'):
        raise ValueError('真实脚本的调用字节不符合预期')
    uc = Uc(UC_ARCH_MIPS, UC_MODE_MIPS64 | UC_MODE_LITTLE_ENDIAN)
    uc.ctl_set_cpu_model(UC_CPU_MIPS64_20KC)
    uc.mem_map(0, EE_SIZE)
    uc.mem_write(0, source)
    uc.mem_write(SCRIPT, script)
    uc.reg_write(UC_MIPS_REG_GP, elf_gp(elf))
    uc.reg_write(UC_MIPS_REG_SP, STACK)
    def u32(addr): return int.from_bytes(uc.mem_read(addr, 4), 'little')
    def put32(addr, n): uc.mem_write(addr, struct.pack('<I', n))
    state = u32(elf_gp(elf) - 0x6D44)
    uc.mem_write(CTX, bytes(0x100))
    uc.mem_write(VM, bytes(0x200))
    put32(CTX + 0x44, VM)
    put32(VM + 0xC, SCRIPT)
    def hook(machine, address, _size, _user):
        if address == HELPER:
            machine.reg_write(UC_MIPS_REG_PC, machine.reg_read(UC_MIPS_REG_RA))
    uc.hook_add(UC_HOOK_CODE, hook)
    def invoke(address):
        uc.reg_write(UC_MIPS_REG_A0, CTX)
        uc.reg_write(UC_MIPS_REG_RA, END)
        uc.emu_start(address, END, count=5000)
        if uc.reg_read(UC_MIPS_REG_PC) != END:
            raise ValueError('函数未正常返回')
    trace = []
    # 第二次调用位置也来自原脚本；嵌套是人为构造，不表示真实执行路径。
    for index, (offset, resource) in enumerate(((0xA4, 0x1234), (0xD0, 0x5678))):
        put32(VM + 8, SCRIPT + offset)
        put32(state + 0x52E0, resource)
        invoke(CALL)
        expected = (index + 1, SCRIPT + 0x0C, resource, offset + 8)
        actual = (u32(VM + 0x10), u32(VM + 8), u32(VM + 0x14 + index * 8), u32(VM + 0x18 + index * 8))
        if actual != expected:
            raise ValueError(f'调用入栈不符: {actual} != {expected}')
        trace.append({'event': 'call', 'source_offset': f'0x{offset:X}', 'depth': actual[0],
                      'target_offset': '0x0C', 'saved_resource': f'0x{resource:X}', 'return_offset': f'0x{offset+8:X}'})
    put32(state + 0x52E0, 0x9999)
    for index, (offset, resource) in enumerate(((0xD0, 0x5678), (0xA4, 0x1234))):
        put32(VM + 8, SCRIPT + 0x84)
        invoke(RETURN)
        actual = (u32(VM + 0x10), u32(VM + 8) - SCRIPT, u32(state + 0x52E0))
        expected = (1 - index, offset + 8, resource)
        if actual != expected:
            raise ValueError(f'返回出栈不符: {actual} != {expected}')
        trace.append({'event': 'return', 'depth': actual[0], 'restored_offset': f'0x{actual[1]:X}',
                      'restored_resource': f'0x{actual[2]:X}'})
    result = {'savestate_sha256': hashlib.sha256(archive).hexdigest(),
              'elf_sha256': hashlib.sha256(elf).hexdigest(),
              'script_sha256': hashlib.sha256(script).hexdigest(), 'trace': trace,
              'scope': '两层调用和逐层返回在内存副本执行原指令；嵌套路径及资源值为构造数据，派发器刷新为桩，未执行被调用子程序。'}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
        f.write('\n')
    print('two nested calls and returns matched; output:', args.output)


if __name__ == '__main__':
    main()
