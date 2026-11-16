"""从原 ELF 抽取消息窗指令处理函数的可复核事实，不推断未出现的字段含义。

输出只记录可直接由字节和反汇编验证的内容：
- 命令表条目（处理函数地址、长度、名称）；
- 处理函数内存取手柄状态位 0x2000 的指令位置；
- msg_disp2 的两级跳转表地址与入口；
- 处理函数内的直接调用目标；
- 每条消息窗指令的原始字节。
"""
import argparse
import hashlib
import json
import struct
from pathlib import Path

from capstone import Cs, CS_ARCH_MIPS, CS_MODE_MIPS64, CS_MODE_LITTLE_ENDIAN
import mac_reader  # noqa: F401  由它把 移植验证/ 加入 sys.path
import MAC_命令表提取 as common

WATCH = (0x12, 0x13, 0x1A, 0x1B, 0x60)
MAX_REGION = 0x800
PAD_LUI = ', 0xc5'
PAD_LOAD = '0x6508('
PAD_MASK = ', 0x2000'
CMD_TABLE_LOAD = 'lw\t$v1, -0x6270($v1)'
WIN_TABLE_LOAD = 'lw\t$v1, -0x6250($v1)'


def segments(data):
    header = struct.unpack_from('<16sHHIIIIIHHHHHH', data)
    phoff, phsize, phcount = header[5], header[9], header[10]
    return [struct.unpack_from('<8I', data, phoff + i * phsize) for i in range(phcount)]


def vaddr_to_offset(segs, address, size=4):
    for kind, offset, vaddr, _, filesz, _, _, _ in segs:
        if kind == 1 and vaddr <= address and address + size <= vaddr + filesz:
            return offset + address - vaddr
    raise ValueError(f'地址不在装载段内: {address:#x}')


def table_at(data, segs, address, count):
    return [struct.unpack_from('<I', data, vaddr_to_offset(segs, address + 4 * i))[0]
            for i in range(count)]


def find_table(instructions, load_text):
    """定位 `lui 0x26` … `lw v1, -0x6xxx(v1)` 组合，返回 0x260000-偏移 的表地址。"""
    for index, ins in enumerate(instructions):
        if ins.mnemonic != load_text.split('\t')[0] or ins.op_str != load_text.split('\t')[1]:
            continue
        for previous in reversed(instructions[max(0, index - 4):index]):
            if previous.mnemonic == 'lui' and ', 0x26' in previous.op_str:
                return 0x260000 + int(ins.op_str.split(', ')[1].split('(')[0], 16), ins.address
    return None, None


def scan(data, segs, table):
    decoder = Cs(CS_ARCH_MIPS, CS_MODE_MIPS64 | CS_MODE_LITTLE_ENDIAN)
    handlers = {row['handler']: row['name'] for row in table}
    boundaries = sorted(set(handlers))
    facts = {}
    for opcode in WATCH:
        row = table[opcode]
        start = row['handler']
        # 以命令表里下一个更高的处理函数地址作为区间上界，避免把相邻函数算进本函数。
        end = next((address for address in boundaries if address > start), start + MAX_REGION)
        end = min(end, start + MAX_REGION)
        code = data[vaddr_to_offset(segs, start, end - start):][:end - start]
        instructions = list(decoder.disasm(code, start))
        calls = [{'at': f'0x{ins.address:08X}', 'target': f'0x{int(ins.op_str, 16):08X}',
                  'name': handlers.get(int(ins.op_str, 16), '')}
                 for ins in instructions if ins.mnemonic == 'jal']
        pad = []
        for index, ins in enumerate(instructions):
            if ins.mnemonic == 'lui' and ins.op_str.endswith(PAD_LUI):
                window = instructions[index:index + 5]
                load = next((i for i in window if i.mnemonic == 'lw' and PAD_LOAD in i.op_str), None)
                if load is None:
                    continue
                register = load.op_str.split(',')[0].strip()
                if any(i.mnemonic == 'andi' and i.op_str.startswith(register) and i.op_str.endswith(PAD_MASK)
                       for i in window):
                    pad.append(f'0x{ins.address:08X}')
        command_table, command_load = find_table(instructions, CMD_TABLE_LOAD)
        window_table, window_load = find_table(instructions, WIN_TABLE_LOAD)
        facts[f'0x{opcode:02X}'] = {
            'name': row['name'],
            'bytes': row['bytes'],
            'handler': f'0x{start:08X}',
            'region': f'0x{start:08X}-0x{end:08X}',
            'instruction_count_in_window': len(instructions),
            'pad_bit_0x2000_reads': pad,
            'command_state_jump_table': None if command_table is None else {
                'address': f'0x{command_table:08X}',
                'loaded_at': f'0x{command_load:08X}',
                'entries': [f'0x{value:08X}' for value in table_at(data, segs, command_table, 8)]},
            'window_state_jump_table': None if window_table is None else {
                'address': f'0x{window_table:08X}',
                'loaded_at': f'0x{window_load:08X}',
                'entries': [f'0x{value:08X}' for value in table_at(data, segs, window_table, 10)]},
            'direct_calls': calls,
        }
    return facts


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    data = common.ELF.read_bytes()
    segs = segments(data)
    table = common.load_table(data)
    facts = scan(data, segs, table)
    payload = {
        'elf': str(common.ELF),
        'elf_sha256': hashlib.sha256(data).hexdigest(),
        'command_table_vaddr': f'0x{common.TABLE_VADDR:08X}',
        'decode_mode': 'MIPS64 little-endian (capstone)',
        'scope': '只记录字节级可复核事实；不据此认定参数含义、窗口状态编号语义或运行时顺序。',
        'opcodes': facts,
        'notes': [
            'pad_bit_0x2000_reads 表示处理函数窗口内向 0xC506508 读取 0x2000 位，通常对应一次按键判定，但未在真机确认。',
            'command_state_jump_table 是脚本指令自身 0x10 状态字段的分派表；window_state_jump_table 是消息窗 0x4E8 状态对应的分派表。',
            'direct_calls 只含 jal 直接调用，不含间接跳转。',
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write('\n')
    for key, value in facts.items():
        print(key, value['name'], value['handler'], 'pad', len(value['pad_bit_0x2000_reads']),
              'cmdtable', bool(value['command_state_jump_table']),
              'wintable', bool(value['window_state_jump_table']))
    print('输出:', args.output)


if __name__ == '__main__':
    main()
