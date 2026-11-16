"""`time_wait` 的已核实子集：把原程序的帧计时转成 WebGAL 的 `wait` 命令。

证据来自 `输出-保护边修复/SYSTEM/SLPM_665.70`，现场复核见 `转换器/跳转与等待证据.py`，
产物 `数据/跳转与等待ELF证据.json`，说明见 `验证/等待与跨剧本跳转.md`。

- `time_wait`（`0x0C`，4 字节）处理函数 `0x00119258`：
  `lbu ip[1]` 是模式（`0x001192E0`），`lh ip[2..3]` 经 `0x115730` 读取时长
  （`0x001192B8`/`0x001192C0`），`0x11FD00` 把“当前计时器 + 时长”写入计时对象；
  之后 `0x11FD18` 按模式判断是否完成，`ip += 4`（`0x0011930C`–`0x00119318`）。
- 计时器 `*(gp-0x6DE8)` 在帧循环里加 1（`0x10DF44`–`0x10DF48`，调用点
  `0x1132BC`）。因此 1 个单位按 60 Hz 换算为 1000/60 毫秒。
- 本轮只实现模式 1（`0x730` 使用的模式）：计时到点即完成；模式 0/2/3 的
  输入/跳过语义未核实，遇到即停止。
"""
from mac_state import UnsupportedCommand

TIME_WAIT = 0x0C
FRAME_HZ = 60
WAIT_NOTE = ('time_wait 用 WebGAL 的 wait 命令表达；原程序计时器按帧递增，'
             '这里按 60 Hz 换算为毫秒。原版可能因全局 +0x47C 提前结束，移植版不模拟该提前结束。')


def parse_time_wait(raw, state):
    """解析 4 字节 `time_wait`，返回模式、帧数与 WebGAL 的 wait 毫秒数。"""
    if len(raw) != 4 or raw[0] != TIME_WAIT:
        raise UnsupportedCommand('不是 4 字节 time_wait')
    mode = raw[1]
    if mode != 1:
        raise UnsupportedCommand(f'未核实的 time_wait 模式 {mode}')
    operand = raw[2] | (raw[3] << 8)
    frames = state.read(operand)
    milliseconds = max(0, round(frames * 1000 / FRAME_HZ))
    return {
        'mode': mode,
        'duration_operand': f'0x{operand:04X}',
        'frames': frames,
        'duration_ms': milliseconds,
        'frame_hz': FRAME_HZ,
        'command': f'wait:{milliseconds};',
        'effect': f'等待 {frames} 个计时单位（按 {FRAME_HZ} Hz 约 {milliseconds} 毫秒）',
        'webgal': {'mapped': True, 'command': f'wait:{milliseconds};', 'reason': WAIT_NOTE},
    }
