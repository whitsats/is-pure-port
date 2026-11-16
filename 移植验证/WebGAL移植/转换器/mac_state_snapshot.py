"""使用显式提供的即时存档内存副本作为实验状态；不修改原存档。"""
from pathlib import Path
import hashlib
import struct
from zipfile import ZipFile

from mac_state import State, UnsupportedCommand, to_s16
from mac_progress_snapshot import EeMemory, EE_SIZE, SnapshotError, read_state_base, simulate_reg17
from 检查即时存档表 import elf_gp
from 校验reg17指令执行 import verify_code
import MAC_命令表提取 as common


class SnapshotState(State):
    """状态字和 0x17 的全局表共用同一内存，避免隐藏内存别名。"""

    def __init__(self, memory, gp, snapshot_sha256):
        super().__init__()
        self.memory = memory
        self.gp = gp
        self.state_base = read_state_base(memory, gp)
        self.snapshot_sha256 = snapshot_sha256

    def read(self, raw):
        kind, bank, index = self.address_of(raw)
        if kind == 'value':
            return to_s16(raw)
        address = self.state_base + self.offset_of(kind, bank, index)
        try:
            if kind == 'word':
                return to_s16(self.memory.u16(address))
            return (self.memory.u8(address) >> (index % 8)) & 1
        except SnapshotError as exc:
            raise UnsupportedCommand(f'快照状态读取失败: {exc}') from exc

    def write(self, raw, value):
        kind, bank, index = self.address_of(raw)
        if kind == 'value':
            raise UnsupportedCommand(f'立即数不能作为写入目的 {raw:#06x}')
        old = self.read(raw)
        new = to_s16(value) if kind == 'word' else value & 1
        try:
            address = self.state_base + self.offset_of(kind, bank, index)
            if kind == 'word':
                self.memory.write16(address, new & 0xFFFF)
            else:
                mask = 1 << (index % 8)
                current = self.memory.u8(address)
                self.memory.data[address] = (current | mask) if new else (current & ~mask)
        except SnapshotError as exc:
            raise UnsupportedCommand(f'快照状态写入失败: {exc}') from exc
        self.written.add((bank, index))
        return old, new

    def apply_reg17(self, raw):
        if len(raw) != 8 or raw[0:2] != b'\x09\x17':
            raise UnsupportedCommand('不是 8 字节 reg_calc 0x17')
        operand = struct.unpack_from('<H', raw, 2)[0]
        try:
            result = simulate_reg17(self.memory, self.gp, operand)
        except SnapshotError as exc:
            raise UnsupportedCommand(f'快照状态无法执行 0x17: {exc}') from exc
        return {'operation': 'reg_calc_17_snapshot', **result,
                'note': '只依据用户明确指定的快照模拟，输入编号与旧位值分别写入 G+0x440/+0x4B0；'
                        '所有相关位为 1 时处理类型 3 场景表项。其业务含义和完整运行轨迹未证实。'}

    def read_context_u32(self, offset):
        try:
            return self.memory.u32(self.state_base + offset)
        except SnapshotError as exc:
            raise UnsupportedCommand(f'快照上下文读取失败: {exc}') from exc

    def write_context_u32(self, offset, value):
        try:
            self.memory.write32(self.state_base + offset, value & 0xFFFFFFFF)
        except SnapshotError as exc:
            raise UnsupportedCommand(f'快照上下文写入失败: {exc}') from exc


def load_snapshot(path):
    path = Path(path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    with ZipFile(path) as archive:
        info = archive.getinfo('eeMemory.bin')
        if info.file_size != EE_SIZE:
            raise SnapshotError('即时存档 EE 内存不是 32 MiB')
        data = archive.read(info)
    elf = common.ELF.read_bytes()
    verify_code(data, elf)
    return SnapshotState(EeMemory(bytearray(data)), elf_gp(elf), digest)
