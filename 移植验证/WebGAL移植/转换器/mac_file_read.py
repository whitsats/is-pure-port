"""`file_read`（操作码 `0x0F`）与 `file_wait`（`0x10`）的已核实子集。

全部结论来自 `输出-保护边修复/SYSTEM/SLPM_665.70` 的反汇编，现场复核脚本见
`转换器/文件读取证据.py`，产物 `数据/文件读取ELF证据.json`；说明见
`验证/文件读取与SE阻塞.md`。

分派（命令表 `0x213590`，条目 24 字节：`handler, name, ?, mode1, mode2, length`）：
- 只有两处按命令表取址：`0x00117B0C`、`0x00117DFC`；两处都取第一字段
  （`0x00117E04` 的 `lw $v1, ($v0)`），且 `0x117DC0` 把该值写进 `ctx+0`。
- `0x0F` → `handler` `0x00119878`；`0x10` → `0x001198E0`。表里的 `mode1`
  （`0x1183C0`）虽另有实现，但没有任何分派路径引用它。

`file_read` `0x00119878`：
- `a0 = lbu ip[1]`（`0x00119890`，记作 style），`a1 = lhu ip[2]`（`0x00119898`，记作 code）。
- `jal 0x12D980`（`0x00119894`）。返回 0 → `ip += 4`（`0x001198A8`–`0x001198B4`）；
  非 0 → 清 `ctx+0xD`/`ctx+0xE`（`0x001198C0`–`0x001198C8`）且不前进，逐帧重试。

`0x0012D980(style, code)`：
- `style == 0` 时才 `jal 0x12D810(code)`（`0x0012D9D0`）；`style == 1/2` 直接取 0。
- 无论哪条分支，最后都写 staging（`0x0012D9FC`–`0x0012DA18`）：
  `state+0xD51F8 = 1`（挂起）、`+0xD51F9 = style`、`+0xD51FA = code`，并返回 0。

`0x0012D810(code)`（style 0 的唯一读取入口）：
- `group = code >> 12`，`index = code & 0xFFF`（`0x0012D81C`–`0x0012D820`）。
- `group < 8` 时走跳表 `0x259FD0`（`0x0012D844`）：0→`0x12D850`、1→`0x12D860`、
  2→`0x12D878`、3→`0x12D890`、4→`0x12D8A8`、**5→`0x12D8B8`**、6→`0x12D878`、7→`0x12D860`。
- `0x12D8B8` 只有 `addiu $s0,$zero,5` 与 `move $a2,$zero`，随后 `0x12D8C0` 的
  `beql $a2,$zero,0x12D970` 直接返回 0：**不拼文件名、不调用读取**。组 0–4 的
  描述表指针在 BSS（`0xB1EC4C`…）里由启动代码填写，才是真正发起读取的分支。

`file_wait` `0x001198E0` → `0x0012DA38`：
- `state+0xD51F8` 未置位 → 返回 0（视为已完成，`0x0012DA50`）。
- 置位时按 `state+0xD51F9`（style）轮询：style 0 → `0x101A00(-1)`（`0x0012DA80`），
  返回 0 则继续挂起；非 0 时 `0x101A80(-1)`（`0x0012DA90`），把结果写
  `state+0xD51FC`（`0x0012DAB0`）并清挂起位（`0x0012DAA4`）。

原盘统计（74 个 `MAC_*.bin`，`转换器/文件读取证据.py` 复现）：
2321 条 `file_read` 的 `code` 高字节恒为 `0x50`，取值 `0x5000`–`0x5097`（152 种），
且每一条后面紧跟一条 `file_wait`。因此这里只接受 `style == 0` 且 `code >> 8 == 0x50`
的形态；其它形态一律抛 `UnsupportedCommand`，由调用方记录停止原因。

注意：`code` 的低 12 位（0–151）与 `se.afs` 的 174 个条目数量相容，但
**索引到条目的对应尚未证实**（`se_set` 取的是运行时句柄表），所以这里只记录
`index`，不据此引用任何音频文件。
"""
from mac_state import UnsupportedCommand

FILE_READ = 0x0F
FILE_WAIT = 0x10

COMMAND_TABLE = 0x213590
ENTRY_BYTES = 24
HANDLERS = {FILE_READ: 0x119878, FILE_WAIT: 0x1198E0}
GROUP_JUMP_TABLE = 0x259FD0
GROUP_FIVE_HANDLER = 0x12D8B8
GROUP_FIVE_RETURN = 0x12D970
STAGED_FLAG = 0xD51F8
STAGED_STYLE = 0xD51F9
STAGED_CODE = 0xD51FA
STAGED_RESULT = 0xD51FC

# 只有 style 0 会进入 `0x12D810`；只有 code 高字节 0x50（组 5）被证实不发起读取。
SUPPORTED_STYLE = 0
SUPPORTED_GROUP = 5
SUPPORTED_PREFIX = 0x50

VOLUME_TABLE = 0x212E00
VOLUME_ROW_BYTES = 0x20
SE_AFS_ROW = 0x212EE0
SE_AFS_ENTRIES = 174

SE_CHANNEL_STRUCT = 'gp-0x6D44 起 + 0x3F480 + 通道号*12'
SE_CHANNEL_FIELDS = {'code': 0x0, 'vol': 0x2, 'prev_vol': 0x3, 'state': 0x5, 'counter': 0x6, 'speed': 0x8}
SE_HANDLERS = {0x3A: 0x11D080, 0x3C: 0x11D138, 0x3D: 0x11CC18, 0x3E: 0x11D188, 0x3F: 0x11D1E0}
SE_NOTES = ('se_speed/se_vol/se_set/se_req/se_wait 已定位到通道结构，但 se_set 只有在运行时'
            '“样本已就绪”字节为 2 时才启动播放，se_wait 又要等播放结束；两者都依赖 se.afs 样本表，'
            '索引到条目的对应尚未证实，所以这里不实现、也不猜音频文件。')


def _code(raw):
    return raw[2] | (raw[3] << 8)


def parse_file_read(raw):
    """解析 `file_read` 的已核实形态；其它一律拒绝。"""
    if len(raw) != 4:
        raise UnsupportedCommand(f'file_read 长度应为 4，实际 {len(raw)}')
    style = raw[1]
    code = _code(raw)
    if style != SUPPORTED_STYLE:
        raise UnsupportedCommand(f'未核实的 file_read style={style:#04x}')
    if code >> 8 != SUPPORTED_PREFIX:
        raise UnsupportedCommand(f'未核实的 file_read code={code:#06x}（只证实高字节 0x50）')
    return {'style': style, 'code': f'0x{code:04X}', 'group': code >> 12, 'index': code & 0xFFF,
            'staged': {'flag': f'0x{STAGED_FLAG:X}', 'style': f'0x{STAGED_STYLE:X}',
                       'code': f'0x{STAGED_CODE:X}'},
            'effect': '只把 (style, code) 写进 staging 槽位；组 5 没有描述表，不拼文件名、不发起读取',
            'webgal': {'mapped': False,
                       'reason': '该指令不产生可见/可听输出，只是为后续 se_* 声明资源编号；'
                                 '编号到 se.afs 条目的对应尚未证实'}}


def parse_file_wait(raw):
    """解析 `file_wait`；参数不含被读取的内容，只表示等待 staging 槽位。"""
    if len(raw) != 4:
        raise UnsupportedCommand(f'file_wait 长度应为 4，实际 {len(raw)}')
    if _code(raw) != 0:
        raise UnsupportedCommand(f'未核实的 file_wait 参数 {_code(raw):#06x}')
    return {'parameter': 0, 'staged': {'flag': f'0x{STAGED_FLAG:X}', 'result': f'0x{STAGED_RESULT:X}'},
            'effect': '轮询 staging 挂起位；未挂起即视为完成，挂起时按 style 取结果并清位',
            'webgal': {'mapped': False, 'reason': '不产生可见/可听输出；原程序的等待在本 build 里对组 5 立即返回'}}
