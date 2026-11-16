"""从 ELF 抽取 `fade_start` / `fade_wait` / `se_del` 的可复核证据，写成 JSON。

每条结论都带地址；能从指令字节算出的常量一律现算，与 `mac_fade.py` / `mac_se.py`
不一致就报错。无法静态断定的内容列在 unknowns 中。
"""
import argparse
import hashlib
import json
import struct
from pathlib import Path

import mac_reader  # noqa: F401  由它把 移植验证/ 加入 sys.path
import MAC_命令表提取 as common
import mac_fade
import mac_se
import 状态字证据 as state_evidence

FADE_START_HANDLER = 0x11E398
FADE_WAIT_HANDLER = 0x11E5B0
FADE_WAIT_OBJECT_GETTER = 0x17F518
TRANSITION_TABLE = 0x2140F0
TRANSITION_ENTRY_BYTES = 12
COLOR_OBJECT = 0x4C750
STORED_COLOR = 0x4C74C
SE_DEL_HANDLER = 0x11D0E8
SE_DEL_CALL = 0x12D478


def expect_sequence(dis, start, size, wanted, label):
    code = [f"{item['mnemonic']} {item['op']}" for item in dis.read(start, size)]
    for text in wanted:
        if text not in code:
            raise ValueError(f'{label} 缺少 {text}；实际前几条：{code[:8]}')
    return code


def fade_start_evidence(dis, data, segs):
    expect_sequence(dis, FADE_START_HANDLER, 0x140, [
        'lbu $a1, 1($s0)',
        'lh $a0, 2($s0)',
        'lhu $v1, 4($s0)',
        'andi $v0, $v1, 0xf000',
        'addiu $v1, $zero, 0xfff',
        'beq $v0, $v1, 0x11e428',
        'jal 0x115730',
    ], 'fade_start 参数读取')
    expect_sequence(dis, FADE_START_HANDLER, 0x1F0, [
        'beq $a1, $a0, 0x11e488',
        'andi $s0, $v0, 0x7f',
        'jal 0x17f468',
        'addiu $v0, $v0, 8',
    ], 'fade_start 方向与前进量')
    table = state_evidence.table_at(data, segs, TRANSITION_TABLE, 3)
    if table != [20, 21, 0]:
        raise ValueError(f'过渡表首项与预期不符: {table}')
    return {
        'handler': f'0x{FADE_START_HANDLER:08X}',
        'length': 8,
        'parameters': {
            'byte1': {'name': '方向位（bit7）与保留的索引（低 8 位）',
                      'read_at': '0x0011E44C',
                      'writes': {'0x0011E478': '方向位 0 时把低 7 位写回存储字',
                                 '0x0011E4AC': '方向位 1 时写 0x80 | 旧低 7 位'}},
            'u16_at_2': {'name': '时长操作数', 'read_at': '0x0011E448',
                         'resolved_by': '0x115730（立即数/状态字）',
                         'clamp': '≤0 时按 1 处理（0x0011E458–0x0011E464 的 slt/movz）'},
            'u16_at_4': {'name': '颜色字', 'read_at': '0x0011E3BC',
                         'reuse_when': '高 4 位非 0（0x0011E3C0 的 andi 0xF000）',
                         'white_when': '低 12 位 = 0xFFF（0x0011E3F4 → 0x0011E428）',
                         'rgb444_expand': 'r=(v>>8)<<4、g=v&0xF0、b=(v&0xF)<<4'
                                          '（0x0011E40C/0x0011E410/0x0011E418）'},
            'bytes_6_7': {'name': '未读取', 'note': '处理函数只 lhu 4($s0)'},
        },
        'color_storage': {'stored_word': f'0x{STORED_COLOR:X}（gp-0x6D44 起）',
                          'object': f'0x{COLOR_OBJECT:X}（gp-0x6D44 起）',
                          'writer': '0x0011E478 / 0x0011E4AC',
                          'reader': '0x0011E4BC'},
        'transition_table': {
            'base': f'0x{TRANSITION_TABLE:X}',
            'entry_bytes': TRANSITION_ENTRY_BYTES,
            'lookup': '*(0x2140F0 + (ip[1]&0x7F)*12)（0x0011E4CC–0x0011E4EC）',
            'entry_0': {'word_0': table[0], 'word_1': table[1], 'type': table[2]},
            'word_choice': '方向位 1 → +0；方向位 0 → +4（0x0011E4CC–0x0011E524）',
        },
        'advance': {'bytes': 8, 'site': '0x0011E57C–0x0011E58C'},
        'evidence': [f"{item['at']}: {item['mnemonic']} {item['op']}"
                     for item in dis.read(FADE_START_HANDLER, 0x40)],
        'confidence': ('proven：长度、参数位置、颜色展开、时长读取、表项选择、前进量；'
                       'unproven：方向命名，见 unknowns'),
    }


def fade_wait_evidence(dis):
    expect_sequence(dis, FADE_WAIT_HANDLER, 0x150, [
        'jal 0x17f518',
        'bnel $v0, $s0, 0x11e6dc',
        'addiu $v0, $v0, 4',
    ], 'fade_wait 轮询与前进量')
    getter = dis.read(FADE_WAIT_OBJECT_GETTER, 8)
    state_evidence.expect(f"{getter[1]['mnemonic']} {getter[1]['op']}", 'lbu $v0, ($a0)',
                          '过渡对象读取函数')
    return {
        'handler': f'0x{FADE_WAIT_HANDLER:08X}',
        'length': 4,
        'parameters': '无；ip[1..3] 未读取',
        'completion': {'getter': f'0x{FADE_WAIT_OBJECT_GETTER:08X} 返回过渡对象 +0',
                       'condition': '等于 1 时前进（0x0011E6A0–0x0011E6CC）',
                       'otherwise': '清 ctx+0xD，不前进（0x0011E6DC）'},
        'advance': {'bytes': 4, 'site': '0x0011E6C0–0x0011E6CC'},
        'confidence': 'proven（等待条件与前进量）',
    }


def se_del_evidence(dis):
    expect_sequence(dis, SE_DEL_HANDLER, 0x30, [
        'lbu $a0, 1($v1)',
        'jal 0x12d478',
        'addiu $v0, $v0, 4',
    ], 'se_del 通道与前进量')
    return {
        'handler': f'0x{SE_DEL_HANDLER:08X}',
        'length': 4,
        'parameters': {'byte1': {'name': '通道号', 'read_at': '0x0011D104'}},
        'call': {'target': f'0x{SE_DEL_CALL:08X}', 'argument': 'ip[1]',
                 'site': '0x0011D100–0x0011D104'},
        'advance': {'bytes': 4, 'site': '0x0011D110–0x0011D11C'},
        'confidence': 'proven（通道号、调用目标、前进量）',
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
    for opcode, info in ((mac_fade.FADE_START, (FADE_START_HANDLER, 8)),
                         (mac_fade.FADE_WAIT, (FADE_WAIT_HANDLER, 4)),
                         (mac_se.SE_DEL, (SE_DEL_HANDLER, 4))):
        state_evidence.expect(table[opcode]['handler'], info[0], f'{table[opcode]["name"]} 处理函数')
        state_evidence.expect(table[opcode]['bytes'], info[1], f'{table[opcode]["name"]} 长度')
    payload = {
        'elf': str(common.ELF),
        'elf_sha256': hashlib.sha256(data).hexdigest(),
        'decode_mode': 'MIPS64 little-endian (capstone)',
        'command_table': {
            '0x68': {k: table[mac_fade.FADE_START][k] for k in ('name', 'bytes', 'handler')},
            '0x69': {k: table[mac_fade.FADE_WAIT][k] for k in ('name', 'bytes', 'handler')},
            '0x3B': {k: table[mac_se.SE_DEL][k] for k in ('name', 'bytes', 'handler')},
        },
        'fade_start': fade_start_evidence(dis, data, segs),
        'fade_wait': fade_wait_evidence(dis),
        'se_del': se_del_evidence(dis),
        'unknowns': [
            '方向命名：ELF 只证明 ip[1] 最高位选择过渡表项 +0/+4，没有字符串说明哪边是淡出；'
            '产物按同一过渡“先出后进”的指令顺序命名，属于顺序推断。',
            '过渡表项 +8 的 type（首项为 0）与 0x109568/0x17E488 两个分支的实际渲染差异未核实。',
            '时长单位：ip[2..3] 的 0x1E00 原样传给过渡对象 +8，未确认是帧、毫秒还是定点数。',
            '颜色字高 4 位非 0 时复用上一次颜色的原因（可能是 alpha/标志位）未核实。',
            'WebGAL 侧没有对应的全屏颜色渐变命令，因此只记录、不映射。',
        ],
    }
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'输出 {args.output}：fade_start 8 字节、fade_wait 4 字节、se_del 4 字节；'
          f'过渡表首项 {payload["fade_start"]["transition_table"]["entry_0"]}')


if __name__ == '__main__':
    main()
