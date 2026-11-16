"""消息窗模式与画面显示指令的已证实子集。

证据见 `数据/画面指令ELF证据.json`（由 `转换器/画面指令证据.py` 现场反汇编生成）。

`msg_mode`（操作码 `0x13`，4 字节）处理函数 `0x0011A678`：
- 只读 `ip[1]`（`0x0011A6D0` / `0x0011A6D4`）；`ip[2]`、`ip[3]` 没有任何读取，属于未使用字节。
- 转调 `0x00122EB0(mode)`：按当前窗口槽位 `idx = *(state+0x3553C)` 写窗口记录
  `*(gp-0x6D40) + idx*0x5FF8`：
  `+0x30 = 6`（`0x00122EF0`）、`+0x19 = mode`（`0x00122EF8`，模式 6 会跳过这一条）、
  `+0x4C/+0x50 = x/y`（`0x00123888`/`0x001238AC`）、`+0x54/+0x58 = w/h`
  （`0x001238D0`/`0x001238F4`）、`+0x38 = aux`（`0x00123964`）、`+0xA4 = 行数`（`0x00122FC4`）。
- 记录的“上次模式”读自 `state + 0x3555 + idx*0x5FF8`（`0x0011A6C8`）；与参数不同时，
  `0x0011A6E0` 调 `0x001241F8`，后者只有一条 `sw $a0, -0x79f8($gp)`（`0x001241FC`），
  即把 `mode+1` 挂到全局待更新标志上，由 `0x001230D8`–`0x00123174` 取走并清零。

`graph_disp`（操作码 `0x33`，8 字节）处理函数 `0x0011C2E8`：
- 两个上下文分支（`lh 0x10($s4)` 为 0 时 `0x0011C340`，为 1 时 `0x0011C480`），
  最后都在 `0x0011C4DC` 做 `ip += 8`，因此对控制流没有影响。
- `ip[1]` = 记录条数（`0x0011C350`/`0x0011C400`，循环上界 `s0 = ip[1]-1`）；
  `ip[2]` 存入 `state+0x1B38`（`0x0011C368`）；`u32@4` 是记录块内偏移（`0x0011C320`–`0x0011C328`）。
- 每条记录 12 字节（`0x0011C390`–`0x0011C3A4` 的 `3n*4`）；记录 `+4` 的 u16 高 4 位是资源组
  （`0x0011C3C0` 的 `srl 0xC`），低 12 位是组内编号。

只实现 5/6 两个消息窗模式与“记录已显示”这一层含义；其余模式或参数一律抛
`UnsupportedCommand`，由调用方记录为停止原因。
"""
import struct

from mac_state import UnsupportedCommand

MSG_MODE = 0x13
GRAPH_DISP = 0x33
GRAPH_POS = 0x2C
GRAPH_PRIO = 0x2E

# 窗口记录里各字段的偏移（0x123868/0x1238B0/0x123940 写入的位置）。
RECORD_FIELDS = {'x': 0x4C, 'y': 0x50, 'w': 0x54, 'h': 0x58, 'aux': 0x38,
                 'class': 0x30, 'mode': 0x19, 'lines': 0xA4}

# 0x122EB0 里两个已核实的模式分支；值全部来自反汇编中的立即数。
MSG_MODES = {
    5: {'class': 6, 'x': 0xAE, 'y': 0x158, 'w': 0x23C, 'h': 0x4E, 'aux': 0x190, 'lines': 0xB},
    6: {'class': 6, 'x': 0x4A, 'y': 0x158, 'w': 0x23C, 'h': 0x4E, 'aux': 0x1EC, 'lines': 0xB},
}
# 0x122EF4：模式 6 直接跳到几何设置，不写 +0x19。
MSG_MODES_WITHOUT_MODE_BYTE = {6}

GRAPH_GROUP_NAMES = {1: 'BG', 2: 'EV', 3: 'CHR'}
GRAPH_RECORD_BYTES = 12


def parse_msg_mode(raw):
    """解析 4 字节 msg_mode，返回 {mode, record, mode_byte_written, ...}。"""
    if len(raw) != 4 or raw[0] != MSG_MODE:
        raise UnsupportedCommand('不是 4 字节 msg_mode')
    mode = raw[1]
    if mode not in MSG_MODES:
        raise UnsupportedCommand(f'未核实的 msg_mode 模式 {mode}')
    geometry = dict(MSG_MODES[mode])
    return {'mode': mode, 'geometry': geometry,
            'mode_byte_written': mode not in MSG_MODES_WITHOUT_MODE_BYTE,
            'unused_bytes': raw[2:].hex(),
            'summary': (f'消息窗改用模式 {mode}：x=0x{geometry["x"]:X}、y=0x{geometry["y"]:X}、'
                        f'w=0x{geometry["w"]:X}、h=0x{geometry["h"]:X}、{geometry["lines"]} 行；'
                        '两个已核实的模式都只改几何，不改显隐')}


def parse_graph_disp(raw):
    """解析 8 字节 graph_disp，返回 {count, flag, blob_offset}。"""
    if len(raw) != 8 or raw[0] != GRAPH_DISP:
        raise UnsupportedCommand('不是 8 字节 graph_disp')
    count = raw[1]
    flag = raw[2]
    blob_offset = struct.unpack_from('<I', raw, 4)[0]
    if count == 0:
        raise UnsupportedCommand('graph_disp 记录条数为 0，原程序行为未核实')
    return {'count': count, 'flag': flag, 'blob_offset': blob_offset,
            'unused_bytes': raw[6:].hex()}


def parse_graph_pos(raw, state=None):
    """解析 8 字节 graph_pos；只记录图层位置，不伪造 WebGAL 画面映射。

    处理函数 `0x0011C888` 依次读取 ip[2..3]、ip[4..5] 两个操作数，再以
    ip[1] 为图层号调用 `0x0012B628` 写入图形记录。它不读取剧情位表，也不
    影响脚本前进；WebGAL 侧暂不播放这条位置变化。
    """
    if len(raw) != 8 or raw[0] != GRAPH_POS:
        raise UnsupportedCommand('不是 8 字节 graph_pos')
    layer = raw[1]
    x_operand = struct.unpack_from('<H', raw, 2)[0]
    y_operand = struct.unpack_from('<H', raw, 4)[0]
    x = state.read(x_operand) if state is not None else None
    y = state.read(y_operand) if state is not None else None
    return {
        'layer': layer,
        'x_operand': f'0x{x_operand:04X}',
        'y_operand': f'0x{y_operand:04X}',
        'x': x,
        'y': y,
        'unused_bytes': raw[6:].hex(),
        'effect': ('按图层号把两个操作数的值写入图形位置记录；不改变剧情状态，'
                   '不生成 WebGAL 画面命令'),
        'webgal': {'mapped': False,
                   'reason': '只记录坐标，未映射到 WebGAL 的立绘/背景位置；不影响脚本前进。'},
        'evidence': {
            'handler': '0x0011C888',
            'reads': 'ip[1] 图层号；ip[2..3]、ip[4..5] 两个操作数',
            'writes': '0x0012B628 的图形记录 +8/+0xC',
        },
    }


def apply_graph_prio(raw, state):
    """按 0x11C900/0x12B1C8 写画面槽位的优先级；不伪造 WebGAL 图层。"""
    if len(raw) != 4 or raw[0] != GRAPH_PRIO:
        raise UnsupportedCommand('不是 4 字节 graph_prio')
    layer = raw[1]
    argument = struct.unpack_from('<H', raw, 2)[0]
    priority = min(argument, 9)
    offset = 0x3DEFD + layer * 0x108
    state.write_context_u8(offset, priority)
    return {'layer': layer, 'argument': argument, 'priority': priority,
            'state_offset': f'0x{offset:05X}',
            'webgal': {'mapped': False, 'reason': '已记录并写入原画面槽位优先级，WebGAL 图层映射尚未完成。'},
            'evidence': {'handler': '0x0011C900：lbu ip[1]、lhu ip[2]、前进 4 字节',
                         'callee': '0x0012B1C8：参数夹至 0..9，写 G+0x3DEFD+layer*0x108'}}


def resolve_graph_records(data, blob_offset, count):
    """按记录块偏移读出记录，解释资源组与组内编号。

    记录块偏移是脚本文件内偏移：既有 `数据/画面资源候选.tsv` 里 `MAC_000.bin` 的
    `0x0000D4` 条目的“记录偏移 0x000754”与本指令的 u32@4 = 0x000754 相同。
    """
    if not data:
        raise UnsupportedCommand('没有脚本原始字节，无法解析画面记录')
    # 原程序里的循环从最后一条往第一条走：s1 先加 (count-1)*12（0x0011C3A4），
    # 每轮再减 0xC（0x0011C3BC）。这里保持同一顺序，并在记录里标出序号。
    start = blob_offset + GRAPH_RECORD_BYTES * count - GRAPH_RECORD_BYTES
    records = []
    for index in range(count):
        offset = start - GRAPH_RECORD_BYTES * index
        if offset < 0 or offset + GRAPH_RECORD_BYTES > len(data):
            raise UnsupportedCommand(f'画面记录越界: 0x{offset:06X}')
        chunk = data[offset:offset + GRAPH_RECORD_BYTES]
        code = struct.unpack_from('<H', chunk, 4)[0]
        group, member = code >> 12, code & 0xFFF
        # 组内编号 0xFFF 是特殊编号（既有 数据/画面资源候选.tsv 里没有对应文件）；
        # 其余按既有证据把编号乘 2 才是文件名（259 → CHR_0518.png）。
        name = GRAPH_GROUP_NAMES.get(group)
        candidate = (f'{name}/{name}_{member * 2:04d}.png'
                     if name and member != 0xFFF else None)
        records.append({'record_index': index, 'record_offset': offset, 'raw_hex': chunk.hex(' '),
                        'code': code, 'group': group, 'group_name': name or '?',
                        'member': member, 'candidate': candidate,
                        'summary': (f'第 {index + 1} 条记录（文件偏移 0x{offset:06X}）：资源 {code:#06X} → '
                                    f'{name or "未知组"} 组内 #{member}'
                                    + (f'，候选 {candidate}' if candidate else '，特殊编号，没有对应图片'))})
    return records
