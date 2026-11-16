"""隔离执行原选项处理器的组装与结果写回；界面绘制和交互以桩代替。"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
from zipfile import ZipFile

from unicorn import Uc, UC_ARCH_MIPS, UC_HOOK_CODE, UC_MODE_LITTLE_ENDIAN, UC_MODE_MIPS64
from unicorn.mips_const import (UC_CPU_MIPS64_20KC, UC_MIPS_REG_A0, UC_MIPS_REG_GP,
                                UC_MIPS_REG_PC, UC_MIPS_REG_RA, UC_MIPS_REG_SP, UC_MIPS_REG_V0)
from mac_progress_snapshot import EE_SIZE
from 检查即时存档表 import elf_gp
from mac_reader import ROOT
import MAC_命令表提取 as common
import 状态字证据 as evidence

START, END = 0x11ABF8, 0x1FF0000
SCRIPT, CONTEXT, SCRIPT_CTX, STACK = 0x1E00000, 0x1F40000, 0x1F41000, 0x1FD0000
SELECTION = 0x3878
STUBS = {0x1058A8, 0x115D38, 0x128328, 0x106668, 0x1280D0, 0x1282F8,
         0x115E60, 0x123070, 0x122D18, 0x128340, 0x1283C8, 0x117DC0,
         0x117760, 0x116AD0, 0x117920, 0x1161C0}


def u32(uc, address):
    return int.from_bytes(uc.mem_read(address, 4), 'little')


def put32(uc, address, value):
    uc.mem_write(address, struct.pack('<I', value))


def invoke(uc):
    uc.reg_write(UC_MIPS_REG_A0, CONTEXT)
    uc.reg_write(UC_MIPS_REG_RA, END)
    uc.emu_start(START, END, count=100000)
    if uc.reg_read(UC_MIPS_REG_PC) != END:
        raise ValueError('选项函数没有正常返回')


def run(source, gp, script, selected, expected_labels, expected_rows, *, selection=SELECTION,
        comparison_input=None):
    uc = Uc(UC_ARCH_MIPS, UC_MODE_MIPS64 | UC_MODE_LITTLE_ENDIAN)
    uc.ctl_set_cpu_model(UC_CPU_MIPS64_20KC)
    uc.mem_map(0, EE_SIZE)
    uc.mem_write(0, source)
    uc.mem_write(SCRIPT, script)
    uc.reg_write(UC_MIPS_REG_GP, gp)
    uc.reg_write(UC_MIPS_REG_SP, STACK)
    state = u32(uc, gp - 0x6D44)
    ui = u32(uc, gp - 0x6ED8)
    if ui != state + 0x3B7D4:
        raise ValueError('本快照 UI 指针与预期关系不符')
    uc.mem_write(state + 0x479, b'\x00')
    uc.mem_write(state + 0x4C5, b'\x01')
    uc.mem_write(state + 0x47D, b'\x00')
    uc.mem_write(ui + 7, b'\x00')
    uc.mem_write(CONTEXT, bytes(0x100))
    uc.mem_write(SCRIPT_CTX, bytes(0x100))
    put32(uc, CONTEXT + 0x44, SCRIPT_CTX)
    put32(uc, SCRIPT_CTX + 8, SCRIPT + selection)
    put32(uc, SCRIPT_CTX + 12, SCRIPT)
    labels = []
    calls = []

    def hook(machine, address, _size, _user):
        if address in STUBS:
            calls.append(f'0x{address:08X}')
            if address == 0x128328:
                pointer = machine.reg_read(UC_MIPS_REG_A0) & 0xFFFFFFFF
                raw = bytearray()
                for i in range(128):
                    char = machine.mem_read(pointer + i, 1)[0]
                    if not char:
                        break
                    raw.append(char)
                else:
                    raise ValueError('选项文本没有结束符')
                labels.append(raw.decode('cp932'))
            machine.reg_write(UC_MIPS_REG_V0, 1 if address == 0x1282F8 else 0)
            machine.reg_write(UC_MIPS_REG_PC, machine.reg_read(UC_MIPS_REG_RA))

    uc.hook_add(UC_HOOK_CODE, hook)
    condition_word = None
    if comparison_input is not None:
        uc.mem_write(state + 0x278, struct.pack('<h', comparison_input))
        put32(uc, SCRIPT_CTX + 8, SCRIPT + 0x24A4)
        steps = 0
        while u32(uc, SCRIPT_CTX + 8) != SCRIPT + selection:
            offset = u32(uc, SCRIPT_CTX + 8) - SCRIPT
            handler = {0x24A4: evidence.CALC_HANDLER, 0x24AC: evidence.IF_HANDLER,
                       0x24BC: evidence.CALC_HANDLER}.get(offset)
            if handler is None or steps >= 3:
                raise ValueError(f'条件跳转未到达第三组选项: {offset:#x}')
            uc.reg_write(UC_MIPS_REG_A0, CONTEXT)
            uc.reg_write(UC_MIPS_REG_RA, END)
            uc.emu_start(handler, END, count=100000)
            if uc.reg_read(UC_MIPS_REG_PC) != END:
                raise ValueError('计算或比较处理函数没有正常返回')
            steps += 1
        condition_word = int.from_bytes(uc.mem_read(state + 0x240, 2), 'little', signed=True)
    invoke(uc)
    count = uc.mem_read(ui + 7, 1)[0]
    row_values = [u32(uc, ui + 0x24 + 44 * i) for i in range(count)]
    if labels != expected_labels or row_values != expected_rows:
        raise ValueError(f'选项表与 UI 索引不符: {labels}, {row_values}')
    if expected_rows:
        uc.mem_write(ui + 6, bytes([selected]))
        uc.mem_write(CONTEXT + 0x10, struct.pack('<H', 3))
        invoke(uc)
    result = int.from_bytes(uc.mem_read(state + 0x220 + 7 * 2, 2), 'little', signed=True)
    next_ip = u32(uc, SCRIPT_CTX + 8) - SCRIPT
    expected_value = expected_rows[selected] if expected_rows else 3
    if result != expected_value or next_ip != selection + 12:
        raise ValueError(f'选项结果不符: {selected=} {result=} {next_ip:#x}')
    return {'ui_selection_position': selected, 'display_labels': labels,
            'ui_row_values': row_values, 'written_operand': '0x6007', 'written_value': result,
            'next_ip': f'0x{next_ip:06X}', 'stub_calls': calls,
            **({'input_602c': comparison_input, 'condition_6010': condition_word}
               if comparison_input is not None else {})}


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--savestate', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--third-choice', action='store_true')
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
    for address, size in ((START, 0x608), (0x127F78, 0x7C), (0x115730, 0x208)):
        off = evidence.vaddr_to_offset(segs, address, size)
        if source[address:address + size] != elf[off:off + size]:
            raise ValueError(f'快照代码与 ELF 不一致: {address:#x}')
    script = (ROOT / '输出-保护边修复/MAC/MAC_001.bin').read_bytes()
    if args.third_choice:
        for address, size in ((evidence.CALC_HANDLER, 0x318), (evidence.IF_HANDLER, 0x130)):
            off = evidence.vaddr_to_offset(segs, address, size)
            if source[address:address + size] != elf[off:off + size]:
                raise ValueError(f'快照代码与 ELF 不一致: {address:#x}')
        script = (ROOT / '输出-保护边修复/MAC/MAC_003.bin').read_bytes()
        labels = ['ただの幼なじみ', '説明する必要はない', '…………']
        cases = []
        for value, indexes in ((19, [0, 1, 2]), (20, [0, 1, 2]), (21, [1, 2])):
            case = run(source, elf_gp(elf), script, 0, [labels[i] for i in indexes], indexes,
                       selection=0x24C4, comparison_input=value)
            if case['condition_6010'] != int(value < 21):
                raise ValueError(f'条件结果不符: {case}')
            cases.append(case)
        result = {'savestate_sha256': hashlib.sha256(archive).hexdigest(),
                  'elf_sha256': hashlib.sha256(elf).hexdigest(),
                  'script_sha256': hashlib.sha256(script).hexdigest(), 'cases': cases,
                  'scope': '隔离内存中执行 MAC_003 原赋值、比较和选项处理器。注入三种输入值，显示与输入辅助函数使用桩。'}
        with args.output.open('x', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
            f.write('\n')
        print('第三组选项：19、20 显示第 0 项，21 隐藏且点击首个可见项返回原序号 1')
        return
    if len(script) > CONTEXT - SCRIPT:
        raise ValueError('测试脚本超过隔离区')
    labels = ['謝る', 'ふざけろ！', '…………']
    cases = [run(source, elf_gp(elf), script, i, labels, [0, 1, 2]) for i in range(3)]
    for case in cases:
        case['scenario'] = '原脚本三项均显示'
    filtered = bytearray(script)
    table = struct.unpack_from('<I', filtered, SELECTION + 4)[0]
    struct.pack_into('<H', filtered, table + 12 + 8, 0)
    for i in range(2):
        case = run(source, elf_gp(elf), bytes(filtered), i, [labels[0], labels[2]], [0, 2])
        case['scenario'] = '构造：第 2 项显示条件为零'
        cases.append(case)
    filtered_all = bytearray(script)
    for i in range(3):
        struct.pack_into('<H', filtered_all, table + i * 12 + 8, 0)
    case = run(source, elf_gp(elf), bytes(filtered_all), None, [], [])
    case['scenario'] = '构造：三个选项显示条件均为零'
    cases.append(case)
    result = {'savestate_sha256': hashlib.sha256(archive).hexdigest(),
              'elf_sha256': hashlib.sha256(elf).hexdigest(),
              'script_sha256': hashlib.sha256(script).hexdigest(), 'cases': cases,
              'scope': '原选项处理函数及 UI 条目写入函数在内存副本中执行；UI 初始化、显示和辅助函数为桩，选择位置直接注入，并非原游戏实际点击或渲染对照。过滤选项两组为修改脚本数据构造的测试。'}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
        f.write('\n')
    print('Original instruction cases matched:', len(cases), 'output:', args.output)


if __name__ == '__main__':
    main()
