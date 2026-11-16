"""使用显式提供的 EE 内存快照，保守模拟 reg_calc 0x17 的已识别内存路径。

不打开模拟器、不修改源存档，也不把任何已有存档当作新游戏初值。
本模块独立于正式转换器；是否接入取决于原版运行时前后对照。
"""
from dataclasses import dataclass
import struct

EE_SIZE = 0x2000000
VISITED_BITS = 0xA98C50
SCENE_FLAGS = 0xA98D10
STORY_COUNT = 0xB1EC20
SCENE_TABLE_PTR = 0xB25554
SCENE_TABLE_COUNT = 0xB25558
STATE_PTR_GP_OFFSET = -0x6D44
MAX_RECORDS = 0x10000


class SnapshotError(ValueError):
    pass


def physical(address, length=1):
    if not isinstance(address, int) or address < 0 or length < 0:
        raise SnapshotError('无效内存地址')
    if 0x80000000 <= address < 0xC0000000:
        address &= 0x1FFFFFFF
    if address + length > EE_SIZE:
        raise SnapshotError(f'EE 地址越界: {address:#x}+{length:#x}')
    return address


@dataclass
class EeMemory:
    data: bytearray

    def __post_init__(self):
        if len(self.data) != EE_SIZE:
            raise SnapshotError(f'需要 32 MiB EE 内存，实际 {len(self.data)} 字节')

    def u8(self, address):
        return self.data[physical(address)]

    def u16(self, address):
        return struct.unpack_from('<H', self.data, physical(address, 2))[0]

    def u32(self, address):
        return struct.unpack_from('<I', self.data, physical(address, 4))[0]

    def write16(self, address, value):
        struct.pack_into('<H', self.data, physical(address, 2), value)

    def write32(self, address, value):
        struct.pack_into('<I', self.data, physical(address, 4), value)

    def bit(self, base, index):
        return (self.u8(base + index // 8) >> (index % 8)) & 1

    def set_bit(self, base, index):
        addr = physical(base + index // 8)
        self.data[addr] |= 1 << (index % 8)


def read_state_base(memory, gp):
    pointer = memory.u32(gp + STATE_PTR_GP_OFFSET)
    if pointer == 0:
        raise SnapshotError('状态指针为空')
    return physical(pointer, 0x4B4)


def simulate_reg17(memory, gp, operand):
    """原样本路径：读旧位、记录编号/旧位、置位；全部置位时处理类型 3 表项。

    修改传入的 EeMemory 副本；失败前先校验所有会访问的范围，避免部分写入。
    表语义、进游戏的状态初值和该路径的原机前后变化仍需要验证。
    """
    if not isinstance(operand, int) or not 0 <= operand <= 0xFFFF:
        raise SnapshotError('编号必须为 u16')
    state = read_state_base(memory, gp)
    count = memory.u32(STORY_COUNT)
    # 已知两个位表的起点相隔 0xC0 字节；不猜测越过下一个位表的访问。
    max_story_bits = (SCENE_FLAGS - VISITED_BITS) * 8
    if count > max_story_bits or operand >= max_story_bits:
        raise SnapshotError(f'剧本计数异常: {count}')
    physical(VISITED_BITS, max((count + 7) // 8, operand // 8 + 1))
    previous = memory.bit(VISITED_BITS, operand)
    # 首先在逻辑上计算写入后的完成情况，避免校验失败时改动内存。
    bits_after = sum(memory.bit(VISITED_BITS, i) or i == operand for i in range(count))
    all_set = bits_after >= count
    selected = []
    if all_set:
        table_count = memory.u32(SCENE_TABLE_COUNT)
        if table_count > MAX_RECORDS:
            raise SnapshotError(f'场景表长度异常: {table_count}')
        table_ptr = memory.u32(SCENE_TABLE_PTR)
        if table_count and not table_ptr:
            raise SnapshotError('非空场景表的指针为空')
        table = physical(table_ptr, 12 * table_count) if table_count else 0
        physical(SCENE_FLAGS, (table_count + 7) // 8)
        selected = [i for i in range(table_count) if memory.u16(table + 12 * i + 8) == 3]
    memory.write16(state + 0x440, operand)
    memory.write32(state + 0x4B0, previous)
    memory.set_bit(VISITED_BITS, operand)
    for i in selected:
        memory.set_bit(SCENE_FLAGS, i)
    return {'operand': operand, 'state_base': state, 'previous_bit': previous,
            'story_count': count, 'bits_after': bits_after, 'all_set': all_set,
            'scene_flag_indices_set': selected}
