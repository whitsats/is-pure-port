"""从 ELF 抽取 `time_wait` / `ext_goto` 的可复核证据，写成 JSON。

每条结论都带地址；能从指令字节算出的常量一律现算，与 `mac_wait.py` /
`mac_jump.py` 不一致就报错。无法静态断定的内容列在 unknowns 中。
"""
import argparse
import csv
import hashlib
import json
import struct
from pathlib import Path

import mac_reader  # noqa: F401  由它把 移植验证/ 加入 sys.path
import MAC_命令表提取 as common
import mac_jump
import mac_wait
import 状态字证据 as state_evidence

TIME_WAIT_HANDLER = 0x119258
TIME_HELPER_SET = 0x11FD00
TIME_HELPER_DONE = 0x11FD18
TIMER_SLOT = 0x10DF38
TIMER_INCREMENT = 0x10DF48
TIMER_CALL_SITE = 0x1132BC
EXT_GOTO_HANDLER = 0x1196B8
INT_GOTO_HANDLER = 0x119590
SCRIPT_LOAD = 0x12D980
SCRIPT_WAIT = 0x12DA38
FILE_GROUP_DISPATCH = 0x12D810
GROUP_TABLE = 0x259FD0
GROUP_ZERO_HANDLER = 0x12D850
NAME_FORMAT = 0x270078
SCRIPT_COPY = 0x1FBAD4


def expect_sequence(dis, start, size, wanted, label):
    code = [f"{item['mnemonic']} {item['op']}" for item in dis.read(start, size)]
    for text in wanted:
        if text not in code:
            raise ValueError(f'{label} 缺少 {text}；实际前几条：{code[:8]}')
    return code


def time_wait_evidence(dis):
    expect_sequence(dis, TIME_WAIT_HANDLER, 0x110, [
        'lbu $a1, 1($s1)',
        'lh $a0, 2($s1)',
        'jal 0x115730',
        'jal 0x11fd00',
        'jal 0x11fd18',
        'addiu $v0, $v0, 4',
        'sh $s2, 0x10($s0)',
    ], 'time_wait 参数/状态/前进量')
    expect_sequence(dis, TIME_HELPER_DONE, 0x30, [
        'lw $v1, -0x6de8($gp)',
        'subu $v1, $v1, $a2',
        'slt $v0, $v1, $v0',
        'sltiu $a2, $v0, 1',
        'beq $a3, $t0, 0x11fda0',
    ], 'time_wait 完成条件')
    expect_sequence(dis, TIME_HELPER_SET, 0x10, [
        'sw $a1, 4($a0)',
        'sw $v0, 8($a0)',
    ], 'time_wait 计时对象初始化')
    expect_sequence(dis, TIMER_SLOT, 0x18, [
        'lw $v0, -0x6de8($gp)',
        'addiu $v0, $v0, 1',
        'sw $v0, -0x6de8($gp)',
    ], '计时器递增')
    expect_sequence(dis, TIMER_CALL_SITE, 8, ['jal 0x10df38'], '计时器调用点')
    return {
        'handler': f'0x{TIME_WAIT_HANDLER:08X}',
        'length': 4,
        'parameters': {
            'byte1': {'name': '模式', 'read_at': '0x001192E0',
                      'supported': {'1': '计时到点（0x11FDA0 分支）'},
                      'unknown': ['0', '2', '3']},
            'u16_at_2': {'name': '时长操作数', 'read_at': '0x001192BC/0x001192C4',
                         'resolved_by': '0x115730（立即数或状态字）',
                         'stored_at': '0x0011FD04（计时对象 +4）'},
        },
        'timer': {'slot': '*(gp-0x6DE8)', 'increment_site': f'0x{TIMER_INCREMENT:08X}',
                  'increment': 1, 'call_site': f'0x{TIMER_CALL_SITE:08X}',
                  'frame_hz': mac_wait.FRAME_HZ,
                  'basis': '递增函数在帧循环 0x1132BC 调用；按 60 Hz 换算为毫秒'},
        'completion': {
            'helper': f'0x{TIME_HELPER_DONE:08X}',
            'formula': 'elapsed = *(gp-0x6DE8) - start；elapsed >= duration 时 a2 = 1',
            'mode_1': 'mode==1 时若全局 +0x47C == 1 立即完成（0x11FDA0 分支）',
        },
        'state_machine': {
            'state_pointer': 'ctx+0x10 的 16 位状态（lh 0x10(ctx)）',
            'state_0': '把模式/时长写进计时对象（0x11FD00），状态转 1；本次不 ip+=4',
            'state_1': '调 0x11FD18 检查完成；完成且全局 +0x47C != 1 时 ip += 4',
            'note': '转换器把整段等待合并为一次 wait；初始化/检查之间的调度次数不影响总时长，但没有逐帧模拟。',
        },
        'advance': {'bytes': 4, 'sites': ['0x0011930C–0x00119318', '0x00119324–0x00119330']},
        'webgal': {'command': 'wait:<ms>', 'mapping': mac_wait.WAIT_NOTE},
        'confidence': 'proven：参数位置、计时对象、计时器递增、模式 1 的完成条件、前进量；'
                      'unknown：每帧调用次数未实测，模式 0/2/3 语义。',
    }


def ext_goto_evidence(dis, data, segs, scripts_dir):
    expect_sequence(dis, EXT_GOTO_HANDLER, 0x100, [
        'lhu $a1, 2($a0)',
        'jal 0x12d980',
        'jal 0x12da38',
        'lw $a0, 0xc($v0)',
        'jal 0x1fbad4',
        'jal 0x117dc0',
        'sw $a1, 8($a2)',
    ], 'ext_goto 读取/加载/切换 ip')
    expect_sequence(dis, FILE_GROUP_DISPATCH, 0x30, [
        'srl $s0, $a0, 0xc',
        'andi $a1, $a0, 0xfff',
    ], '资源号拆分')
    expect_sequence(dis, GROUP_ZERO_HANDLER, 0x10, [
        'lw $a2, -0x13b4($v0)',
    ], '组 0 名字表')
    table = state_evidence.table_at(data, segs, GROUP_TABLE, 8)
    if table[0] != GROUP_ZERO_HANDLER:
        raise ValueError(f'组 0 处理函数与预期不符: {table[0]:#x}')
    name_fmt = data[state_evidence.vaddr_to_offset(segs, NAME_FORMAT, 8):][:8]
    if not name_fmt.startswith(b'%s.BIP'):
        raise ValueError(f'组 0 文件名格式与预期不符: {name_fmt!r}')
    probe_target = Path(scripts_dir) / 'MAC_001.bin'
    probe = probe_target.read_bytes()
    if probe[:8] != mac_jump.SCRIPT_HEADER:
        raise ValueError('MAC_001.bin 文件头与预期不符')
    probe_entry = struct.unpack_from('<I', probe, 8)[0]
    return {
        'handler': f'0x{EXT_GOTO_HANDLER:08X}',
        'length': 4,
        'parameters': {
            'byte1': {'name': '未读取', 'note': '处理函数只 lhu 2($a0)'},
            'u16_at_2': {'name': '资源号', 'read_at': '0x00119708',
                         'split': '高 4 位组、低 12 位索引（0x12D81C/0x12D820）',
                         'passed_to': f'0x{SCRIPT_LOAD:08X}(style=0, code)'},
        },
        'load': {'script_loader': f'0x{SCRIPT_LOAD:08X}',
                 'wait': f'0x{SCRIPT_WAIT:08X}',
                 'group_dispatch': f'0x{FILE_GROUP_DISPATCH:08X}',
                 'group_table': f'0x{GROUP_TABLE:X}',
                 'group_zero_handler': f'0x{GROUP_ZERO_HANDLER:08X}',
                 'group_zero_format': '%s.BIP（0x270078）'},
        'switch': {'copy_call': f'0x{SCRIPT_COPY:08X}',
                   'new_ip_from': 'ctx+0x44 结构 +0xC（0x00119758/0x00119774–0x00119780）',
                   'advance': '不是 ip+4；把 ip 换成目标剧本缓冲区指针'},
        'state_machine': {
            'state_pointer': 'ctx+0x10 的 16 位状态（lh 0x10(s0)，0x001196D0）',
            'state_0': '只把状态置 1（0x001196EC），本次不读资源、不换 ip',
            'state_1': '读 u16@2 并调 0x12D980 启动加载（0x00119708）',
            'state_2': '调 0x12DA38 等待加载完成，然后复制并替换 ip（0x00119724–0x00119780）',
            'note': '转换器把多状态加载视为已完成，直接跳到目标入口；加载等待的帧数未模拟。',
        },
        'target_probe': {'file': probe_target.name,
                         'header': probe[:8].hex(' '),
                         'entry': f'0x{probe_entry:06X}'},
        'webgal': {'mapped': False, 'reason': mac_jump.JUMP_NOTE,
                   'recording': 'jump_events（脚本、偏移、目标文件、入口）'},
        'confidence': 'proven：资源号位置、组 0 分派、%s.BIP 格式、目标文件头/入口、ip 切换；'
                      'unknown：组 0 运行时名字表内容、索引→文件名的静态对应、ext_call/ext_return。',
    }


def int_goto_evidence(dis):
    expect_sequence(dis, INT_GOTO_HANDLER, 0x40, [
        'lw $a1, 0x44($a3)',
        'lw $a2, 8($a1)',
        'lw $v0, 0xc($a1)',
        'lw $v1, 4($a2)',
        'addu $v0, $v0, $v1',
        'jal 0x117dc0',
        'sw $v0, 8($a1)',
    ], 'int_goto 读取目标并替换 ip')
    return {
        'handler': f'0x{INT_GOTO_HANDLER:08X}',
        'length': 8,
        'layout': {'opcode': 0, 'target_u32_at_4': 'u32@4'},
        'effect': 'ip = script_base + u32@4；同一剧本内绝对偏移，不读 ip[1]，不写状态块',
        'evidence': [f"{item['at']}: {item['mnemonic']} {item['op']}"
                     for item in dis.read(INT_GOTO_HANDLER, 0x40)],
        'webgal': {'mapped': True, 'reason': '同一剧本控制流；转换器直接跟进目标命令边界并记录 int_gotos'},
        'confidence': 'proven：目标偏移位置、script_base 加法、ip 替换与 8 字节长度。',
    }


def candidate_row():
    table = Path(__file__).resolve().parents[2] / 'MAC_命令表/跨剧本跳转候选.tsv'
    with table.open(encoding='utf-8-sig', newline='') as f:
        for row in csv.DictReader(f, delimiter='\t'):
            if row['源脚本'] == 'MAC_000.bin' and row['偏移'].upper() == '0X00073C':
                return dict(row)
    raise ValueError('跨剧本候选表中没有 MAC_000 0x73C')


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
    for opcode, info in ((mac_wait.TIME_WAIT, (TIME_WAIT_HANDLER, 4)),
                         (mac_jump.EXT_GOTO, (EXT_GOTO_HANDLER, 4)),
                         (mac_jump.INT_GOTO, (INT_GOTO_HANDLER, 8))):
        state_evidence.expect(table[opcode]['handler'], info[0], f'{table[opcode]["name"]} 处理函数')
        state_evidence.expect(table[opcode]['bytes'], info[1], f'{table[opcode]["name"]} 长度')
    payload = {
        'elf': str(common.ELF),
        'elf_sha256': hashlib.sha256(data).hexdigest(),
        'decode_mode': 'MIPS64 little-endian (capstone)',
        'command_table': {
            '0x0C': {k: table[mac_wait.TIME_WAIT][k] for k in ('name', 'bytes', 'handler')},
            '0x06': {k: table[mac_jump.EXT_GOTO][k] for k in ('name', 'bytes', 'handler')},
            '0x03': {k: table[mac_jump.INT_GOTO][k] for k in ('name', 'bytes', 'handler')},
        },
        'time_wait': time_wait_evidence(dis),
        'ext_goto': ext_goto_evidence(dis, data, segs, args.scripts),
        'int_goto': int_goto_evidence(dis),
        'ext_goto_candidate_row': candidate_row(),
        'unknowns': [
            '计时器 *(gp-0x6DE8) 虽在 0x1132BC 的帧循环里递增，但没有实测每帧调用次数；'
            '转换按 60 Hz 换算毫秒，属于有依据的近似。',
            'time_wait 模式 0/2/3 的输入/跳过语义未核实，转换器遇到即停止。',
            '全局 +0x47C 为 1 时模式 1 立即完成；该标志的触发条件未核实，移植版不模拟提前结束。',
            'ext_goto 组 0 的名字表由运行时模块填充（0xB1FFC4C 相对指针），'
            '索引→MAC_xxx.bin 沿用既有跨剧本候选规则，未静态证明。',
            'ext_call（0x07）/ext_return（0x08）与调用栈未实现。',
            '跳转后原程序是否重置消息窗/状态块未核实；链式转换只保留同一 State 对象。',
        ],
    }
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'输出 {args.output}：time_wait 模式 1、int_goto 0x{INT_GOTO_HANDLER:08X}、'
          f'ext_goto 组 0 → {payload["ext_goto"]["target_probe"]["file"]}'
          f'@{payload["ext_goto"]["target_probe"]["entry"]}')


if __name__ == '__main__':
    main()
