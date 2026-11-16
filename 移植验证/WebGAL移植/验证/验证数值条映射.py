"""从原盘 INIT.BIN / SLPM_665.70 复核三条数值条的寄存器、初值和显示范围。

证据链：
1. INIT.BIN 是原盘 LZSS 压缩的调试名称表；解压后 0x8f4 起是变量索引到名称的指针表。
   索引 38..44 依次是 伊織好感度 / いつき好感度 / 泉好感度 / 藍子好感度 / 自信 / 自制心 / ひねくれ。
2. 脚本操作数 0x6026..0x602C 的编码是 bank1 word，索引正好是 0x26..0x2C(38..44)。
3. 原盘绘制函数 0x12ebf8 从 0x214538 读三个操作数 0x602A/0x602C/0x602B，
   循环 3 次；每个值乘条宽后除以 0x28(40)，再按条宽钳位。
4. 开篇 MAC_000 的 reg_calc（命令 0x09、运算字节 0x00）将 16 位立即数 0x0014（20）写到 0x6026/0x602B/0x602C/0x602A。这里 0x0E 是“写立即数”运算常量，不是这条记录的运算字节。
5. 从直接引用记录统计三条数值条的比较方向和常数；移植写入器必须保留有符号 16 位回绕。

输出 `数据/数值条证据.json`；任何一项不符即非零退出。
"""
from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(ROOT / '转换器'))
from decode_clean_30 import unpack_lzss  # noqa: E402
from mac_state import to_s16  # noqa: E402
from mac_webgal_state import emit_word_write  # noqa: E402

ELF = ROOT.parent / '输出-保护边修复/SYSTEM/SLPM_665.70'
INIT = ROOT.parent / '输出-保护边修复/SYSTEM/INIT.BIN'
STATUS_TABLE_VA = 0x214538
DRAW_FN = 0x12EBF8
NAME_TABLE_BASE = 0x8F4


def va_to_file(va: int) -> int:
    data = ELF.read_bytes()
    phoff = struct.unpack_from('<I', data, 28)[0]
    for i in range(struct.unpack_from('<H', data, 44)[0]):
        kind, off, vaddr, _, filesz, _, _, _ = struct.unpack_from('<8I', data, phoff + i * 32)
        if kind == 1 and vaddr <= va < vaddr + filesz:
            return off + va - vaddr
    raise ValueError(f'vaddr 0x{va:x} 不在可加载段')


def word(va: int) -> int:
    return struct.unpack_from('<I', ELF.read_bytes(), va_to_file(va))[0]


def cstring(blob: bytes, offset: int) -> str:
    end = blob.index(b'\0', offset)
    return blob[offset:end].decode('shift_jis')


def main() -> int:
    raw = unpack_lzss(INIT.read_bytes())
    assert len(raw) == 47553, len(raw)

    entries = {}
    for index in range(38, 45):
        pointer = struct.unpack_from('<I', raw, NAME_TABLE_BASE + index * 4)[0]
        entries[index] = cstring(raw, pointer)
    expected = {38: '伊織好感度', 39: 'いつき好感度', 40: '泉好感度', 41: '藍子好感度',
                42: '自信', 43: '自制心', 44: 'ひねくれ'}
    assert entries == expected, entries

    table = [word(STATUS_TABLE_VA + i * 4) for i in range(3)]
    assert table == [0x602A, 0x602C, 0x602B], [hex(v) for v in table]

    # 0x12ec14: addiu $s2,$zero,2（3 条）；0x12ec1c: addiu $s3,$zero,0x28（分母 40）
    assert word(0x12EC14) == 0x24120002, hex(word(0x12EC14))
    assert word(0x12EC1C) == 0x24130028, hex(word(0x12EC1C))
    # 0x12ed40: lh $a0,0($s0)；0x12ed48: jal 0x115730（读取变量）
    assert word(0x12ED40) == 0x86040000, hex(word(0x12ED40))
    assert word(0x12ED48) == 0x0C0455CC, hex(word(0x12ED48))
    # 0x12ed70: div $zero,$v0,$s3；0x12ed80: slt $v1,$t0,$v0；0x12ed84: movn $v0,$t0,$v1
    assert word(0x12ED70) == 0x0053001A, hex(word(0x12ED70))
    assert word(0x12ED80) == 0x0102182A, hex(word(0x12ED80))
    assert word(0x12ED84) == 0x0103100B, hex(word(0x12ED84))

    refs = json.loads((ROOT / '数据/剧情状态直接引用.json').read_text(encoding='utf-8'))['references']
    initial = {}
    for operand in ('0x6026', '0x602A', '0x602B', '0x602C'):
        writes = [item for item in refs[operand]
                  if item['role'] == 'write' and item['script'] == 'MAC_000.bin' and item['offset'] < 64]
        assert writes, operand
        raw_hex = writes[0]['raw_hex']
        command, operation, destination, immediate, trailing = struct.unpack(
            '<BBHHH', bytes.fromhex(raw_hex)
        )
        assert (command, operation, destination, immediate, trailing) == (
            0x09, 0x00, int(operand, 16), 0x0014, 0
        ), (operand, raw_hex)
        initial[operand] = 20

    # 原盘比较记录：只统计“变量在左、常数在右”的直接 if。
    # 全部记录由脚本逐条解析，不依赖生成场景里的文字。
    comparison_names = {0: '==', 1: '!=', 2: '<=', 3: '>=', 4: '<', 5: '>'}
    expected_branches = {
        '0x602A': {('<', 20): 162, ('!=', 20): 52, ('!=', 19): 52},
        '0x602B': {('<', 20): 213, ('!=', 20): 27, ('!=', 19): 27, ('>', 19): 1},
        '0x602C': {('>', 20): 160, ('!=', 20): 53, ('!=', 21): 53, ('<', 21): 3},
    }
    branch_evidence = {}
    for operand, expected in expected_branches.items():
        counts = {}
        examples = {}
        for item in refs[operand]:
            if item['role'] != 'compare':
                continue
            raw = bytes.fromhex(item['raw_hex'])
            lhs, rhs = struct.unpack_from('<HH', raw, 8)
            code = raw[12]
            assert code in comparison_names, (operand, code)
            if lhs == int(operand, 16):
                other = rhs
            elif rhs == int(operand, 16):
                other = lhs
            else:
                raise AssertionError((operand, item['script'], item['offset']))
            assert other & 0xC000 not in (0x4000, 0x8000), (operand, hex(other))
            key = (comparison_names[code], to_s16(other))
            counts[key] = counts.get(key, 0) + 1
            examples.setdefault(key, f"{item['script']}:{item['offset']:#x}")
        assert counts == expected, (operand, counts)
        branch_evidence[operand] = {
            'comparisons': [{'operator': op, 'constant': value, 'count': count,
                             'example': examples[(op, value)]}
                            for (op, value), count in sorted(counts.items())],
            'bare_operand': '0x' + operand[2:],
        }

    # 移植的写入器必须保留原程序的 16 位有符号回绕，不能把 0..32767 当成全部范围。
    assert (to_s16(0x7FFF), to_s16(0x8000), to_s16(0xFFFF)) == (32767, -32768, -1)
    add_line = emit_word_write(bytes.fromhex('09012a6001000000'), (0x602A,), 'branch')
    assert add_line[0] == 'setVar:mac_602a=mac_602a+(1) -next;'
    assert 'jumpLabel:wrap_branch_underflow -when=mac_602a<-32768;' in add_line
    assert 'jumpLabel:wrap_branch_overflow -when=mac_602a>32767;' in add_line

    def operand_for(index: int) -> str:
        return f'0x{0x6000 | index:04X}'

    evidence = {
        'source': {
            'name_table': 'INIT.BIN -> LZSS -> 0x8F4 名称指针表',
            'status_table': f'SLPM_665.70 0x{STATUS_TABLE_VA:08X}',
            'draw_function': f'SLPM_665.70 0x{DRAW_FN:08X}',
        },
        'name_table': {f'index {k}': v for k, v in entries.items()},
        'operand_encoding': '0x4000 | 0x2000 | index = bank1 word；0x6026..0x602C 对应索引 38..44',
        'bars': [
            {'position': 1, 'operand': '0x602A', 'index': 42, 'name': entries[42],
             'state_offset': '0x274', 'initial': 20},
            {'position': 2, 'operand': '0x602C', 'index': 44, 'name': entries[44],
             'state_offset': '0x278', 'initial': 20},
            {'position': 3, 'operand': '0x602B', 'index': 43, 'name': entries[43],
             'state_offset': '0x276', 'initial': 20},
        ],
        'affection': [
            {'operand': operand_for(index), 'index': index, 'name': entries[index],
             'state_offset': f'0x{0x220 + index * 2:03X}', 'initial': 20 if index == 38 else 0}
            for index in range(38, 42)
        ],
        'display_range': {'divisor': 40, 'clamp': '按条宽钳位；0..40 映射满条',
                          'note': '超过 40 仍显示满条，不改变脚本值'},
        'initial_write': initial,
        'numeric_range': {'storage': 'signed 16-bit', 'min': -32768, 'max': 32767,
                          'display_scale': '0..40 fills the bar; values above 40 are display-clamped only'},
        'branch_checks': branch_evidence,
        'read_sequence': ['0x602A', '0x602C', '0x602B'],
    }
    (ROOT / '数据/数值条证据.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + '\n',
                                                encoding='utf-8')
    print('PASS INIT 名称表索引 38..44 =', ' / '.join(entries.values()))
    print('PASS 绘制表 0x214538 =', ' / '.join(f'0x{v:04X}' for v in table),
          '=> 自信 / ひねくれ / 自制心')
    print('PASS 绘制循环 3 次、分母 0x28(40)、按条宽钳位')
    print('PASS MAC_000 reg_calc 运算码 0x00 写立即数 0x0014(20)：0x6026 / 0x602A / 0x602B / 0x602C')
    for operand, data in branch_evidence.items():
        detail = ', '.join(f"{x['operator']} {x['constant']} x{x['count']}" for x in data['comparisons'])
        print(f'PASS {operand} 原盘分支 {detail}')
    print('PASS 有符号 16 位范围 -32768..32767，移植写入器保留回绕守卫')
    print('WROTE 数据/数值条证据.json')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
