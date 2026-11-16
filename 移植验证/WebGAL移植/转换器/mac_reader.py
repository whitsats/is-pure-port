"""保守读取 MAC 的第零入口及其后线性指令，不推断其他入口或数据区。"""
from dataclasses import dataclass
from pathlib import Path
import struct
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import MAC_命令表提取 as common


@dataclass(frozen=True)
class Command:
    offset: int
    opcode: int
    name: str
    data: bytes


def read_linear_range(data, start, boundary, table):
    """按调用者提供的范围解析；不将范围本身当作已验证的代码。"""
    if not isinstance(start, int) or not isinstance(boundary, int) or not 0 <= start < boundary <= len(data):
        raise ValueError('无效的代码范围')
    pos = start
    commands = []
    while pos < boundary:
        opcode = data[pos]
        if opcode >= len(table):
            raise ValueError(f'未知操作码 {opcode:#x} @ {pos:#x}')
        info = table[opcode]
        length = info['bytes']
        if length <= 0 or pos + length > boundary:
            raise ValueError(f'不支持的长度或越过边界 @ {pos:#x}')
        commands.append(Command(pos, opcode, info['name'], data[pos:pos + length]))
        pos += length
    return commands


def read_entry_zero(data, boundary, table):
    if len(data) < 12 or data[:8] != bytes.fromhex('09 11 00 60 08 00 00 00'):
        raise ValueError('未识别的 MAC 入口指令')
    if not isinstance(boundary, int) or not 12 <= boundary <= len(data):
        raise ValueError('无效的候选数据边界')
    entry = struct.unpack_from('<I', data, 8)[0]
    if not 12 <= entry < boundary or entry % 4:
        raise ValueError(f'入口不在有效范围内: {entry:#x}')
    return entry, read_linear_range(data, entry, boundary, table)


def load_table():
    return common.load_table(common.ELF.read_bytes())
