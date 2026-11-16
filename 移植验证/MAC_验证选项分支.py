"""验证 MAC_001 的一处选择→寄存器→条件跳转，不执行完整游戏。"""
import json
import struct
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SCRIPT = ROOT / "输出-保护边修复" / "MAC" / "MAC_001.bin"
OUT = ROOT / "MAC_命令表" / "三选项分支验证.json"
SELECTION = 0x3878


def u16(data, offset):
    return struct.unpack_from("<H", data, offset)[0]


def u32(data, offset):
    return struct.unpack_from("<I", data, offset)[0]


def read_operand(raw, registers):
    # Verified subset: local 16-bit registers and nonnegative immediates.
    if raw & 0xE000 == 0x6000:
        index = raw & 0x1FFF
        if index not in registers:
            raise ValueError(f"Uninitialized register {index}")
        return registers[index]
    if raw < 0x4000:
        return raw
    raise ValueError(f"Unsupported operand {raw:#x}")


def branch_for_choice(data, choice):
    regs = {7: choice}  # Selection's destination operand is 0x6007.
    pos = SELECTION + 12
    trace = []
    while True:
        op = data[pos]
        if op == 0x09:
            mode, dst, src = data[pos + 1], u16(data, pos + 2), u16(data, pos + 4)
            if mode != 0 or dst & 0xE000 != 0x6000:
                raise ValueError(f"Unsupported reg_calc at {pos:#x}")
            regs[dst & 0x1FFF] = read_operand(src, regs)
            trace.append({"offset": pos, "op": "reg_copy", "dest": dst,
                          "source": src, "value": regs[dst & 0x1FFF]})
            pos += 8
        elif op == 0x02:
            mode, target = data[pos + 1], u32(data, pos + 4)
            lhs, rhs = read_operand(u16(data, pos + 8), regs), read_operand(u16(data, pos + 10), regs)
            compare, next_clause = data[pos + 12], data[pos + 13]
            if mode != 0 or compare != 0 or next_clause != 0:
                raise ValueError(f"Unsupported if form at {pos:#x}")
            taken = lhs == rhs
            trace.append({"offset": pos, "op": "if_equal", "lhs": lhs,
                          "rhs": rhs, "taken": taken, "target": target})
            if taken:
                return target, trace
            pos += 16
        elif op == 0x03:
            target = u32(data, pos + 4)
            trace.append({"offset": pos, "op": "goto", "target": target})
            return target, trace
        else:
            raise ValueError(f"Unsupported opcode {op:#x} at {pos:#x}")


def main():
    data = SCRIPT.read_bytes()
    if data[SELECTION:SELECTION + 4] != bytes.fromhex("72 03 07 60"):
        raise ValueError("Unexpected selection instruction")
    table = u32(data, SELECTION + 4)
    outcomes = []
    for i, expected in enumerate((0x38C4, 0x3C2C, 0x40B8)):
        ptr = u32(data, table + i * 12)
        end = data.find(b"\0", ptr)
        if end < 0:
            raise ValueError("Unterminated option text")
        text = data[ptr:end].decode("cp932")
        target, trace = branch_for_choice(data, i)
        if target != expected:
            raise AssertionError(f"Choice {i} produced {target:#x}, expected {expected:#x}")
        outcomes.append({"choice": i, "original_text": text, "target": f"0x{target:04X}", "trace": trace})
    if OUT.exists():
        raise FileExistsError(f"Not overwriting {OUT}")
    OUT.write_text(json.dumps(outcomes, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("Three branch outcomes verified:", [(x["original_text"], x["target"]) for x in outcomes])


if __name__ == "__main__":
    main()
