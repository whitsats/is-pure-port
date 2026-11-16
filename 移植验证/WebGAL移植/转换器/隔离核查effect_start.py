"""在即时存档的内存副本上隔离执行一条真实 effect_start 指令。

只替换派发器刷新函数；构造的指令上下文不代表真实剧本到达该处的完整运行状态。
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
from zipfile import ZipFile

from unicorn import Uc, UC_ARCH_MIPS, UC_HOOK_CODE, UC_MODE_LITTLE_ENDIAN, UC_MODE_MIPS64
from unicorn.mips_const import (UC_CPU_MIPS64_20KC, UC_MIPS_REG_A0, UC_MIPS_REG_GP,
                                UC_MIPS_REG_PC, UC_MIPS_REG_RA, UC_MIPS_REG_SP, UC_MIPS_REG_V0)
from mac_reader import ROOT
from 检查即时存档表 import elf_gp
import MAC_命令表提取 as common

SCRIPT, CTX, VM, STACK, END = 0x1E00000, 0x1F40000, 0x1F41000, 0x1FD0000, 0x1FF0000
HANDLER, DISPATCH_REFRESH, STATE_SIZE = 0x11DDB8, 0x117DC0, 0x0D38680
RAW = bytes.fromhex('6a00010100004000f6ff000000000c000c000c000600020000000000000000000000000000000000')
WAIT_RAW = bytes.fromhex('6b00fc0100000000')
POLL_RAW = bytes.fromhex('6b00fd0000000000')


def probe_completion(machine, state):
    """Execute the original stop request, poll and frame callback with controlled particle counts."""
    record = state + 0x3F18C
    effect_mode = CTX + 0x200

    def read(address, count=4):
        return int.from_bytes(machine.mem_read(address, count), 'little')

    def put(address, value, count=4):
        machine.mem_write(address, value.to_bytes(count, 'little'))

    def call(address, context):
        machine.reg_write(UC_MIPS_REG_A0, context)
        machine.reg_write(UC_MIPS_REG_RA, END)
        machine.emu_start(address, END, count=100000)
        if machine.reg_read(UC_MIPS_REG_PC) != END:
            raise ValueError(f'原处理函数未返回: {address:#x}')

    def wait(raw, phase):
        machine.mem_write(SCRIPT, raw)
        put(VM + 8, SCRIPT)
        put(CTX + 0x10, phase, 2)
        call(0x11E110, CTX)
        return {'advance': read(VM + 8) - SCRIPT, 'phase': read(CTX + 0x10, 2),
                'busy': read(record + 0x10), 'type': read(record + 0x2C, 1)}

    def particle_status(uc, address, size, active):
        uc.reg_write(UC_MIPS_REG_V0, active)
        uc.reg_write(UC_MIPS_REG_PC, uc.reg_read(UC_MIPS_REG_RA))

    rows = []
    for mode, active, elapsed in [(1, 1, 0), (0, 0, 0), (0, 1, 0), (0, 1, 600)]:
        machine.mem_write(SCRIPT, RAW)
        put(VM + 8, SCRIPT)
        put(CTX + 0x10, 0, 2)
        call(HANDLER, CTX)
        request = wait(WAIT_RAW[:3] + bytes([mode]) + WAIT_RAW[4:], 0)
        first_poll = wait(POLL_RAW, 0)
        busy_poll = wait(POLL_RAW, 1)
        # The callback enters phase 100 when the record's stop request word is 1.
        callback_context = read(record + 4)
        put(callback_context + 0x44, record)
        put(callback_context + 0x10, 100, 2)
        put(record + 8, elapsed)
        put(record + 0xC, 0)
        hook = machine.hook_add(UC_HOOK_CODE, particle_status, active, begin=0x131D58, end=0x131D58)
        try:
            call(0x132140, callback_context)
        finally:
            machine.hook_del(hook)
        final_poll = wait(POLL_RAW, 1)
        rows.append({'stop_mode': mode, 'stub_particles_active': active, 'ticks_before_callback': elapsed,
                     'request': request, 'first_poll': first_poll, 'busy_poll': busy_poll,
                     'poll_after_callback': final_poll})
    return {'scope': '运行原 FC/FD 与类型 1 回调，替换粒子更新渲染函数 0x131D58 为指定的活动标志。',
            'rows': rows}


def ranges(before, after):
    changed = [i for i, (a, b) in enumerate(zip(before, after)) if a != b]
    output = []
    for i in changed:
        if not output or i != output[-1]['end']:
            output.append({'start': i, 'end': i + 1})
        else:
            output[-1]['end'] = i + 1
    return [{'offset': f"0x{x['start']:X}", 'length': x['end'] - x['start'],
             'before': before[x['start']:x['end']].hex(),
             'after': after[x['start']:x['end']].hex()} for x in output]


def inspect(savestate, completion=False):
    with ZipFile(savestate) as archive:
        source = archive.read('eeMemory.bin')
    elf = common.ELF.read_bytes()
    gp = elf_gp(elf)
    state = struct.unpack_from('<I', source, gp - 0x6D44)[0]
    if not 0 < state < state + STATE_SIZE <= len(source):
        raise ValueError('状态块范围越界')
    machine = Uc(UC_ARCH_MIPS, UC_MODE_MIPS64 | UC_MODE_LITTLE_ENDIAN)
    machine.ctl_set_cpu_model(UC_CPU_MIPS64_20KC)
    machine.mem_map(0, len(source))
    machine.mem_write(0, source)
    machine.mem_write(SCRIPT, RAW)
    machine.mem_write(CTX, bytes(0x100))
    machine.mem_write(VM, bytes(0x200))
    machine.mem_write(CTX + 0x44, struct.pack('<I', VM))
    machine.mem_write(VM + 8, struct.pack('<I', SCRIPT))
    for register, value in ((UC_MIPS_REG_GP, gp), (UC_MIPS_REG_SP, STACK),
                            (UC_MIPS_REG_A0, CTX), (UC_MIPS_REG_RA, END)):
        machine.reg_write(register, value)
    tracked = {0x131620: 0, 0x1316B8: 0, 0x1317F0: 0, 0x19D8D8: 0, DISPATCH_REFRESH: 0}

    def hook(uc, address, size, user):
        if address in tracked:
            tracked[address] += 1
        if address == DISPATCH_REFRESH:
            uc.reg_write(UC_MIPS_REG_PC, uc.reg_read(UC_MIPS_REG_RA))

    machine.hook_add(UC_HOOK_CODE, hook)
    machine.emu_start(HANDLER, END, count=100000)
    if machine.reg_read(UC_MIPS_REG_PC) != END:
        raise ValueError('处理函数未在步数上限内返回')
    after = bytes(machine.mem_read(state, STATE_SIZE))
    before = source[state:state + STATE_SIZE]
    ip = struct.unpack('<I', machine.mem_read(VM + 8, 4))[0]
    if ip != SCRIPT + len(RAW):
        raise ValueError(f'指令指针前进不符: {ip:#x}')
    start_calls = dict(tracked)
    for address in tracked:
        tracked[address] = 0
    machine.mem_write(SCRIPT + len(RAW), WAIT_RAW)
    machine.reg_write(UC_MIPS_REG_A0, CTX)
    machine.reg_write(UC_MIPS_REG_RA, END)
    machine.emu_start(0x11E110, END, count=100000)
    wait_pc = machine.reg_read(UC_MIPS_REG_PC)
    wait_ip = struct.unpack('<I', machine.mem_read(VM + 8, 4))[0]
    if wait_pc != END:
        raise ValueError('effect_wait 处理函数未返回')
    wait_after = bytes(machine.mem_read(state, STATE_SIZE))
    report = {'scope': '在存档内存副本构造上下文，隔离调用原处理函数；只替换派发器刷新，不代表真实到达该处的全路径。',
            'limitations': ['输入内存来自开场，非目标剧情位置；未对渲染、随机性和后续 effect_wait 做时序验证。',
                            '只比较原状态块的前后变化；相同值写入和状态块外写入不计。'],
            'savestate_sha256': hashlib.sha256(savestate.read_bytes()).hexdigest(),
            'elf_sha256': hashlib.sha256(elf).hexdigest(), 'raw_hex': RAW.hex(),
            'handler': f'0x{HANDLER:08X}', 'state_address': f'0x{state:08X}',
            'ip_advance': ip - SCRIPT, 'context_mode_after': struct.unpack('<H', machine.mem_read(CTX + 0x10, 2))[0],
            'calls': {f'0x{k:08X}': v for k, v in start_calls.items()}, 'changed_state_ranges': ranges(before, after),
            'effect_wait': {'raw_hex': WAIT_RAW.hex(), 'handler': '0x0011E110',
                            'ip_advance': wait_ip - (SCRIPT + len(RAW)),
                            'context_mode_after': struct.unpack('<H', machine.mem_read(CTX + 0x10, 2))[0],
                            'calls': {f'0x{k:08X}': v for k, v in tracked.items()},
                            'changed_state_ranges': ranges(after, wait_after)}}
    if completion:
        report['completion_probe'] = probe_completion(machine, state)
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--savestate', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--completion', action='store_true')
    args = parser.parse_args()
    result = inspect(args.savestate, completion=args.completion)
    with args.output.open('x', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
        f.write('\n')
    print('effect_start 处理函数返回；状态变化区间:', len(result['changed_state_ranges']), '报告:', args.output)


if __name__ == '__main__':
    main()
