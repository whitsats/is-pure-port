"""用现有快照的内存副本执行原状态复制函数，记录写入范围，不推断业务含义。"""
import argparse
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile

from unicorn import Uc, UC_ARCH_MIPS, UC_HOOK_MEM_WRITE, UC_MODE_LITTLE_ENDIAN, UC_MODE_MIPS64
from unicorn.mips_const import (UC_CPU_MIPS64_20KC, UC_MIPS_REG_GP, UC_MIPS_REG_PC,
                                UC_MIPS_REG_RA, UC_MIPS_REG_SP)
from mac_progress_snapshot import EE_SIZE
from 检查即时存档表 import elf_gp
import MAC_命令表提取 as common
import 状态字证据 as evidence

START, END, RETURN = 0x1161C0, 0x1165D4, 0x1F02000


def ranges(values):
    values = sorted(values)
    if not values:
        return []
    result, start, last = [], values[0], values[0]
    for value in values[1:]:
        if value != last + 1:
            result.append((start, last + 1))
            start = value
        last = value
    result.append((start, last + 1))
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--savestate', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    archive = args.savestate.read_bytes()
    with ZipFile(args.savestate) as z:
        source = z.read('eeMemory.bin')
    if len(source) != EE_SIZE:
        raise ValueError('EE 内存不是 32 MiB')
    elf = common.ELF.read_bytes()
    offset = evidence.vaddr_to_offset(evidence.segments(elf), START, END - START)
    if source[START:END] != elf[offset:offset + END - START]:
        raise ValueError('状态复制函数与 ELF 不一致')
    machine = Uc(UC_ARCH_MIPS, UC_MODE_MIPS64 | UC_MODE_LITTLE_ENDIAN)
    machine.ctl_set_cpu_model(UC_CPU_MIPS64_20KC)
    machine.mem_map(0, EE_SIZE)
    machine.mem_write(0, source)
    machine.reg_write(UC_MIPS_REG_GP, elf_gp(elf))
    machine.reg_write(UC_MIPS_REG_SP, 0x1F10000)
    machine.reg_write(UC_MIPS_REG_RA, RETURN)
    touched, events = set(), [0]

    def track(_uc, _access, address, size, _value, _user):
        events[0] += 1
        touched.update(range(address, address + size))

    machine.hook_add(UC_HOOK_MEM_WRITE, track)
    machine.emu_start(START, RETURN, count=200000)
    if machine.reg_read(UC_MIPS_REG_PC) != RETURN:
        raise ValueError('函数未正常返回')
    changed = {i for i in touched if machine.mem_read(i, 1)[0] != source[i]}
    payload = {'savestate_sha256': hashlib.sha256(archive).hexdigest(),
               'elf_sha256': hashlib.sha256(elf).hexdigest(),
               'function': '0x001161C0', 'writes': events[0],
               'touched_bytes': len(touched), 'changed_bytes': len(changed),
               'written_ranges': [{'start': f'0x{a:08X}', 'end_exclusive': f'0x{b:08X}', 'length': b-a}
                                  for a, b in ranges(touched)],
               'changed_ranges': [{'start': f'0x{a:08X}', 'end_exclusive': f'0x{b:08X}', 'length': b-a}
                                  for a, b in ranges(changed)],
               'scope': '真实快照内存副本执行原函数；写入范围仅代表当前输入，不能推断其他状态、业务含义或完整存读档。'}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write('\n')
    print(f"writes={events[0]} touched={len(touched)} changed={len(changed)} ranges={len(payload['written_ranges'])}")
    print('Output:', args.output)


if __name__ == '__main__':
    main()
