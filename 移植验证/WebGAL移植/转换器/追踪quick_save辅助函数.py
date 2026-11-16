"""隔离追踪 quick_save 辅助函数；系统调用替换为假成功，不能用于正式存档语义。"""
import argparse
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile

from unicorn import Uc, UcError, UC_ARCH_MIPS, UC_HOOK_CODE, UC_HOOK_MEM_WRITE, UC_MODE_LITTLE_ENDIAN, UC_MODE_MIPS64
from unicorn.mips_const import (UC_CPU_MIPS64_20KC, UC_MIPS_REG_GP, UC_MIPS_REG_PC,
                                UC_MIPS_REG_RA, UC_MIPS_REG_SP, UC_MIPS_REG_V0, UC_MIPS_REG_V1)
from mac_progress_snapshot import EE_SIZE
from 检查即时存档表 import elf_gp
import MAC_命令表提取 as common
import 状态字证据 as evidence

START, RETURN, SYSTEM_CALL = 0x116AD0, 0x1F02000, 0x2059F4


def spans(values):
    values = sorted(values)
    if not values:
        return []
    start = last = values[0]
    result = []
    for value in values[1:]:
        if value != last + 1:
            result.append({'start': f'0x{start:08X}', 'end_exclusive': f'0x{last + 1:08X}', 'length': last - start + 1})
            start = value
        last = value
    result.append({'start': f'0x{start:08X}', 'end_exclusive': f'0x{last + 1:08X}', 'length': last - start + 1})
    return result


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
    for address, size in ((START, 0x430), (SYSTEM_CALL - 4, 0x10)):
        off = evidence.vaddr_to_offset(segs, address, size)
        if source[address:address + size] != elf[off:off + size]:
            raise ValueError(f'快照与 ELF 的代码不一致: {address:#x}')
    uc = Uc(UC_ARCH_MIPS, UC_MODE_MIPS64 | UC_MODE_LITTLE_ENDIAN)
    uc.ctl_set_cpu_model(UC_CPU_MIPS64_20KC)
    uc.mem_map(0, EE_SIZE)
    uc.mem_write(0, source)
    uc.reg_write(UC_MIPS_REG_GP, elf_gp(elf))
    uc.reg_write(UC_MIPS_REG_SP, 0x1F10000)
    uc.reg_write(UC_MIPS_REG_RA, RETURN)
    touched, writes, mocked, last = set(), [0], [], [None]
    def write(_uc, _access, address, size, _value, _user):
        if 0x1F00000 <= address < 0x1F20000:
            return
        writes[0] += 1
        touched.update(range(address, address + size))
    def syscall(machine, address, _size, _user):
        mocked.append({'address': f'0x{address:08X}', 'number': machine.reg_read(UC_MIPS_REG_V1) & 0xFFFFFFFF})
        machine.reg_write(UC_MIPS_REG_V0, 0)
        machine.reg_write(UC_MIPS_REG_PC, address + 4)
    def track_code(_machine, address, _size, _user):
        last[0] = address
    uc.hook_add(UC_HOOK_MEM_WRITE, write)
    uc.hook_add(UC_HOOK_CODE, track_code)
    uc.hook_add(UC_HOOK_CODE, syscall, begin=SYSTEM_CALL, end=SYSTEM_CALL)
    failure = None
    try:
        uc.emu_start(START, RETURN, count=3000000)
    except UcError as exc:
        failure = str(exc)
    finished = uc.reg_read(UC_MIPS_REG_PC) == RETURN
    if not finished and failure is None:
        failure = '执行步数上限或未到预期返回地址'
    changed = {i for i in touched if uc.mem_read(i, 1)[0] != source[i]}
    result = {'savestate_sha256': hashlib.sha256(archive).hexdigest(),
              'elf_sha256': hashlib.sha256(elf).hexdigest(), 'mocked_system_calls': mocked,
              'returned': finished, 'failure': failure,
              'last_instruction': f'0x{last[0]:08X}' if last[0] is not None else None,
              'write_events': writes[0], 'touched_bytes': len(touched), 'changed_bytes': len(changed),
              'written_ranges': spans(touched), 'changed_ranges': spans(changed),
              'scope': '只在已有快照内存副本运行该函数；系统调用 0x2059F4 假设成功，无实际系统或记忆卡操作。结果不能代表真实存档副作用或新游戏流程。'}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
        f.write('\n')
    print('returned', finished, 'last', result['last_instruction'], 'failure', failure,
          'writes', writes[0], 'touched', len(touched), 'changed', len(changed), 'mocked', len(mocked))
    print('output:', args.output)


if __name__ == '__main__':
    main()
