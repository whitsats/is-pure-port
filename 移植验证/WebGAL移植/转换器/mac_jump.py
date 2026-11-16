"""`ext_goto` 的已核实子集：解析跨剧本资源号、目标文件与入口。

证据来自 `输出-保护边修复/SYSTEM/SLPM_665.70`，现场复核见 `转换器/跳转与等待证据.py`，
产物 `数据/跳转与等待ELF证据.json`，说明见 `验证/等待与跨剧本跳转.md`。

- `ext_goto`（`0x06`，4 字节）处理函数 `0x001196B8`：只读 `lhu ip[2]`
  （`0x00119708`），把它作为资源号交给 `0x12D980(style=0, code)`（`0x0011970C`）；
  `0x12D980` 在 style 0 时转 `0x12D810(code)`。资源号高 4 位是组、低 12 位是索引
  （`0x12D81C`/`0x12D820`）。
- 组 0 的处理函数 `0x12D850` 从运行时表取索引对应的名字，用 `%s.BIP`
  （ELF `0x270078`）拼文件名；读完后 `0x119774`–`0x119780` 把
  `ctx+0x44` 结构的 `+0xC` 指针作为新的 `ip`，即跳入目标剧本。
- 目标文件按既有 `MAC_命令表/跨剧本跳转候选.tsv` 的候选规则取
  `MAC_{index:03}.bin`；本模块不假设运行时名字表已经静态证实，只验证目标文件头
  `09 11 00 60 08 00 00 00` 与第 0 入口 `u32@8`。
"""
import struct
from pathlib import Path

from mac_state import UnsupportedCommand

EXT_GOTO = 0x06
EXT_CALL = 0x07
EXT_RETURN = 0x08
INT_GOTO = 0x03
INT_CALL = 0x04
INT_RETURN = 0x05

SCRIPT_HEADER = bytes.fromhex('09 11 00 60 08 00 00 00')
JUMP_NOTE = ('ext_goto 会切换原程序的剧本缓冲并把 ip 指向目标剧本；转换器记录跳转事件，'
             '使用 --scene-dir 时在父场景末生成 changeScene，不生成其他伪造命令。')
INT_GOTO_NOTE = ('int_goto 只把 ip 换成同一剧本的绝对偏移；转换器按命令边界跟进并记录事件，'
                 '这是原程序的控制流，不需要生成 WebGAL 命令。')


def parse_int_goto(raw):
    """解析 8 字节 `int_goto`，返回同一剧本内的绝对偏移。

    处理函数 `0x00119590`：`ip = script_base + u32@4`，没有状态机、不读
    `ip[1]`，也不写状态块。目标必须已经落在解析器识别出的命令边界上，
    否则调用方停止，不猜测指令长度。
    """
    if len(raw) != 8 or raw[0] != INT_GOTO:
        raise UnsupportedCommand('不是 8 字节 int_goto')
    return struct.unpack_from('<I', raw, 4)[0]


def parse_int_call(raw):
    if len(raw) != 8 or raw[0] != INT_CALL:
        raise UnsupportedCommand('不是 8 字节 int_call')
    return struct.unpack_from('<I', raw, 4)[0]


def parse_int_return(raw):
    if len(raw) != 4 or raw[0] != INT_RETURN:
        raise UnsupportedCommand('不是 4 字节 int_return')


def parse_ext_goto(raw, scripts_dir):
    """解析 4 字节 `ext_goto`，验证目标文件头并返回入口。

    `scripts_dir` 是 `输出-保护边修复/MAC`；目标文件缺失或头部不符时抛
    `UnsupportedCommand`，不猜测目标。
    """
    if len(raw) != 4 or raw[0] != EXT_GOTO:
        raise UnsupportedCommand('不是 4 字节 ext_goto')
    resource = raw[2] | (raw[3] << 8)
    group, index = resource >> 12, resource & 0xFFF
    if group != 0:
        raise UnsupportedCommand(f'未核实的 ext_goto 资源组 {group}（资源号 {resource:#06X}）')
    target = Path(scripts_dir) / f'MAC_{index:03}.bin'
    if not target.is_file():
        raise UnsupportedCommand(f'ext_goto 目标文件不存在: {target.name}')
    data = target.read_bytes()
    if len(data) < 12 or data[:8] != SCRIPT_HEADER:
        raise UnsupportedCommand(f'ext_goto 目标文件头不符: {target.name}')
    entry = struct.unpack_from('<I', data, 8)[0]
    if entry >= len(data):
        raise UnsupportedCommand(f'ext_goto 目标入口越界: {target.name}+0x{entry:X}')
    return {
        'resource': f'0x{resource:04X}',
        'group': group,
        'index': index,
        'target_script': target.name,
        'target_entry': entry,
        'target_entry_hex': f'0x{entry:06X}',
        'target_header': data[:8].hex(' '),
        'unused_bytes': raw[1:2].hex(),
        'mapping_source': '数据来源：MAC_命令表/跨剧本跳转候选.tsv 的候选规则（group 0 → MAC_xxx.bin）',
        'effect': (f'读取 group 0 资源 #{index}（{target.name}），把 ip 指向其第 0 入口 '
                   f'0x{entry:06X}'),
        'webgal': {'mapped': False, 'reason': JUMP_NOTE},
    }
