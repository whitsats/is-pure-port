"""WebGAL's simplified completion for the verified MAC type-1 particle effect."""
from mac_state import UnsupportedCommand

PARTICLE_START = bytes.fromhex('6a00010100004000f6ff000000000c000c000c000600020000000000000000000000000000000000')
PARTICLE_STOP = {bytes.fromhex('6b00fc0000000000'): 0, bytes.fromhex('6b00fc0100000000'): 1}
PARTICLE_POLL = bytes.fromhex('6b00fd0000000000')
PARTICLE_PHASE = 'mac_effect_0_phase'
SCREEN_START = bytes.fromhex('6a000300000008000600060005000800000000000000000000000000000000000000000000000000')
# 后续章节里按原字节登记的另外两类启动：类型 6（MAC_020）与类型 12（MAC_054）。
# 两者的 ip 推进都是 40 字节，结束请求/完成检查沿各自的 0x6B 通道：
# 类型 6 用 6b00fc01 + 6b00fd，类型 12 用 6b02fd。"
EXTRA_STARTS = {
    bytes.fromhex('6a020c00010000000000000006000000000000000000000000000000000000000000000000000000'): 'type_12_p6',
    bytes.fromhex('6a020c002d0000000000000008000000000000000000000000000000000000000000000000000000'): 'type_12_p8',
    bytes.fromhex('6a020c0001000f000f000f000a000000000000000000000000000000000000000000000000000000'): 'type_12_pf',
    bytes.fromhex('6a020c00010000000000000009000000000000000000000000000000000000000000000000000000'): 'type_12_p9',
    bytes.fromhex('6a020c00010000000000000004000000000000000000000000000000000000000000000000000000'): 'type_12_p4',
    bytes.fromhex('6a00060100000f000f000d0010000300080042008c000f001d00e001000000000000000000000000'): 'type_6',
    bytes.fromhex('6a020c00010000000000000008000000000000000000000000000000000000000000000000000000'): 'type_12_p8',
    bytes.fromhex('6a020c0001000000000000000c000000000000000000000000000000000000000000000000000000'): 'type_12_p12',
}
CHANNEL_STOP = {bytes.fromhex('6b00fc'): 'channel_0', bytes.fromhex('6b02fc'): 'channel_2'}
CHANNEL_POLL = {bytes.fromhex('6b00fd'): 'channel_0', bytes.fromhex('6b02fd'): 'channel_2'}


def emit_particle_effect(raw):
    """Retain the request/poll order while mapping PS2 particle effects to WebGAL performs."""
    if raw == PARTICLE_START:
        return ['pixiPerform:rain -next;', f'setVar:{PARTICLE_PHASE}=1 -next;'], 'start_rain'
    if raw in PARTICLE_STOP:
        mode = PARTICLE_STOP[raw]
        return ['pixiInit -next;', f'setVar:{PARTICLE_PHASE}={2 + mode} -next;'], f'stop_mode_{mode}'
    if raw == PARTICLE_POLL:
        return [f'wait:17 -nobreak -when={PARTICLE_PHASE}>=2;',
                f'setVar:{PARTICLE_PHASE}=0 -next;'], 'completion_poll'
    raise UnsupportedCommand(f'未核实的粒子特效指令参数: {raw.hex()}')


def emit_screen_effect(raw):
    """类型 3 用已验证的八帧上限；类型 6/12 按登记的原字节沿同一完成协议。"""
    if raw == PARTICLE_START or raw in PARTICLE_STOP or raw == PARTICLE_POLL:
        return emit_particle_effect(raw)
    if raw == SCREEN_START:
        return ['setAnimation:shake -target=stage -next;', f'setVar:{PARTICLE_PHASE}=1 -next;'], 'start_quake'
    if raw in EXTRA_STARTS:
        tag = EXTRA_STARTS[raw]
        if tag == 'type_6':
            return ['pixiPerform:snow -next;', f'setVar:{PARTICLE_PHASE}=1 -next;'], 'start_snow'
        return [f'setVar:{PARTICLE_PHASE}=1 -next;'], f'start_{tag}'
    if raw[:3] in CHANNEL_STOP:
        mode = raw[3]
        if mode not in (0, 1):
            raise UnsupportedCommand(f'未核实的特效结束模式: {raw.hex()}')
        ch = CHANNEL_STOP[raw[:3]]
        lines = []
        if ch == 'channel_0':
            lines.append('pixiInit -next;')
        lines.append(f'setVar:{PARTICLE_PHASE}={2 + mode} -next;')
        return lines, f'stop_mode_{mode}_{ch}'
    if raw[:3] in CHANNEL_POLL:
        return [f'wait:17 -nobreak -when={PARTICLE_PHASE}>=2;',
                f'setVar:{PARTICLE_PHASE}=0 -next;'], f'completion_poll_{CHANNEL_POLL[raw[:3]]}'
    if raw == PARTICLE_POLL:
        return [f'wait:134 -nobreak -when={PARTICLE_PHASE}>=2;',
                f'setVar:{PARTICLE_PHASE}=0 -next;'], 'completion_poll'
    if raw == bytes.fromhex('6b00fc0000000000'):
        return emit_particle_effect(raw)
    raise UnsupportedCommand(f'未核实的类型 3 特效指令参数: {raw.hex()}')
