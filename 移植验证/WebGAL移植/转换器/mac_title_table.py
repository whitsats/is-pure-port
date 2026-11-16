"""从原版与 v7.4 INIT 静态提取 57 条章节标题，并解析 title_disp。

来源：
- 原版解压文件：汉化项目的 `素材/汉化原始工程/原始解包/init.bin.bin`
- v7.4 终版：字体研究/_release-v7.4/.../打盘/init-v5-lazy.bin

标题表固定在解压缓冲 0x0AE8，每条 12 字节：+0 首行字符串偏移、+4 标题字符串
偏移、+8 一个 0x000A0001 形态的标记。原版与 v7.4 的表项和字符串偏移一致，只有
被汉化的标题字节不同；第 57 项开始不再是 12 字节记录（+0 为 0），因此静态长度为
57。0xB1EC18 处的 52 不是标题表长度，不用于索引上限。

作者码表没有收录 0x8145、0x8140；两者在原版与 v7.4 的同位置都存在。按项目已有
证据，0x8145 映射为「・」、0x8140 映射为全角空格；这两项作为显式替换写入清单，
而不是悄悄扩展作者码表。其他未知码保留为 <XXXX> 并标为不可安全生成。
"""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import struct
import sys

from mac_state import UnsupportedCommand
from mac_title_snapshot import TITLE_RECORD_COUNT, decode_title, invert_author_table

BASE = Path(__file__).resolve().parents[1]
PROJECT = BASE.parent
sys.path.insert(0, str(PROJECT))
from 本地路径 import V74_RELEASE, ZH_ROOT
TITLE_TABLE_OFFSET = 0xAE8
TITLE_RECORD_SIZE = 12
TITLE_DISP = 0x50
DEFAULT_TITLE_MANIFEST = BASE / '数据/章节标题静态表.json'
DEFAULT_V74_INIT = V74_RELEASE / '打盘/init-v5-lazy.bin'
DEFAULT_ORIGINAL_INIT = ZH_ROOT / '素材/汉化原始工程/原始解包/init.bin.bin'

# 原版与 v7.4 标题表同位置都出现的码位；作者码表未收录。来源写在每条记录的
# substitutions 中，供人工复核，不修改作者码表文件。
TITLE_CODE_SUBSTITUTIONS = {
    '8145': {
        'char': '・',
        'source': '原版 init.bin.bin 与 v7.4 init-v5-lazy.bin 同位置均为 0x8145；交接文档记录 0x8145=・，作者码表未收录',
    },
    '8140': {
        'char': '　',
        'source': '原版与 v7.4 同位置均为 0x8140；数据/字码补充推断.json：226 行对齐推断为全角空格，字体字模未核对',
    },
}


def _read_null(raw, offset, label):
    if not isinstance(offset, int) or offset <= 0 or offset >= len(raw):
        raise ValueError(f'{label} 偏移越界: {offset:#x}')
    end = raw.find(b'\0', offset)
    if end < 0:
        raise ValueError(f'{label} 没有 NUL 终止: {offset:#x}')
    return bytes(raw[offset:end])


def unpack_init(path):
    text = path.read_bytes()
    if len(text) == 0x100000:
        return bytearray(text)
    sys.path.insert(0, str(PROJECT))
    from decode_clean_30 import unpack_lzss
    return bytearray(unpack_lzss(text))


def _decode(raw, inverse, substitutions):
    text, unknown = decode_title(raw, inverse)
    used = []
    for code in sorted(set(unknown)):
        replacement = substitutions.get(code.upper())
        if replacement:
            text = text.replace(f'<{code.upper()}>', replacement['char'])
            used.append({'code': code.upper(), **replacement})
    remaining = [code for code in unknown if code.upper() not in substitutions]
    safe = not remaining and not any(ch in text for ch in ';|\\\r\n')
    return text, remaining, used, safe


def load_title_table(v74_path=DEFAULT_V74_INIT, original_path=DEFAULT_ORIGINAL_INIT):
    """返回 {source..., records: [...]}；不写文件。"""
    v74_path, original_path = Path(v74_path), Path(original_path)
    if not v74_path.is_file():
        raise FileNotFoundError(v74_path)
    v74_raw = unpack_init(v74_path)
    original_raw = original_path.read_bytes() if original_path.is_file() else None
    expected_end = TITLE_TABLE_OFFSET + TITLE_RECORD_SIZE * TITLE_RECORD_COUNT
    if len(v74_raw) < expected_end + 4:
        raise ValueError('v7.4 INIT 解压缓冲不足 57 条标题')
    inverse = invert_author_table()
    records = []
    for index in range(TITLE_RECORD_COUNT):
        offset = TITLE_TABLE_OFFSET + TITLE_RECORD_SIZE * index
        first_ptr, title_ptr, marker = struct.unpack_from('<III', v74_raw, offset)
        first_raw = _read_null(v74_raw, first_ptr, f'标题 {index} 首行')
        title_raw = _read_null(v74_raw, title_ptr, f'标题 {index} 标题')
        first_text, first_unknown, first_subs, first_safe = _decode(
            first_raw, inverse, TITLE_CODE_SUBSTITUTIONS)
        title_text, title_unknown, title_subs, title_safe = _decode(
            title_raw, inverse, TITLE_CODE_SUBSTITUTIONS)
        original_match = None
        if original_raw is not None:
            if len(original_raw) >= expected_end + 4:
                original_first, original_title, _ = struct.unpack_from('<III', original_raw, offset)
                original_match = {
                    'first_pointer': f'0x{original_first:08X}',
                    'title_pointer': f'0x{original_title:08X}',
                    'same_pointer_layout': (original_first, original_title) == (first_ptr, title_ptr),
                    'same_first_bytes': _read_null(original_raw, first_ptr, '原版首行') == first_raw,
                    'same_title_bytes': _read_null(original_raw, title_ptr, '原版标题') == title_raw,
                }
        records.append({
            'index': index,
            'record_offset': f'0x{offset:06X}',
            'first_pointer': f'0x{first_ptr:08X}',
            'title_pointer': f'0x{title_ptr:08X}',
            'marker': f'0x{marker:08X}',
            'first_raw_hex': first_raw.hex(' '),
            'title_raw_hex': title_raw.hex(' '),
            'first_text': first_text,
            'title': title_text,
            'unknown_codes': title_unknown,
            'first_unknown_codes': first_unknown,
            'first_substitutions': first_subs,
            'title_substitutions': title_subs,
            'substitutions': title_subs + [item for item in first_subs if item not in title_subs],
            'webgal_safe': title_safe,
            'first_webgal_safe': first_safe,
            'original': original_match,
        })
    next_first = struct.unpack_from('<I', v74_raw, expected_end)[0]
    if next_first != 0:
        raise ValueError(f'第 58 条记录的首指针不是 0，不能证明静态长度为 57: {next_first:#x}')
    return {
        'v74_source': str(v74_path),
        'v74_sha256': hashlib.sha256(v74_path.read_bytes()).hexdigest(),
        'v74_decompressed_sha256': hashlib.sha256(v74_raw).hexdigest(),
        'original_source': str(original_path) if original_path.is_file() else None,
        'original_sha256': (hashlib.sha256(original_path.read_bytes()).hexdigest()
                            if original_path.is_file() else None),
        'decompressed_size': len(v74_raw),
        'table_offset': f'0x{TITLE_TABLE_OFFSET:06X}',
        'record_size': TITLE_RECORD_SIZE,
        'record_count': TITLE_RECORD_COUNT,
        'next_record_offset': f'0x{expected_end:06X}',
        'next_record_first_pointer': f'0x{next_first:08X}',
        'count_note': '57 条由第 0 项到第 56 项的 12 字节记录确定；第 57 项首指针为 0。'
                      '0xB1EC18=52 不是标题表长度，不用于索引上限。',
        'substitutions': TITLE_CODE_SUBSTITUTIONS,
        'records': records,
    }


def write_title_manifest(output, table=None):
    output = Path(output)
    if output.exists():
        raise FileExistsError(output)
    table = table or load_title_table()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(table, ensure_ascii=False, indent=2) + '\n',
                      encoding='utf-8', newline='\n')
    return table


def load_title_manifest(path=DEFAULT_TITLE_MANIFEST):
    table = json.loads(Path(path).read_text(encoding='utf-8'))
    records = table.get('records')
    if not isinstance(records, list) or len(records) != TITLE_RECORD_COUNT:
        raise ValueError(f'标题清单记录数不是 {TITLE_RECORD_COUNT}: {path}')
    return table


def resolve_title_disp(raw, state, records):
    """按 title_disp 处理函数 0x11E6F8/0x11E7E4 的状态字段选择标题并生成 intro。"""
    if bytes(raw) != b'\x50\x00\x00\x00':
        raise UnsupportedCommand(f'未核实的 title_disp 参数: {bytes(raw).hex()}')
    index = state.read_context_u32(0x440) & 0xFFFF
    previous = state.read_context_u32(0x4B0)
    if index >= len(records):
        raise UnsupportedCommand(
            f'title_disp 记录下标 {index} 超出静态标题表 {len(records)} 条')
    record = records[index]
    if not record.get('webgal_safe'):
        raise UnsupportedCommand(
            f'title_disp 第 {index} 条含未确认字码或 WebGAL 不安全字符，拒绝生成')
    title = record.get('title')
    if not title:
        raise UnsupportedCommand(f'title_disp 第 {index} 条标题为空')
    command = f'intro:{title};'
    return {
        'index': index,
        'previous_value': previous,
        'display_parameter': previous + 6,
        'title': title,
        'record_offset': record.get('record_offset'),
        'title_raw_hex': record.get('title_raw_hex'),
        'command': command,
        'webgal': {
            'mapped': True,
            'command': command,
            'note': '使用静态 INIT 的 57 条标题表；title_disp 的 G+0x440 下标已解析，'
                    'G+0x4B0+6 只记录不解释。字号、延迟和原版标题时序未逐项复刻。',
        },
    }
