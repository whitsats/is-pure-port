"""`reg_calc` 运算码 0x17 的静态证据与阻塞结论。

0x17 不在 0/1/2 的算术表里，而是进入 `0x00118FD0`：
- 读 `u16@2` 的操作数，调用 `0x117270`（`j 0x105200`）从全局位表
  `0xA98C50` 读一位；
- 在调用延迟槽把操作数写入 `G+0x440`，返回后把旧位写入 `G+0x4B0`；
- 调 `0x117288`，后者按 `0xB1EC20` 的计数循环读位，并在条件满足时
  调 `0x1174B8(3)`；`0x1174B8` 遍历 `0xB25554` 指向的表，调用
  `0x105818`/`0x117638` 设置标志。

这些全局表和计数值是运行时数据，ELF 里没有初始内容，所以本脚本只固化
“它做了什么、缺什么”，不替它编造语义。
"""
import argparse
import hashlib
import json
from pathlib import Path

import mac_reader  # noqa: F401
import MAC_命令表提取 as common
import 状态字证据 as state_evidence

CALC_TABLE = 0x259D20
OP_17 = 0x118FD0
BIT_READ = 0x105200
BIT_WRITE = 0x105238
SCENE_LOOP = 0x117288
SCENE_FLAGS = 0x1174B8
SCENE_ENTRY = 0x105818
SCENE_SET = 0x117638
BIT_TABLE_READ = 0xA98C50
BIT_TABLE_WRITE = 0xA98C50
SCENE_FLAG_TABLE = 0xA98D10
SCENE_COUNT = 0xB1EC20
SCENE_TABLE_PTR = 0xB25554


def require(dis, start, size, wanted, label):
    code = [f"{item['mnemonic']} {item['op']}" for item in dis.read(start, size)]
    for text in wanted:
        if text not in code:
            raise ValueError(f'{label} 缺少 {text}；实际：{code[:12]}')
    return code


def script_scan(scripts_path):
    scripts = json.loads(Path(scripts_path).read_text(encoding='utf-8'))['scripts']
    rows = []
    for script in scripts:
        for command in script['commands']:
            raw = bytes.fromhex(command['raw_hex'])
            if command['opcode'] == 0x09 and len(raw) == 8 and raw[1] == 0x17:
                rows.append({'script': script['file'], 'offset': f'0x{command["offset"]:04X}',
                             'operand': raw[2] | (raw[3] << 8), 'raw_hex': raw.hex()})
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--scripts', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    data = common.ELF.read_bytes()
    segs = state_evidence.segments(data)
    dis = state_evidence.Dis(data, segs)
    table = common.load_table(data)
    state_evidence.expect(table[0x09]['handler'], 0x118CD8, 'reg_calc 处理函数')
    calc_table = state_evidence.table_at(data, segs, CALC_TABLE, 0x1C)
    state_evidence.expect(calc_table[0x17], OP_17, 'reg_calc 0x17 处理入口')

    op_code = require(dis, OP_17, 0x30, [
        'lhu $v0, 2($s2)',
        'jal 0x117270',
        'sh $v0, 0x440($v1)',
        'sw $v0, 0x4b0($v1)',
        'jal 0x117288',
    ], '0x17 处理段')
    read_code = require(dis, BIT_READ, 0x40, [
        'lbu $v0, -0x73b0($v0)',
        'andi $v0, $v0, 1',
    ], '位表读取')
    write_code = require(dis, BIT_WRITE, 0xA0, [
        'lbu $v1, ($v0)',
        'or $v1, $v1, $a1',
        'sb $v1, ($v0)',
    ], '位表写入')
    loop_code = require(dis, SCENE_LOOP, 0x70, [
        'jal 0x105238',
        'lw $s1, -0x13e0($v0)',
        'jal 0x117270',
        'j 0x1174b8',
        'addiu $a0, $zero, 3',
        'slt $v0, $s2, $s1',
        'bnez $v0, 0x117300',
    ], '场景计数/解锁分支')
    state_evidence.expect(dis.find(OP_17, 0x30, 'jal', '0x117270')['at'], '0x00118FDC', '读位调用')
    state_evidence.expect(dis.find(OP_17, 0x30, 'sh', '$v0, 0x440($v1)')['at'], '0x00118FE0', '延迟槽写入')
    state_evidence.expect((0xAA << 16) - 0x73B0, BIT_TABLE_READ, '位表地址')
    state_evidence.expect(BIT_TABLE_READ, BIT_TABLE_WRITE, '读写位表地址一致')
    flag_code = require(dis, SCENE_FLAGS, 0x60, [
        'lw $v0, 0x6958($v1)',
        'jal 0x105818',
        'jal 0x117638',
    ], '场景表遍历')
    entry_code = require(dis, SCENE_ENTRY, 0x30, [
        'lw $a0, 0x5554($v0)',
        'lhu $v0, 8($v1)',
    ], '场景表项')

    rows = script_scan(args.scripts)
    by_script = {}
    for row in rows:
        by_script.setdefault(row['script'], []).append(row['operand'])
    mismatches = {}
    for name, values in by_script.items():
        if name == 'MAC_058.bin':
            if values != [0, 1, 2, 3, 4]:
                mismatches[name] = values
            continue
        script_index = int(name[4:7])
        if any(value != script_index for value in values):
            mismatches[name] = values
    if mismatches:
        raise ValueError(f'0x17 操作数与剧本号不完全对应: {mismatches}')

    payload = {
        'elf': str(common.ELF),
        'elf_sha256': hashlib.sha256(data).hexdigest(),
        'decode_mode': 'MIPS64 little-endian (capstone)',
        'command': {'opcode': '0x09', 'operation': '0x17', 'handler': f'0x{OP_17:08X}',
                    'length': 8, 'operand_u16_at': 2},
        'dispatch': {'table': f'0x{CALC_TABLE:08X}',
                     'entry_0x17': f'0x{calc_table[0x17]:08X}'},
        'observed_path': {
            'read_bit': {'call': '0x00118FDC 的 0x117270',
                         'thunk_to': f'0x{BIT_READ:08X}',
                         'table': f'0x{BIT_TABLE_READ:08X}',
                         'effect': '读取操作数指定位，返回 0/1'},
            'state_writes': [
                {'address': '0x00118FE0', 'instruction': 'sh $v0, 0x440($v1)', 'value': '输入编号（调用延迟槽）'},
                {'address': '0x00118FEC', 'instruction': 'sw $v0, 0x4b0($v1)', 'value': '设置前读取的位值'},
            ],
            'second_call': {'callee': f'0x{SCENE_LOOP:08X}',
                            'bit_setter': f'0x{BIT_WRITE:08X}',
                            'bit_table': f'0x{BIT_TABLE_WRITE:08X}',
                            'count_source': f'0x{SCENE_COUNT:08X}',
                            'on_all_set': f'0x{SCENE_FLAGS:08X}(3)',
                            'on_shortfall': '直接返回，不调用场景表处理'},
            'scene_table': {'iterator': f'0x{SCENE_FLAGS:08X}',
                            'entry_getter': f'0x{SCENE_ENTRY:08X}',
                            'flag_setter': f'0x{SCENE_SET:08X}',
                            'table_pointer': f'0x{SCENE_TABLE_PTR:08X}',
                            'entry_stride': 12, 'field_read': 'u16@8'},
        },
        'evidence': {
            'op_17': op_code,
            'bit_read': read_code,
            'bit_write': write_code,
            'scene_loop': loop_code,
            'scene_flags': flag_code,
            'scene_entry': entry_code,
        },
        'script_scan': {
            'occurrences': len(rows),
            'scripts': len(by_script),
            'operand_equals_script_index': True,
            'mac_058_operands': by_script.get('MAC_058.bin'),
            'sample': rows[:6],
        },
        'conclusion': {
            'proven': '0x17 不是 0/1/2 的算术；它读取全局位表、写状态 +0x440/+0x4B0，'
                      '并按运行时计数遍历场景表设置标志。',
            'not_proven': '位表/场景表的业务含义（场景已读、画廊解锁或别的）、新游戏表初值、'
                          '运行期间计数是否恒定、+0x440/+0x4B0 是否被后续 if 读取。',
            'converter_behavior': '继续停止在 reg_calc 0x17，不执行、不跳过；'
                                  '停止原因写明运行时表未核实。',
        },
        'blocking': ('MAC_001.bin 0x58 就停在这里；若直接跳过，会漏掉进度位表和可能的场景标志表写入、'
                     '状态 +0x440/+0x4B0，以及可能的场景/画廊解锁，后续路线或存档界面可能不一致。'),
        'next_material': [
            '运行到 MAC_001.bin 0x58 前后的内存转储：0xA98AD0、0xA98C50、0xA98D10、'
            '0xB1EC20、0xB25554 指向的表，以及 G+0x440/+0x4B0。',
            '同一存档在 0x17 执行前后，章节选择/画廊/场景列表的可见变化。',
            '若表由某个模块装载，提供该模块或装载后的完整表内容；仅有 ELF 静态数据不够。',
        ],
    }
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'输出 {args.output}：0x17 → 0x{OP_17:08X}，{len(rows)} 处，操作数=剧本号')


if __name__ == '__main__':
    main()
