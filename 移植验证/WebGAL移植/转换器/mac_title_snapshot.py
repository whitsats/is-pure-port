"""读取已给定快照中 title_disp 使用的标题记录，未模拟完整标题演出。"""
import sys
from pathlib import Path

from mac_progress_snapshot import SnapshotError, physical, read_state_base

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from 本地路径 import ZH_ROOT

TITLE_TABLE_COUNT_CANDIDATE = 0xB1EC18
TITLE_TABLE_PTR = 0xB1EC1C
TITLE_GATE = 0xA98DA8
TITLE_RECORD_COUNT = 57


def read_null_bytes(memory, address, max_length=512):
    if not address:
        raise SnapshotError('标题字符串指针为空')
    start = physical(address)
    end = min(len(memory.data), start + max_length)
    stop = memory.data.find(b'\0', start, end)
    if stop < 0:
        raise SnapshotError(f'标题没有在 {max_length} 字节内终止: {address:#x}')
    return bytes(memory.data[start:stop])


def invert_author_table():
    sys.path.insert(0, str(ZH_ROOT / '打盘'))
    import 烘焙文本 as bake

    table = bake.load_author_table(bake.AUTHOR_TABLE)
    if not table:
        raise SnapshotError('原作者字码表不可用')
    inverse = {}
    for char, codes in table.items():
        for code in codes:
            if code in inverse and inverse[code] != char:
                raise SnapshotError(f'码位对应多个字: {code}')
            inverse[code] = char
    return inverse


def decode_title(raw, inverse):
    result, unknown, i = [], [], 0
    while i < len(raw):
        if raw[i] < 0x80:
            result.append(chr(raw[i]))
            i += 1
            continue
        if i + 1 >= len(raw):
            raise SnapshotError('标题末尾存在不完整双字节')
        code = raw[i:i + 2].hex()
        char = inverse.get(code)
        if char is None:
            result.append(f'<{code.upper()}>')
            unknown.append(code)
        else:
            result.append(char)
        i += 2
    return ''.join(result), unknown


def inspect_title(memory, gp, inverse):
    state = read_state_base(memory, gp)
    number = memory.u16(state + 0x440)
    previous = memory.u32(state + 0x4B0)
    table = memory.u32(TITLE_TABLE_PTR)
    count = memory.u32(TITLE_TABLE_COUNT_CANDIDATE)
    if not table or count > 0x10000 or number >= TITLE_RECORD_COUNT:
        raise SnapshotError(
            f'标题表指针或编号无效: {table:#x}/{count}/{number}；静态表长度为 {TITLE_RECORD_COUNT}')
    record = physical(table + 12 * number, 12)
    first = memory.u32(record)
    title = memory.u32(record + 4)
    first_bytes, title_bytes = read_null_bytes(memory, first), read_null_bytes(memory, title)
    first_text, first_unknown = decode_title(first_bytes, inverse)
    title_text, title_unknown = decode_title(title_bytes, inverse)
    return {'script_number': number, 'previous_bit': previous,
            'adjacent_count_candidate': count, 'table_pointer': f'0x{table:08X}',
            'title_record_count': TITLE_RECORD_COUNT,
            'record_address': f'0x{record:08X}', 'record_first_string_pointer': f'0x{first:08X}',
            'display_title_pointer': f'0x{title:08X}', 'first_string_raw': first_bytes.hex(),
            'first_string': first_text, 'first_unknown_codes': first_unknown,
            'title_raw': title_bytes.hex(), 'title': title_text, 'title_unknown_codes': title_unknown,
            'display_parameter': previous + 6, 'display_gate_byte': memory.u8(TITLE_GATE),
            'scope': '只读快照中记录及传参；编号上限按静态 INIT 的 57 条记录，'
                     '不使用相邻的 52 候选；标题效果或开关业务语义仍未验证。'}
