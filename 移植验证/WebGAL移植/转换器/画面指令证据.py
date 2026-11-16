"""从 ELF 抽取 msg_mode / graph_disp 的可复核证据，写成 JSON。

与 `转换器/状态字证据.py` 同一风格：每条结论带地址，能从指令字节算出的常量现场重算，
和 `转换器/mac_display.py` 里的常量不一致就报错。无法静态确定的内容列在 unknowns。
"""
import argparse
import hashlib
import json
import struct
from pathlib import Path

import mac_reader  # noqa: F401  由它把 移植验证/ 加入 sys.path
import MAC_命令表提取 as common
import mac_display
import 状态字证据 as state_evidence

MSG_MODE_HANDLER = 0x11A678
MSG_LAYOUT = 0x122EB0
MSG_X_DEFAULT_SITE = 0x122EC8
MODE_BLOCKS = {5: (0x122F50, 0x122F78), 6: (0x122F78, 0x122FA0)}
SETTERS = {0x123868: (0x4C, 0x50), 0x1238B0: (0x54, 0x58), 0x123940: (0x38,)}
CHANGED_SETTER = 0x1241F8
GRAPH_DISP_HANDLER = 0x11C2E8
GRAPH_ADVANCE_SITE = 0x11C4DC


def addiu_constants(dis, start, end):
    """按顺序取出 [start, end) 里 `addiu $reg, $zero, imm` 的 (reg, imm)。"""
    return [(item['op'].split(', ')[0], int(item['op'].split(', ')[-1], 16))
            for item in dis.read(start, end - start)
            if item['mnemonic'] == 'addiu' and ', $zero, ' in item['op']]


def jal_targets(dis, start, end):
    return [item['op'] for item in dis.read(start, end - start) if item['mnemonic'] == 'jal']


def msg_mode_evidence(dis):
    dis.find(MSG_MODE_HANDLER, 0xC0, 'lbu', '$a0, 1($s1)')
    dis.find(MSG_MODE_HANDLER, 0xC0, 'lbu', '$v1, 1($s1)')
    dis.find(MSG_MODE_HANDLER, 0xC0, 'addiu', '$v0, $v0, 4')
    setter = dis.read(CHANGED_SETTER, 8)
    state_evidence.expect(f"{setter[1]['mnemonic']} {setter[1]['op']}", 'sw $a0, -0x79f8($gp)', '模式变更写入')

    modes = {}
    for mode, (start, end) in MODE_BLOCKS.items():
        targets = jal_targets(dis, start, end)
        constants = addiu_constants(dis, start, end)
        state_evidence.expect(targets, ['0x123868', '0x1238b0', '0x123940'],
                              f'msg_mode {mode} 的三个 setter')
        expected = {'5': [('$a0', 0xAE), ('$a1', 0x158), ('$a0', 0x23C),
                          ('$a1', 0x4E), ('$a0', 0x190), ('$v0', 0xB)],
                    '6': [('$a1', 0x158), ('$a0', 0x23C), ('$a1', 0x4E),
                          ('$a0', 0x1EC), ('$v0', 0xB)]}[str(mode)]
        state_evidence.expect(constants, [tuple(item) for item in expected],
                              f'msg_mode {mode} 的几何常量')
        geometry = dict(mac_display.MSG_MODES[mode])
        keys = ['x', 'y', 'w', 'h', 'aux', 'lines'] if mode == 5 else ['y', 'w', 'h', 'aux', 'lines']
        from_elf = dict(zip(keys, [value for _, value in constants]))
        if mode == 6:
            # 模式 6 的 x 没有自己的 addiu：用的是入口 0x122EC8 的 0x4A。
            state_evidence.expect(addiu_constants(dis, MSG_X_DEFAULT_SITE, MSG_X_DEFAULT_SITE + 8),
                                  [('$a0', 0x4A)], '模式 6 的 x 来自入口处的立即数')
            from_elf['x'] = 0x4A
        for key, value in from_elf.items():
            state_evidence.expect(geometry[key], value, f'msg_mode {mode} 的 {key}')
        modes[str(mode)] = {'x': geometry['x'], 'y': geometry['y'], 'w': geometry['w'],
                            'h': geometry['h'], 'aux': geometry['aux'], 'lines': geometry['lines'],
                            'branch': f'0x{start:08X}-0x{end:08X}'}

    layout = dis.read(0x122EF0, 0x10)
    state_evidence.expect([f"{item['mnemonic']} {item['op']}" for item in layout],
                          ['sw $a2, 0x18($s0)', 'beq $a3, $a2, 0x122f78',
                           'sb $a3, 1($s0)', 'beqz $t0, 0x122f18'],
                          '窗口类字段与“模式 6 跳过 mode 字节写入”')
    lines_site = dis.find(MSG_LAYOUT, 0x120, 'sw', '$v0, 0x8c($s0)')
    state_evidence.expect(lines_site['at'], '0x00122FC4', '行数字段写入')

    setters = {}
    sizes = {0x123868: 0x48, 0x1238B0: 0x48, 0x123940: 0x28}
    for address, fields in SETTERS.items():
        code = dis.read(address, sizes[address])
        stores = [item for item in code if item['mnemonic'] == 'sw' and item['op'].endswith('($v0)')]
        state_evidence.expect([item['op'].split(', ')[-1] for item in stores],
                              [f'0x{field:x}($v0)' for field in fields],
                              f'0x{address:08X} 的写入偏移')
        setters[f'0x{address:08X}'] = [f'0x{item["op"].split(", ")[-1]}' for item in stores]

    return {
        'handler': f'0x{MSG_MODE_HANDLER:08X}',
        'length': 4,
        'parameter': {'byte': 1, 'read_at': ['0x0011A6D0', '0x0011A6D4'],
                      'unused_bytes': '2、3 没有任何读取'},
        'dispatch': {'layout_function': f'0x{MSG_LAYOUT:08X}',
                     'window_index_from': '*(state+0x3553C)',
                     'window_record_base': '*(gp-0x6D40) + idx*0x5FF8',
                     'previous_mode_byte': '*(state+0x3555 + idx*0x5FF8)（0x0011A6C8）'},
        'record_fields': {name: f'+0x{offset:02X}' for name, offset in mac_display.RECORD_FIELDS.items()},
        'setters': setters,
        'modes': modes,
        'mode_byte_skipped': sorted(mac_display.MSG_MODES_WITHOUT_MODE_BYTE),
        'changed_flag': {'writer': f'0x{CHANGED_SETTER:08X}', 'store': 'sw $a0, -0x79f8($gp)',
                         'value': 'mode+1（0x0011A6DC/0x0011A6E0）',
                         'consumed_by': ['0x001230D8', '0x001230E8', '0x0012316C', '0x00123174']},
        'evidence': [f"{item['at']}: {item['mnemonic']} {item['op']}"
                     for item in dis.read(MSG_MODE_HANDLER, 0x40)],
        'confidence': 'proven（参数、几何常量、写入字段与地址）/ unproven（见 unknowns）',
    }


def graph_disp_evidence(dis):
    code = dis.read(GRAPH_DISP_HANDLER, 0x90)
    reads = [f"{item['mnemonic']} {item['op']}" for item in code
             if item['mnemonic'] in ('lbu', 'lb', 'lw', 'lh') and '($s3)' in item['op']]
    state_evidence.expect(reads, ['lw $v1, 4($s3)', 'lbu $a0, 1($s3)',
                                  'lbu $v0, 2($s3)', 'lbu $v1, ($s3)'],
                          'graph_disp 读取的参数字节')
    dis.find(GRAPH_DISP_HANDLER, 0x200, 'srl', '$v0, $v0, 0xc')
    dis.find(GRAPH_DISP_HANDLER, 0x200, 'xori', '$v0, $v0, 3')
    advance = dis.read(GRAPH_ADVANCE_SITE, 8)
    state_evidence.expect(f"{advance[0]['mnemonic']} {advance[0]['op']}", 'addiu $v0, $v0, 8',
                          'graph_disp 的 ip 前进量')
    stride = [f"{item['mnemonic']} {item['op']}"
              for item in dis.read(0x11C38C, 0x20)
              if item['mnemonic'] in ('sll', 'addu') and '$v0' in item['op']]
    state_evidence.expect(stride, ['sll $v0, $s0, 1', 'addu $v0, $v0, $s0',
                                   'sll $v0, $v0, 2', 'addu $s1, $v0, $a2'],
                          '记录步长 12 字节')
    return {
        'handler': f'0x{GRAPH_DISP_HANDLER:08X}',
        'length': 8,
        'context_branches': ['0x0011C340（上下文 +0x10 为 0）', '0x0011C480（为 1）'],
        'advance': {'site': f'0x{GRAPH_ADVANCE_SITE:08X}', 'bytes': 8,
                    'note': '两个分支都在这里把 ip 加 8，对控制流没有影响'},
        'parameters': {
            'byte1': {'name': '记录条数', 'read_at': '0x0011C350', 'loop': 's0 = ip[1]-1（0x0011C384/0x0011C400）'},
            'byte2': {'name': '标志', 'read_at': '0x0011C364', 'stored_to': 'state+0x1B38（0x0011C368）'},
            'u32_at_4': {'name': '记录块内偏移', 'read_at': '0x0011C320', 'base': '*(ctx+0x44) 结构 +0xC 指针'},
            'bytes_6_7': {'name': '未使用', 'note': '没有读取，按原样保留'},
        },
        'record': {'bytes': mac_display.GRAPH_RECORD_BYTES,
                   'stride_arithmetic': 's0 的 3n*4（0x0011C390-0x0011C3A4）',
                   'resource_code_at': '+4 的 u16，高 4 位资源组、低 12 位组内编号（0x0011C3C0 的 srl 0xC）',
                   'rewritten_state': {'0x1B20': 0, '0x1B28': '0 或 1', '0x1B2C': 0, '0x1B30': 'ip[1]',
                                       '0x1B34': '1 或 0', '0x1B38': 'ip[2]', '0x1AD0+4n': '每条记录一次 0x19DAF8 的返回值'}},
        'script_offset_reuse': '数据/画面资源候选.tsv 的 MAC_000.bin 0x0000D4 记录偏移 0x000754 等于该指令 u32@4',
        'evidence': [f"{item['at']}: {item['mnemonic']} {item['op']}" for item in code[:0x18]],
        'confidence': 'proven（长度、参数位置、记录结构）/ unproven（见 unknowns）',
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    data = common.ELF.read_bytes()
    segs = state_evidence.segments(data)
    dis = state_evidence.Dis(data, segs)
    table = common.load_table(data)
    state_evidence.expect(table[mac_display.MSG_MODE]['handler'], MSG_MODE_HANDLER, 'msg_mode 处理函数')
    state_evidence.expect(table[mac_display.GRAPH_DISP]['handler'], GRAPH_DISP_HANDLER, 'graph_disp 处理函数')
    state_evidence.expect(table[mac_display.MSG_MODE]['bytes'], 4, 'msg_mode 长度')
    state_evidence.expect(table[mac_display.GRAPH_DISP]['bytes'], 8, 'graph_disp 长度')
    payload = {
        'elf': str(common.ELF),
        'elf_sha256': hashlib.sha256(data).hexdigest(),
        'decode_mode': 'MIPS64 little-endian (capstone)',
        'msg_mode': msg_mode_evidence(dis),
        'graph_disp': graph_disp_evidence(dis),
        'unknowns': [
            '窗口记录 +0x38（模式 5 = 0x190、模式 6 = 0x1EC）在渲染器里的确切作用：现有反汇编中只在 0x00122C74 见到一次死读取，真正的消费者未定位。',
            '窗口记录 +0x54/+0x58（0x23C/0x4E）是像素尺寸还是别的单位：0x00122C98-0x00122CB4 会把 x 夹在 [0x20, 0x260-w]，但换算关系没有画面实测。',
            '模式 6 不写 +0x19：该字段在模式 6 下是否仍被渲染器使用未核实。',
            '*(gp-0x6D40)（窗口记录数组）与状态块 *(gp-0x6D44) 的指针关系：反汇编里只看到分别读取，没有看到两者相减或偏移赋值。',
            '窗口记录在游戏开始/读档时由谁初始化、默认模式是多少；本文件只证明 msg_mode 会改写它。',
            'graph_disp 的模式 0/1 分支由上下文 +0x10 决定，哪个分支在正式剧本里生效未核实；两者都只影响画面排队，不影响 ip。',
            'graph_disp 的 ip[2]（存入 state+0x1B38）语义未核实。',
            '画面记录块基址 *(ctx+0x44)+0xC 是运行时指针；此处把 u32@4 当作脚本文件内偏移使用，依据是既有 数据/画面资源候选.tsv 的对应关系，不是从 ELF 直接证明的。',
        ],
    }
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'输出 {args.output}：msg_mode 模式 {sorted(payload["msg_mode"]["modes"])}，'
          f'graph_disp 记录 {payload["graph_disp"]["record"]["bytes"]} 字节，unknowns {len(payload["unknowns"])} 条')


if __name__ == '__main__':
    main()
