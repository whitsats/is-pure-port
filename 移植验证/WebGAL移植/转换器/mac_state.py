"""按原程序实现的状态字与表达式子集。

对应原程序：
- 操作数读取 `0x00115730`、写入 `0x001157F8`、取地址 `0x00115938`；
- `if` 处理函数 `0x001187D8`，比较码分派表 `0x00259D00`；
- `reg_calc` 处理函数 `0x00118CD8`，运算分派表 `0x00259D20`；
- 状态块清零 `memset` 调用点 `0x001151E0`（目标 = `*(gp-0x6D44)`，值 0，长度 `0x0D38680`）。

地址布局（同 `0x115730` / `0x1157F8` 的取址算术）：
- 字 bank0：`G + index*2`；字 bank1：`G + 0x220 + index*2`；
- 位 bank0：`G + 0x200 + index//8` 的第 `index%8` 位；位 bank1：`G + 0x420 + index//8`；
- 其余编码是立即数，按 16 位有符号解释。

只实现已核实子集：字、位、立即数；`if` 比较码 0～5；`reg_calc` 运算
0（赋值）、1/0x0F（加）、2（减）、3（乘）、4（商）、5（余数）、6（按位与）、
7（按位或）、0x0E（写立即数）。其它编码或运算一律抛 `UnsupportedCommand`，
由调用方记录为停止原因。
"""
from dataclasses import dataclass, field
import struct

BANK_STRIDE = 0x220
WORD_BYTES = 0x200
BIT_OFFSET = 0x200
KIND_WORD = 0x4000
KIND_BIT = 0x8000
BANK_BIT = 0x2000
INDEX_MASK = 0x1FFF

# 0x259D00 分派目标与 0x1187D8 中的指令顺序对应，见 数据/状态字ELF证据.json。
COMPARISONS = {
    0: ('==', lambda left, right: left == right),
    1: ('!=', lambda left, right: left != right),
    2: ('<=', lambda left, right: left <= right),
    3: ('>=', lambda left, right: left >= right),
    4: ('<', lambda left, right: left < right),
    5: ('>', lambda left, right: left > right),
}
CALC_OPS = {
    0: ('assign', lambda left, right: right),
    1: ('add', lambda left, right: left + right),
    2: ('sub', lambda left, right: left - right),
    # R5900 的三操作数 mult rd,rs,rt（0x118D90 的 0x02302818）；结果在低 32 位，
    # 随后由 0x1157F8 的 sh 截成 16 位。
    3: ('mul', lambda left, right: left * right),
    4: ('div', None),
    5: ('mod', None),
    6: ('and', lambda left, right: left & right),
    7: ('or', lambda left, right: left | right),
    0x0F: ('add', lambda left, right: left + right),
}
CALC_STORE_IMMEDIATE = 0x0E


class UnsupportedCommand(ValueError):
    """原程序里存在、但本项目尚未核实的行为。"""


def to_s16(value):
    value &= 0xFFFF
    return value - 0x10000 if value & 0x8000 else value


@dataclass
class State:
    """稀疏状态字节，未写过的地址按 0 读取；字和位共享地址空间。"""

    memory_bytes: dict = field(default_factory=dict)
    written: set = field(default_factory=set)

    def address_of(self, raw):
        """返回 (kind, bank, index)；无法归类时抛 UnsupportedCommand。"""
        raw &= 0xFFFF
        kind = raw & 0xC000
        bank = 1 if raw & BANK_BIT else 0
        index = raw & INDEX_MASK
        if kind == KIND_WORD:
            return 'word', bank, index
        if kind == KIND_BIT:
            return 'bit', bank, index
        # 0x115744/0x115750 只比较 0x4000 与 0x8000；其余（含 0xC000）在 0x115758 走
        # `b 0x1157ec` + `move $a1, $a0`，直接返回已经符号扩展的原值，即立即数。
        return 'value', bank, index

    def offset_of(self, kind, bank, index):
        """按原程序算术算出的块内偏移，用于证明两处引用不重叠。"""
        base = bank * BANK_STRIDE
        if kind == 'word':
            return base + index * 2
        if kind == 'bit':
            return base + BIT_OFFSET + index // 8
        raise UnsupportedCommand('立即数没有存储地址')

    def read(self, raw):
        kind, bank, index = self.address_of(raw)
        if kind == 'value':
            return to_s16(raw)  # 0x115730 开头就是 sll 16 / sra 16
        offset = self.offset_of(kind, bank, index)
        if kind == 'word':
            return to_s16(self.memory_bytes.get(offset, 0) | (self.memory_bytes.get(offset + 1, 0) << 8))
        return (self.memory_bytes.get(offset, 0) >> (index % 8)) & 1

    def write(self, raw, value):
        kind, bank, index = self.address_of(raw)
        if kind == 'value':
            raise UnsupportedCommand(f'立即数不能作为写入目的 {raw:#06x}')
        old = self.read(raw)
        offset = self.offset_of(kind, bank, index)
        if kind == 'word':
            value = to_s16(value)
            self.memory_bytes[offset] = value & 0xFF
            self.memory_bytes[offset + 1] = (value >> 8) & 0xFF
        else:
            value &= 1
            mask = 1 << (index % 8)
            current = self.memory_bytes.get(offset, 0)
            self.memory_bytes[offset] = (current | mask) if value else (current & ~mask)
        self.written.add((bank, index))
        return old, value

    def read_context_u32(self, offset):
        if not isinstance(offset, int) or offset < 0:
            raise UnsupportedCommand('无效上下文偏移')
        return sum(self.memory_bytes.get(offset + i, 0) << (8 * i) for i in range(4))

    def read_context_u16(self, offset):
        if not isinstance(offset, int) or offset < 0:
            raise UnsupportedCommand('无效上下文偏移')
        return self.memory_bytes.get(offset, 0) | (self.memory_bytes.get(offset + 1, 0) << 8)

    def write_context_u8(self, offset, value):
        if not isinstance(offset, int) or offset < 0:
            raise UnsupportedCommand('无效上下文偏移')
        self.memory_bytes[offset] = value & 0xFF

    def write_context_u16(self, offset, value):
        if not isinstance(offset, int) or offset < 0:
            raise UnsupportedCommand('无效上下文偏移')
        for i in range(2):
            self.memory_bytes[offset + i] = (value >> (8 * i)) & 0xFF

    def write_context_u32(self, offset, value):
        if not isinstance(offset, int) or offset < 0:
            raise UnsupportedCommand('无效上下文偏移')
        for i in range(4):
            self.memory_bytes[offset + i] = (value >> (8 * i)) & 0xFF

    def describe(self, raw):
        kind, bank, index = self.address_of(raw)
        if kind == 'value':
            return {'kind': 'value', 'raw': f'0x{raw & 0xFFFF:04X}', 'value': to_s16(raw)}
        return {'kind': kind, 'bank': bank, 'index': index, 'raw': f'0x{raw & 0xFFFF:04X}',
                'offset': self.offset_of(kind, bank, index)}


def parse_if(raw):
    """解析 16 字节 if：参数字节必须为 0（单条件），返回目标、左右操作数与比较码。"""
    if len(raw) != 16 or raw[0] != 0x02:
        raise UnsupportedCommand('不是 16 字节 if')
    if raw[1] != 0:
        raise UnsupportedCommand(f'未核实的 if 参数 {raw[1]:#04x}')
    if raw[13] != 0:
        raise UnsupportedCommand('未核实的多条件连接')
    target = struct.unpack_from('<I', raw, 4)[0]
    lhs, rhs = struct.unpack_from('<HH', raw, 8)
    code = raw[12]
    if code not in COMPARISONS:
        raise UnsupportedCommand(f'未核实的比较码 {code:#04x}')
    return target, lhs, rhs, code


def evaluate_if(raw, state):
    """返回 (是否成立, 目标偏移, 说明)。"""
    target, lhs, rhs, code = parse_if(raw)
    left, right = state.read(lhs), state.read(rhs)
    name, function = COMPARISONS[code]
    result = bool(function(left, right))
    detail = {'target': target, 'code': code, 'operator': name,
              'lhs': state.describe(lhs), 'lhs_value': left,
              'rhs': state.describe(rhs), 'rhs_value': right,
              'result': result}
    return result, target, detail


REG_CALC_17_NOTE = ('运算 0x17 进入 0x00118FD0 的全局位表/场景表路径，'
                    '运行时表内容未核实，不能安全执行')


def parse_reg_calc(raw):
    """解析 8 字节 reg_calc：参数字节是运算码，+2 为目的/左操作数，+4 为右操作数；
    运算 0x0E 时 +4 是 16 位有符号立即数。"""
    if len(raw) != 8 or raw[0] != 0x09:
        raise UnsupportedCommand('不是 8 字节 reg_calc')
    op = raw[1]
    if op == 0x17:
        raise UnsupportedCommand(REG_CALC_17_NOTE)
    if op not in CALC_OPS and op != CALC_STORE_IMMEDIATE:
        raise UnsupportedCommand(f'未核实的 reg_calc 运算 {op:#04x}')
    left, right = struct.unpack_from('<HH', raw, 2)
    return op, left, right


def _signed_div(left, right):
    if right == 0:
        raise UnsupportedCommand('reg_calc 的除数为 0；原程序在 0x00118DAC/0x00118F2C 走 break')
    quotient = abs(left) // abs(right)
    return -quotient if (left < 0) != (right < 0) else quotient


def _signed_mod(left, right):
    return left - _signed_div(left, right) * right


CALC_OPS[4] = ('div', _signed_div)
CALC_OPS[5] = ('mod', _signed_mod)


def apply_reg_calc(raw, state):
    """执行一条 reg_calc，返回报告条目。"""
    if len(raw) == 8 and raw[:2] == b'\x09\x17':
        handler = getattr(state, 'apply_reg17', None)
        if handler is not None:
            return handler(raw)
    op, dst, src = parse_reg_calc(raw)
    if op == CALC_STORE_IMMEDIATE:
        old, new = state.write(dst, src)
        return {'operation': 'store_imm', 'dest': state.describe(dst),
                'source': {'kind': 'immediate', 'raw': f'0x{src:04X}', 'value': to_s16(src)},
                'before': old, 'after': new,
                'note': '运算 0x0E 从 ip+4 取 16 位有符号立即数写入目的操作数（0x118E88）'}
    name, function = CALC_OPS[op]
    left, right = state.read(dst), state.read(src)
    old, new = state.write(dst, function(left, right))
    return {'operation': name, 'dest': state.describe(dst), 'source': state.describe(src),
            'before': old, 'after': new,
            'note': '运算与取址顺序按 reg_calc 处理函数 0x118CD8 的实现'}
