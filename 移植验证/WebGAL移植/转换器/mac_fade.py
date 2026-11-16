"""`fade_start` / `fade_wait` 的已核实子集：解码参数、记录淡入淡出，不映射画面。

证据来自 `输出-保护边修复/SYSTEM/SLPM_665.70`，现场复核见 `转换器/淡入淡出证据.py`，
产物 `数据/淡入淡出ELF证据.json`，说明见 `验证/淡入淡出与se_del.md`。

- `fade_start`（`0x68`，8 字节）处理函数 `0x0011E398`：
  `lhu` 读 `ip[4..5]` 作颜色字（`0x0011E3BC`）。高 4 位非 0 时不写入新颜色，
  而是读回上一次存下的颜色（`0x0011E3C0` 的 `andi 0xF000` 分支）；低 12 位
  `0xFFF` 特判为 RGB(255,255,255)（`0x0011E3F4` → `0x0011E428`），其余按
  `(r<<4, g, b<<4)` 展开（`0x0011E40C`/`0x0011E410`/`0x0011E418`）。
  `lh ip[2..3]` 经 `0x0011E444` 调 `0x115730` 读取时长操作数，≤0 时钳到 1。
  `ip[1]` 的最高位选择过渡表项 `+0`/`+4`（`0x0011E460` 与 `0x0011E488`），
  低 7 位属于上一次保留下来的索引，本指令不重写它。
- `fade_wait`（`0x69`，4 字节）处理函数 `0x0011E5B0`：轮询过渡对象 `+0`
  （`0x0011E5E0` → `0x17F518` 的 `lbu`），等于 1 时把 `ip += 4` 并返回；
  否则清 `ctx+0xD` 等待。原程序会阻塞到淡入淡出结束。

方向命名不是 ELF 里的字符串：`ip[1]` 的最高位只证明选择表项 `+0`/`+4`
（表首项 `(20, 21, 0)`）。产物按同一过渡“先出后进”的指令顺序，把最高位 1
记为 `fade_out`（到颜色），最高位 0 记为 `fade_in`（从该颜色进入）；这一点在
证据 JSON 的 `unknowns` 里标为“方向命名由顺序推断”。

WebGAL 侧没有“全屏渐变到指定颜色后更换画面”的单条命令，因此只写进 `fades`，
`webgal.mapped=false`；样片不会出现原版的白色过渡。
"""
import struct

from mac_state import UnsupportedCommand

FADE_START = 0x68
FADE_WAIT = 0x69

COLOR_WHITE = 0xFFF
COLOR_REUSE_FLAG = 0xF000

FADE_MAPPING_NOTE = ('WebGAL 没有“全屏渐变到指定颜色后更换画面”的单条命令；'
                     '这里只记录方向、时长与颜色，不生成语句，也不改变样片背景。')
FADE_WAIT_NOTE = ('原程序在这里轮询过渡对象、完成前不前进；移植版没有对应的画面过渡，'
                  '所以不阻塞，节奏会比原版短一个淡入淡出时长。')


def decode_color(word):
    """把 `fade_start` 的 16 位颜色字展开成 RGB；返回 (color_value, rgb)。"""
    value = word & 0xFFF
    if value == COLOR_WHITE:
        return value, (0xFF, 0xFF, 0xFF)
    return value, (((value >> 8) & 0xF) << 4, value & 0xF0, (value & 0xF) << 4)


def parse_fade_start(raw, state, previous_color=None):
    """解析 8 字节 `fade_start`。

    `previous_color` 是上一次成功指定的 12 位颜色；颜色字高 4 位非 0 时复用它。
    """
    if len(raw) != 8 or raw[0] != FADE_START:
        raise UnsupportedCommand('不是 8 字节 fade_start')
    flag = raw[1]
    duration_operand = struct.unpack_from('<H', raw, 2)[0]
    color_word = struct.unpack_from('<H', raw, 4)[0]
    reuse = bool(color_word & COLOR_REUSE_FLAG)
    if reuse:
        if previous_color is None:
            raise UnsupportedCommand('fade_start 要求复用颜色，但此前没有指定过颜色')
        color_value = previous_color
        color_source = 'reuse'
    else:
        color_value = color_word & 0xFFF
        color_source = 'specified'
    _, rgb = decode_color(color_value)
    duration = max(1, state.read(duration_operand))
    direction = 'fade_out' if flag & 0x80 else 'fade_in'
    return {
        'flag': flag,
        'direction': direction,
        'direction_basis': ('ip[1] 最高位选择过渡表项 +0/+4（0x0011E460/0x0011E488）；'
                            '命名按同一过渡先出后进的顺序推断'),
        'table_word': 0 if flag & 0x80 else 4,
        'duration_operand': f'0x{duration_operand:04X}',
        'duration': duration,
        'color_word': f'0x{color_word:04X}',
        'color_source': color_source,
        'color': f'0x{color_value:03X}',
        'rgb': list(rgb),
        'unused_bytes': raw[6:].hex(),
        'effect': (f'{direction}：{duration} 个单位、颜色 RGB{rgb}；'
                   f'{"复用上一次颜色" if reuse else "本次指定颜色"}'),
        'webgal': {'mapped': False, 'reason': FADE_MAPPING_NOTE},
    }


def parse_fade_wait(raw):
    """解析 4 字节 `fade_wait`；原程序等待过渡对象完成。"""
    if len(raw) != 4 or raw[0] != FADE_WAIT:
        raise UnsupportedCommand('不是 4 字节 fade_wait')
    return {
        'blocks_in_original': True,
        'waited': False,
        'unused_bytes': raw[1:].hex(),
        'effect': '轮询过渡对象 +0，等于 1 才前进（0x0011E5E0 → 0x17F518）',
        'webgal': {'mapped': False, 'reason': FADE_WAIT_NOTE},
    }
