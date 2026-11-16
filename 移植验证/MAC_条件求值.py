"""MAC 条件的保守求值子集；未知模式和未初始化状态均显式报错。"""
from dataclasses import dataclass, field
import struct


@dataclass
class State:
    words: dict = field(default_factory=dict)
    bits: dict = field(default_factory=dict)


def operand(raw, state):
    """依据 ELF 0x115730 读取已研究的 16 位操作数类型。"""
    raw &= 0xFFFF
    kind, bank, index = raw & 0xC000, 1 if raw & 0x2000 else 0, raw & 0x1FFF
    if kind == 0x4000:
        value = state.words[(bank, index)]
        if not -32768 <= value <= 32767:
            raise ValueError("word value outside signed 16-bit range")
        return value
    if kind == 0x8000:
        value = state.bits[(bank, index)]
        if value not in (0, 1):
            raise ValueError("bit value must be 0 or 1")
        return value
    return raw if raw < 0x8000 else raw - 0x10000


def evaluate_if(instruction, state):
    """只处理 16 字节、单条件、模式 0 的已观察形式。"""
    if len(instruction) != 16 or instruction[0] != 0x02:
        raise ValueError("Expected a 16-byte if instruction")
    if instruction[1] != 0 or instruction[13] != 0:
        raise NotImplementedError("Unsupported if mode or combined condition")
    target = struct.unpack_from("<I", instruction, 4)[0]
    lhs, rhs = struct.unpack_from("<HH", instruction, 8)
    compare = instruction[12]
    left, right = operand(lhs, state), operand(rhs, state)
    functions = {0: lambda a, b: a == b, 1: lambda a, b: a != b,
                 3: lambda a, b: a >= b, 4: lambda a, b: a < b,
                 5: lambda a, b: a > b}
    if compare not in functions:
        raise NotImplementedError(f"Unsupported comparison {compare:#x}")
    return functions[compare](left, right), target
