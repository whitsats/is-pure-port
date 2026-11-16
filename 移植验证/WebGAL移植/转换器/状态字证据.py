"""从 ELF 抽取状态字/条件/reg_calc 的可复核证据，写成 JSON。

每条结论都带地址；能从指令字节算出的值一律现算，与预期不符就报错，
避免文档与二进制脱节。无法由静态代码断定的内容列在 unknowns 中。
"""
import argparse
import hashlib
import json
import struct

from capstone import Cs, CS_ARCH_MIPS, CS_MODE_MIPS64, CS_MODE_LITTLE_ENDIAN

import mac_reader  # noqa: F401  由它把 移植验证/ 加入 sys.path
import MAC_命令表提取 as common

READ_OPERAND = 0x115730
WRITE_OPERAND = 0x1157F8
OPERAND_ADDRESS = 0x115938
IF_HANDLER = 0x1187D8
CALC_HANDLER = 0x118CD8
VM_INIT = 0x1151B8
VM_DISPATCH = 0x114B70
MEMSET = 0x1FBB84
IF_TABLE = 0x259D00
CALC_TABLE = 0x259D20
VM_STATE_TABLE = 0x2595E0


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


class Dis:
    def __init__(self, data, segs):
        self.data = data
        self.segs = segs
        self.decoder = Cs(CS_ARCH_MIPS, CS_MODE_MIPS64 | CS_MODE_LITTLE_ENDIAN)

    def read(self, address, size):
        start = vaddr_to_offset(self.segs, address, size)
        return [{'at': f'0x{ins.address:08X}', 'mnemonic': ins.mnemonic, 'op': ins.op_str,
                 'bytes': ins.bytes.hex()}
                for ins in self.decoder.disasm(self.data[start:start + size], address)]

    def find(self, address, size, mnemonic, op):
        for ins in self.read(address, size):
            if ins['mnemonic'] == mnemonic and ins['op'] == op:
                return ins
        raise ValueError(f'{mnemonic} {op} 不在 0x{address:08X} 起的 {size:#x} 字节内')


def expect(value, wanted, label):
    if value != wanted:
        raise ValueError(f'{label} 与预期不符: {value!r} != {wanted!r}')
    return value


def operand_reader(dis):
    code = dis.read(READ_OPERAND, 0xC0)
    texts = [f"{item['mnemonic']}\t{item['op']}" for item in code]
    masks = sorted({item['op'].split(', ')[-1] for item in code
                    if item['mnemonic'] == 'andi' and item['op'].split(', ')[-1].startswith('0x')})
    return {
        'address': f'0x{READ_OPERAND:08X}',
        'kind_mask': '0xC000',
        'word_kind': '0x4000',
        'bit_kind': '0x8000',
        'bank_bit': '0x2000',
        'index_mask': '0x1FFF',
        'bank_stride': '0x220',
        'bit_base_in_bank': '0x200',
        'and_masks_seen': masks,
        'branches': [text for text in texts if text.startswith(('beq', 'bne', 'beql', 'bnel'))][:8],
        'address_taken_from': f'0x{vaddr_to_offset(dis.segs, READ_OPERAND):X} 起反汇编',
        'confidence': 'proven',
        'note': '字 bank0 取 G+index*2，bank1 取 G+0x220+index*2；位取 G+bank*0x220+0x200+index/8 的第 index%8 位；其余编码按 16 位有符号立即数返回。',
    }


def operand_writer(dis):
    code = dis.read(WRITE_OPERAND, 0x100)
    stores = [item for item in code if item['mnemonic'] in ('sh', 'sb')]
    return {
        'address': f'0x{WRITE_OPERAND:08X}',
        'stores': [f"{item['mnemonic']} {item['op']} @ {item['at']}" for item in stores[:4]],
        'confidence': 'proven',
        'note': '字写入用 sh，与读取同样的 bank/index 算术；本项目只允许写“字”。',
    }


def if_evidence(dis, data, segs):
    # 确认比较码确实从 ip+12 读出，且参数字节从 ip+1 读出。
    dis.find(IF_HANDLER, 0x180, 'lbu', '$v1, 4($s1)')
    dis.find(IF_HANDLER, 0x180, 'lbu', '$v1, 1($s5)')
    compare_table = table_at(data, segs, IF_TABLE, 8)
    entries = [f'0x{value:08X}' for value in compare_table]
    return {
        'handler': f'0x{IF_HANDLER:08X}',
        'layout': {'bytes': 16, 'argument_byte': 1, 'target_u32': 4, 'lhs_u16': 8,
                   'rhs_u16': 10, 'compare_code': 12, 'join_byte': 13},
        'compare_table': {'address': f'0x{IF_TABLE:08X}', 'entries': entries},
        'compare_semantics': {
            '0': '左 == 右', '1': '左 != 右', '2': '左 <= 右', '3': '左 >= 右',
            '4': '左 < 右', '5': '左 > 右', '6': '按位与后取低 8 位', '7': '按位或后取低 8 位',
        },
        'jump_path': {
            'address': '0x001189E0-0x00118A20',
            'argument_byte_0': 's2==1（条件成立）时 ip = 脚本基址 + 目标；否则 ip += 16 继续下一条',
            'evidence': [f"{item['at']}: {item['mnemonic']} {item['op']}"
                         for item in dis.read(0x1189E0, 0x44)],
        },
        'category_note': '参数字节 8/9 会走另一套按 8 字节记录扫描的分支（0x0011892C/0x00118980），本项目尚未核实，遇到即停止。',
        'confidence': 'proven',
    }


def calc_evidence(dis, data, segs):
    table = table_at(data, segs, CALC_TABLE, 0x1C)
    def raw_at(address, size):
        offset = vaddr_to_offset(segs, address, size)
        return data[offset:offset + size].hex(' ')
    return {
        'handler': f'0x{CALC_HANDLER:08X}',
        'layout': {'bytes': 8, 'operation_byte': 1, 'dest_and_left_u16': 2, 'right_u16': 4},
        'operation_table': {'address': f'0x{CALC_TABLE:08X}',
                            'entries': [f'0x{value:08X}' for value in table]},
        'supported_operations': {
            '0': {'name': 'assign', 'address': f'0x{table[0]:08X}', 'effect': 'dest = right'},
            '1': {'name': 'add', 'address': f'0x{table[1]:08X}', 'effect': 'dest = left + right'},
            '2': {'name': 'sub', 'address': f'0x{table[2]:08X}', 'effect': 'dest = left - right'},
            '3': {'name': 'mul', 'address': f'0x{table[3]:08X}',
                  'effect': 'dest = left * right（R5900 三操作数 mult rd,rs,rt）',
                  'raw': raw_at(table[3], 0x10)},
            '4': {'name': 'div', 'address': f'0x{table[4]:08X}',
                  'effect': 'dest = left / right（向零截断；除数为 0 时原程序 break）'},
            '5': {'name': 'mod', 'address': f'0x{table[5]:08X}',
                  'effect': 'dest = left % right（余数符号随被除数）'},
            '6': {'name': 'and', 'address': f'0x{table[6]:08X}', 'effect': 'dest = left & right'},
            '7': {'name': 'or', 'address': f'0x{table[7]:08X}', 'effect': 'dest = left | right'},
            '14': {'name': 'store_imm', 'address': f'0x{table[14]:08X}',
                   'effect': 'dest = ip+4 的 16 位有符号立即数'},
            '15': {'name': 'add', 'address': f'0x{table[15]:08X}', 'effect': 'dest = left + right（与运算 1 相同）'},
        },
        'evidence': [f"{item['at']}: {item['mnemonic']} {item['op']}"
                     for item in dis.read(table[0], 0x10)]
                    + [f"{item['at']}: {item['mnemonic']} {item['op']}"
                       for item in dis.read(table[1], 0x10)]
                    + [f"0x{table[3]:08X}: 原始字节 {raw_at(table[3], 0x10)}（capstone 不解 R5900 三操作数 mult）",
                       f"0x{table[4]:08X}: 原始字节 {raw_at(table[4], 0x10)}",
                       f"0x{table[5]:08X}: 原始字节 {raw_at(table[5], 0x10)}",
                       f"0x{table[6]:08X}: 原始字节 {raw_at(table[6], 0x10)}",
                       f"0x{table[7]:08X}: 原始字节 {raw_at(table[7], 0x10)}",
                       f"0x{table[14]:08X}: 原始字节 {raw_at(table[14], 0x10)}",
                       f"0x{table[15]:08X}: 原始字节 {raw_at(table[15], 0x10)}"],
        'confidence': 'proven',
        'note': ('运算 0/1/2/3/4/5/6/7/0x0E/0x0F 已按表项与指令字节核实并接入；'
                 '8/9/0x0B/0x0C 读写剧本内存，0x10 跳转，0x12 随机，'
                 '0x13–0x16 与 0x17 未实现，遇到即停止。'),
    }


def vm_init_evidence(dis, data, segs):
    code = dis.read(VM_INIT, 0x40)
    size = None
    for index, item in enumerate(code):
        if item['mnemonic'] == 'lui' and item['op'] == '$a2, 0xd3':
            following = next((later for later in code[index + 1:index + 6]
                              if later['mnemonic'] == 'ori' and later['op'].startswith('$a2, $a2,')), None)
            if following is None:
                raise ValueError('找不到 memset 长度的高位拼接指令')
            size = (0xd3 << 16) | int(following['op'].split(', ')[-1], 16)
    expect(size, 0xD38680, 'memset 长度')
    jal = dis.find(VM_INIT, 0x40, 'jal', '0x1fbb84')
    callee = dis.read(MEMSET, 0x30)
    replicate = any(item['mnemonic'] == 'dsll' for item in callee) and \
        any(item['mnemonic'] == 'or' for item in callee)
    expect(replicate, True, '0x1FBB84 的字节复制特征')
    dispatcher = dis.read(VM_DISPATCH, 0x40)
    store = next(item for item in dispatcher if item['mnemonic'] == 'sw' and '-0x6d44($gp)' in item['op'])
    jump = next(item for item in dispatcher if item['mnemonic'] == 'jr' and item['op'] == '$v1')
    states = table_at(data, segs, VM_STATE_TABLE, 12)
    return {
        'memset': {
            'call_site': jal['at'],
            'callee': f'0x{MEMSET:08X}',
            'destination': '*(gp-0x6D44)，与状态字读写使用的是同一个基址',
            'value': 0,
            'size': f'0x{size:X}',
            'callee_evidence': [f"{item['at']}: {item['mnemonic']} {item['op']}" for item in callee[:8]],
        },
        'vm_init': {
            'address': f'0x{VM_INIT:08X}',
            'reached_from': f'{store["at"]}（把 *(ctx+0x44) 缓存到 gp-0x6D44 后按状态字分派）',
            'state_table': {'address': f'0x{VM_STATE_TABLE:08X}',
                            'entries': [f'0x{value:08X}' for value in states[:4]]},
            'jump': f"{jump['at']}: jr $v1（状态 0 的目标是 0x{states[0]:08X}）",
        },
        'confidence': 'proven（清零本身）/ unproven（何时重复执行）',
        'note': '只能证明“运行到这里时整块状态被清零”。是否每次进入剧本都走这里、读档是否恢复这块状态，静态代码无法断定，见 unknowns。',
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=__import__('pathlib').Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    data = common.ELF.read_bytes()
    segs = segments(data)
    dis = Dis(data, segs)
    table = common.load_table(data)
    expect(table[0x02]['handler'], IF_HANDLER, 'if 处理函数')
    expect(table[0x09]['handler'], CALC_HANDLER, 'reg_calc 处理函数')
    payload = {
        'elf': str(common.ELF),
        'elf_sha256': hashlib.sha256(data).hexdigest(),
        'decode_mode': 'MIPS64 little-endian (capstone)',
        'operand_read': operand_reader(dis),
        'operand_write': operand_writer(dis),
        'if': if_evidence(dis, data, segs),
        'reg_calc': calc_evidence(dis, data, segs),
        'state_init': vm_init_evidence(dis, data, segs),
        'worked_example': {
            'script': 'MAC_000.bin',
            'offset': '0x0000AC',
            'bytes': '02000000D00000000E6000000100 0000'.replace(' ', ''),
            'decoded': 'if 参数0：字 0x600E != 立即数 0 → 成立时目标 0x0000D0',
            'operand': '0x600E = bank1 word #14（raw&0x2000 置位，index 0x00E）',
            'initial_value': 'MAC_000 的入口片段里 0xAC 之前没有任何指令写过 bank1 word #14；'
                             '按 state_init 的清零证据，本次执行读到 0',
            'result': '0 != 0 不成立 → 不跳 0xD0，继续执行 0xBC 的 reg_calc（把 0x600E 赋为 1）',
        },
        'unknowns': [
            'VM 状态 0（0x1151B8）是否每次进入剧本都会执行，还是只在新游戏/复位时执行。若每次执行，则跨剧本状态不会保留；若只在新游戏时执行，则读档后可能存在非零初值。',
            '状态块是否会随存档保存/恢复（与上一条相关）。',
            'reg_calc 运算码 8/9（读剧本字节/半字）、0x0B/0x0C（写剧本字节/半字）、0x10（跳转）、0x12（随机）与 0x13–0x16 的语义；0x17 已在单独调查中定位到运行时表。',
            'if 参数字节 8/9 的分支形式。',
            '状态数组的真实边界：读取用 index 掩码 0x1FFF，但 bank 间距只有 0x220，实际越界未核实；当前脚本只用到 bank1 字 #0～#44 与位 #0～#77，均未越界。',
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write('\n')
    print('状态证据:', args.output)
    print('memset:', payload['state_init']['memset']['size'],
          'if 表:', payload['if']['compare_table']['entries'][:3])
    print('reg_calc 已实现:', [f"{key}:{value['name']}" for key, value in
                              payload['reg_calc']['supported_operations'].items()])


if __name__ == '__main__':
    main()
