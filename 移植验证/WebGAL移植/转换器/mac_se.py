"""SE 段（`0x3A`/`0x3C`/`0x3D`/`0x3E`/`0x3F`）的已核实子集：解码字节、记账，不映射音频。

证据（`输出-保护边修复/SYSTEM/SLPM_665.70`，现场复核见 `转换器/SE段证据.py`，
产物 `数据/SE段ELF证据.json`，说明见 `验证/文件读取与SE阻塞.md` 与 `验证/SE段解码.md`）：

- `se_speed`（`0x3E`）处理函数 `0x0011D188`：`lbu ip[1]` 取通道号（`0x0011D19C`），
  `lhu ip[2]` 取速度（`0x0011D1A4`），写入通道结构 `+8`（`0x0011D1C8` 的
  `sh $t0, -0xb78($at)`，基址 = `gp-0x6D44` 起 `+0x3F480 + 通道*12`）。
- `se_vol`（`0x3F`）处理函数 `0x0011D1E0`：通道号 `lbu ip[1]`（`0x0011D200`），
  音量 `lbu ip[2]`（`0x0011D22C`）；旧音量 `+2 → +3`（`0x0011D218`/`0x0011D21C`），
  新音量写 `+2`（后续 `sb`）。
- `se_set`（`0x3A`）处理函数 `0x0011D080`，通道号 `lbu ip[1]`（`0x0011D0B8`），
  样本号取 staging 槽位 `ctx+0xD51FA`（`0x0011D0B0`，即上一条 `file_read` 的 code），
  转 `0x12D3D0`：`sh code, 通道+0`（`0x0012D40C`）。之后
  `0x0012D410` 调 `0x107CB8(0x281580+通道)`（对通道对象做 `0x1B7DA8`/`0x1B6FA0`
  两次调用并清 `+3` 标志），再按 `code & 0xFFF` 查 `*(0xB1EC00+0x88)` 字节表与
  `*(0xB1EC00+0x6B90)` u16 表；**仅当字节表值为 2 且句柄 ≠ 0xFFFF** 时
  `j 0x1173E8`（`0x0012D45C`）。
- `se_del`（`0x3B`）处理函数 `0x0011D0E8`：通道号 `lbu ip[1]`，转调
  `0x12D478(通道)` 后 `ip += 4`；用于停止/删除该通道的声音。
- `se_req`（`0x3C`）处理函数 `0x0011D138`：通道号 `lbu ip[1]`，参数 `lhu ip[2]`；
  转 `0x12D4A0`：把参数**低字节**写 `通道+5`（`0x0012D4C0`），`通道+6` 清 0
  （`0x0012D4D0`）。
- `se_wait`（`0x3D`）处理函数 `0x0011CC18`：参数 `lhu ip[2]`（`0x0011CC34`）；
  参数 1 走 `0x0011CC48` → `0x0011CD28`，读全局 `+0x47C` 与通道 `+5`
  （`0x0011CD14` 的 `lb -0xb7b`，即 `+5`），条件不满足时置 `ctx+0xD = 0` 且
  **不前进**（`0x0011CDFC` 一带），即原程序会阻塞到该通道状态改变。

两张表（`+0x88` 字节表、`+0x6B90` u16 表）不是静态数据：`0x00103AD4` 与
`0x00103C20` 把模块头 `+0x40` / `+0x74` 的相对偏移加上装载基址后写进
`0xB1EC00` 结构；装载由启动流程 `0x00108C18`–`0x00108C28` 完成
（`0x101468(a0=8, 'init.bin', 缓冲, 地址)` 之后 `jal 0x1035D8(缓冲)`）。
这些表里放的是运行时句柄与“样本就绪”状态，**没有文件名**；`0x1173E8` 也不接触
文件名（它只做 `0x1053C0` 调用与一张 0x10 字节记录表的遍历）。因此
“编号 0–151 → `se.afs` 条目”无法从 ELF/ISO 上静态定死，本轮不映射任何音频。
"""
from mac_state import UnsupportedCommand

SE_SET = 0x3A
SE_DEL = 0x3B
SE_REQ = 0x3C
SE_WAIT = 0x3D
SE_SPEED = 0x3E
SE_VOL = 0x3F

HANDLERS = {SE_SET: 0x11D080, SE_DEL: 0x11D0E8, SE_REQ: 0x11D138,
            SE_WAIT: 0x11CC18, SE_SPEED: 0x11D188, SE_VOL: 0x11D1E0}

CHANNEL_BASE = 0x3F480          # ctx(gp-0x6D44) 起
CHANNEL_BYTES = 12
CHANNEL_FIELDS = {'code': 0x0, 'volume': 0x2, 'previous_volume': 0x3,
                  'state': 0x5, 'counter': 0x6, 'speed': 0x8}

STAGED_CODE = 0xD51FA

# `(0xB1EC00+0x88)` 字节表与 `(0xB1EC00+0x6B90)` u16 表的写者与来源。
TABLE_WRITERS = {'byte_table': '0x00103AD4（模块头 +0x40）',
                 'handle_table': '0x00103C20（模块头 +0x74）'}
MODULE_LOAD = {'call': '0x00108C1C–0x00108C24',
               'read': '0x101468(a0 = 8, a1 = "init.bin", a2 = 0x00A54700, a3 = 0x00D72980)',
               'init': '0x1035D8(0x00A54700)'}

MAPPING_NOTE = ('SE 段只解码字节并记账：样本表（0xB1EC00+0x88 / +0x6B90）由运行时装载的模块'
                '填写，里面没有文件名，编号到 se.afs 条目的对应无法静态证明，所以不生成任何'
                '声音播放命令或音频路径；se_wait 在原程序会阻塞，这里也不等待。')
WAIT_NOTE = ('原程序在这里会等通道状态改变（0x0011CDFC 一带不前进）；音频未映射，'
             '所以移植版不阻塞，节奏会比原版短一个音效时长。')


def _u16(raw):
    return raw[2] | (raw[3] << 8)


def _check_length(raw, name):
    if len(raw) != 4:
        raise UnsupportedCommand(f'{name} 长度应为 4，实际 {len(raw)}')
    return raw[1], _u16(raw)


def parse_se_speed(raw):
    channel, value = _check_length(raw, 'se_speed')
    return {'channel': channel, 'speed': value, 'writes': {f'0x{CHANNEL_FIELDS["speed"]:X}': value},
            'effect': '把速度写入该通道结构 +8；不产生可见输出',
            'webgal': {'mapped': False, 'reason': MAPPING_NOTE}}


def parse_se_vol(raw):
    channel, value = _check_length(raw, 'se_vol')
    if raw[3] != 0:
        raise UnsupportedCommand(f'se_vol 的参数高位不是 0: {raw[3]:#04x}')
    return {'channel': channel, 'volume': raw[2],
            'writes': {f'0x{CHANNEL_FIELDS["volume"]:X}': raw[2],
                       f'0x{CHANNEL_FIELDS["previous_volume"]:X}': '旧值'},
            'effect': '旧音量搬到 +3，新音量写 +2；不产生可见输出',
            'webgal': {'mapped': False, 'reason': MAPPING_NOTE}}


def parse_se_set(raw, staged_code):
    channel, unused = _check_length(raw, 'se_set')
    if staged_code is None:
        raise UnsupportedCommand('se_set 之前没有 file_read 写入 staging 槽位，样本号未知')
    if unused != 0:
        raise UnsupportedCommand(f'se_set 的参数字节不是 0: {unused:#06x}')
    return {'channel': channel, 'staged_code': f'0x{staged_code:04X}',
            'sample_index': staged_code & 0xFFF,
            'writes': {f'0x{CHANNEL_FIELDS["code"]:X}': f'0x{staged_code:04X}'},
            'effect': '把 staging 的样本号写进通道 +0；是否起播取决于运行时“样本就绪”字节',
            'webgal': {'mapped': False, 'reason': MAPPING_NOTE}}


def parse_se_del(raw):
    channel, unused = _check_length(raw, 'se_del')
    if unused != 0:
        raise UnsupportedCommand(f'se_del 的参数字节不是 0: {unused:#06x}')
    return {'channel': channel,
            'effect': '转调 0x12D478(通道) 停止该通道声音；不产生可见输出',
            'webgal': {'mapped': False, 'reason': MAPPING_NOTE}}


def parse_se_req(raw):
    channel, value = _check_length(raw, 'se_req')
    if value > 0xFF:
        raise UnsupportedCommand(f'se_req 参数超过一字节: {value:#06x}')
    return {'channel': channel, 'parameter': value & 0xFF,
            'writes': {f'0x{CHANNEL_FIELDS["state"]:X}': value & 0xFF,
                       f'0x{CHANNEL_FIELDS["counter"]:X}': 0},
            'effect': '把参数低字节写通道 +5、+6 清 0；参数含义（起播/停止）未证实',
            'webgal': {'mapped': False, 'reason': MAPPING_NOTE}}


def parse_se_wait(raw):
    channel, parameter = _check_length(raw, 'se_wait')
    return {'channel': channel, 'parameter': parameter,
            'blocks_in_original': True, 'waited': False,
            'effect': '原程序按参数轮询通道状态并在未完成时不前进',
            'webgal': {'mapped': False, 'reason': WAIT_NOTE}}


PARSERS = {SE_SPEED: parse_se_speed, SE_VOL: parse_se_vol, SE_DEL: parse_se_del,
           SE_REQ: parse_se_req, SE_WAIT: parse_se_wait}
