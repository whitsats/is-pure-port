"""严格转换连续的已核对 msg_disp2；遇到其他指令立即停止。"""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import shutil

from mac_display import (GRAPH_POS, GRAPH_PRIO, apply_graph_prio, parse_graph_disp, parse_graph_pos,
                         parse_msg_mode, resolve_graph_records)
from mac_fade import (FADE_MAPPING_NOTE, FADE_START, FADE_WAIT, parse_fade_start,
                      parse_fade_wait)
from mac_file_read import FILE_READ, FILE_WAIT, SE_NOTES, parse_file_read, parse_file_wait
from mac_jump import (EXT_GOTO, INT_CALL, INT_GOTO, INT_GOTO_NOTE, INT_RETURN, JUMP_NOTE,
                      parse_ext_goto, parse_int_call, parse_int_goto, parse_int_return)
from mac_se import (MAPPING_NOTE as SE_MAPPING_NOTE, PARSERS as SE_PARSERS, SE_DEL, SE_REQ,
                    SE_SET, SE_SPEED, SE_VOL, SE_WAIT, parse_se_set)
from mac_title_table import (DEFAULT_TITLE_MANIFEST, load_title_manifest, resolve_title_disp)
from mac_new_game import NewGameRuntime
from mac_release import DISC_DIALOGUE
from mac_wait import TIME_WAIT, WAIT_NOTE, parse_time_wait
from mac_state import State, UnsupportedCommand, apply_reg_calc, evaluate_if
from mac_webgal_state import emit_word_write

BASE = Path(__file__).resolve().parents[1]
ROOT = BASE.parent
IR = BASE / '数据/入口片段.json'
CHECKS = DISC_DIALOGUE


TRANSLATION_SOURCE = 'v7.4 原始工程（剧本+指令偏移对应）'
TRANSLATION_NOTE = ('选译只取 v7.4 原始工程中与剧本、指令偏移对应的最终译文；'
                    '三版表的逐字节对盘结果仅作为独立证据保留，不参与选译。')


def normalize_mapping_row(row):
    row = dict(row)
    if 'v7.4中文' in row:
        row['中文（原对照表）'] = row['v7.4中文']
        if row['匹配状态'] == '工程与地址匹配':
            row['匹配状态'] = '唯一匹配'
            row['译文来源'] = TRANSLATION_SOURCE
    elif 'v7.4工程文本对盘' in row:
        # 对盘状态只记录事实，供独立核查；选译按地址对应的 v7.4 文本。
        row['对盘状态'] = '；'.join(
            f'{name}={row.get(column, "")}' for name, column in
            (('v7.4工程', 'v7.4工程文本对盘'), ('汇总', '汇总文本对盘'), ('v7', 'v7工程文本对盘')))
        text = row.get('v7.4工程中文', '')
        if text:
            row['中文（原对照表）'] = text
            row['匹配状态'] = '唯一匹配'
            row['译文来源'] = TRANSLATION_SOURCE
        else:
            row['中文（原对照表）'] = ''
            row['匹配状态'] = '没有 v7.4 地址对应译文'
            row['译文来源'] = ''
    return row


PACING = {0x12: ('msg_view', '等待消息窗状态；不新增文本、不读按键'),
          0x1A: ('msg_wait', '等待文字显示完成；不新增文本'),
          0x1B: ('msg_clear', '重置消息窗记录；不新增文本')}
VIEW_PARAM = '03'


def convert_message_window_run(commands, rows, start, verified_voices=None):
    """跨过已核实的消息窗节拍命令，逐条输出台词。

    msg_disp2 自带一次按键推进（原程序在窗口状态 5 分支读取手柄 0x2000 位），
    因此每条台词对应 WebGAL 的一次 say；msg_view / msg_wait / msg_clear 只做
    窗口内部节拍，不新增文本也不读取按键，转换时记入报告但不生成语句。
    没有前置台词、或 msg_view 参数不是已观察到的 3 时会停止。
    """
    verified_voices = verified_voices or {}
    index = next((i for i, c in enumerate(commands) if c['offset'] == start), None)
    if index is None:
        raise ValueError('开始偏移不在入口片段中')
    output, sources, pacing = [], [], []
    has_text = False
    for command in commands[index:]:
        if command['opcode'] == 0x60:
            row = rows.get(command['offset'])
            if not row or row['匹配状态'] != '唯一匹配' or not row['中文（原对照表）']:
                return output, sources, pacing, {'offset': command['offset'], 'name': command['name'],
                                                 'reason': '中文未唯一匹配或缺失'}
            text = row['中文（原对照表）']
            if any(c in text for c in ';:|\\\r\n'):
                return output, sources, pacing, {'offset': command['offset'], 'name': command['name'],
                                                 'reason': '文本含尚未处理的特殊字符'}
            voice = int(row['语音号'])
            if voice != -1 and voice not in verified_voices:
                return output, sources, pacing, {'offset': command['offset'], 'name': command['name'],
                                                 'reason': '自动语音映射尚未验证'}
            output.append(text + (f' -{verified_voices[voice]}' if voice != -1 else '') + ';')
            sources.append({'offset': command['offset'], 'line': int(row['行号']), 'voice': voice})
            has_text = True
            continue
        if command['opcode'] in PACING:
            if command['opcode'] == 0x12 and command['raw_hex'][2:4] != VIEW_PARAM:
                return output, sources, pacing, {'offset': command['offset'], 'name': command['name'],
                                                 'reason': '未核实的 msg_view 参数'}
            name, effect = PACING[command['opcode']]
            pacing.append({'offset': command['offset'], 'name': name, 'raw_hex': command['raw_hex'],
                           'effect': effect, 'emitted': False, 'text_since_clear': has_text})
            if command['opcode'] == 0x1B:
                has_text = False
            continue
        return output, sources, pacing, {'offset': command['offset'], 'name': command['name'],
                                         'reason': '未转换的指令'}
    return output, sources, pacing, {'offset': None, 'name': None, 'reason': '到达已解析范围末尾'}


STATE_EVIDENCE = '数据/状态字ELF证据.json'
DISPLAY_EVIDENCE = '数据/画面指令ELF证据.json'
DISPLAY_MAPPING_NOTE = ('msg_mode 与 graph_disp 已按 ELF 证据解释，但 WebGAL 侧没有逐条改消息窗几何或显示资源的能力，'
                        '所以它们只写进 displays，不生成语句；这不是静默丢弃。')
INITIAL_STATE_NOTE = ('初值按原程序 memset 证据取 0：*(gp-0x6D44) 起 0x0D38680 字节在 VM 初始化时清零')
READ_EVIDENCE = '数据/文件读取ELF证据.json'
SE_EVIDENCE = '数据/SE段ELF证据.json'
FADE_EVIDENCE = '数据/淡入淡出ELF证据.json'
JUMP_EVIDENCE = '数据/跳转与等待ELF证据.json'
TITLE_EVIDENCE = '数据/章节标题静态表.json'
SE_BLOCK = (SE_SET, SE_DEL, SE_REQ, SE_WAIT, SE_SPEED, SE_VOL)
READ_MAPPING_NOTE = ('file_read/file_wait 只把 (style, code) 写进 staging 槽位并轮询；组 5 没有描述表，'
                     '原程序在这条路径上不拼文件名也不发起读取（0x12D810 → 0x12D8B8 → 0x12D970），'
                     '因此换算后不生成语句，只写进 file_reads。' + SE_NOTES)


def convert_program(commands, rows, start, verified_voices=None, state=None, max_steps=2000, data=None,
                    emit_waits=False, emit_state_bytes=False, prototype_save=False, prototype_title=False,
                    titles=None, runtime=None, stop_after=None, diagnostic_effects=False,
                    webgal_words=()):
    """带状态与条件的最小解释执行，返回
    (台词, 来源, 节拍, 判定, 写入, 画面记录, 跳转记录, 停止, 读取记录, SE 记录, 淡入淡出记录, 等待记录)。

    只执行已核实的子集：msg_disp2、msg_view(参数 3)、msg_wait、msg_clear、if(参数 0，比较码 0～5)、
    reg_calc(运算 0/1/2)、msg_mode(模式 5/6)、graph_disp、file_read/file_wait(style 0、code 0x50xx)、
    SE 段、fade_start/fade_wait、time_wait(模式 1)、title_disp(有静态 57 条标题表时)。
    其余一律停止并记录原字节，不静默跳过。
    msg_mode、graph_disp、file_read、SE、fade 都不生成语句；time_wait 生成 WebGAL 的 wait 命令。
    （见 验证/状态与条件.md、验证/文件读取与SE阻塞.md、验证/SE段解码.md、
    验证/淡入淡出与se_del.md、验证/等待与跨剧本跳转.md）。
    """
    verified_voices = verified_voices or {}
    if runtime is not None:
        if state is not None and state is not runtime.state:
            raise ValueError('runtime 与 state 必须指向同一个状态对象')
        state = runtime.state
    state = state if state is not None else State()
    index_by_offset = {command['offset']: i for i, command in enumerate(commands)}
    if start not in index_by_offset:
        raise ValueError('开始偏移不在入口片段中')
    position = index_by_offset[start]
    output, sources, pacing, decisions, writes, displays, gotos, reads, sounds, fades, waits = \
        [], [], [], [], [], [], [], [], [], [], []
    staged = {'code': None}
    fade_color = None
    visited, call_stack, has_text, steps = {}, [], False, 0
    last_command = None

    def state_signature():
        # 合法的计数循环（例如 MAC_001 0x21D0 到 0x230C）会多次到达同一偏移；
        # 只有“同一偏移 + 完全相同的状态”才视为无法推进的环。
        return tuple(sorted(state.memory_bytes.items()))

    def stop(command, reason):
        return output, sources, pacing, decisions, writes, displays, gotos, {
            'offset': command['offset'] if command else None,
            'name': command['name'] if command else None,
            'raw_hex': command['raw_hex'] if command else None, 'reason': reason}, reads, sounds, fades, waits

    while True:
        if stop_after is not None and last_command is not None and last_command['offset'] == stop_after:
            return stop(last_command, f'已到达样片目标 0x{stop_after:X}（含该条指令）')
        if position >= len(commands):
            return stop(None, '到达已解析范围末尾')
        steps += 1
        if steps > max_steps:
            return stop(commands[position], f'超过 {max_steps} 步上限')
        command = commands[position]
        last_command = command
        visit_key = (command['offset'], tuple(call_stack))
        signature = state_signature()
        if visit_key in visited and visited[visit_key] == signature:
            return stop(command, '会重复到达同一偏移，可能成环')
        visited[visit_key] = signature

        if command['opcode'] == 0x60:
            row = rows.get(command['offset'])
            if not row or row['匹配状态'] != '唯一匹配' or not row['中文（原对照表）']:
                return stop(command, '中文未唯一匹配或缺失')
            text = row['中文（原对照表）']
            if any(c in text for c in ';:|\\\r\n'):
                return stop(command, '文本含尚未处理的特殊字符')
            voice = int(row['语音号'])
            if voice != -1 and voice not in verified_voices:
                return stop(command, '自动语音映射尚未验证')
            output.append(text + (f' -{verified_voices[voice]}' if voice != -1 else '') + ';')
            sources.append({'offset': command['offset'], 'line': int(row['行号']), 'voice': voice})
            has_text = True
            position += 1
            continue

        if command['opcode'] in PACING:
            if command['opcode'] == 0x12 and command['raw_hex'][2:4] != VIEW_PARAM:
                return stop(command, '未核实的 msg_view 参数')
            name, effect = PACING[command['opcode']]
            pacing.append({'offset': command['offset'], 'name': name, 'raw_hex': command['raw_hex'],
                           'effect': effect, 'emitted': False, 'text_since_clear': has_text})
            if command['opcode'] == 0x1B:
                has_text = False
            position += 1
            continue

        if command['opcode'] == 0x02:
            try:
                result, target, detail = evaluate_if(bytes.fromhex(command['raw_hex']), state)
            except UnsupportedCommand as error:
                return stop(command, f'条件无法求值: {error}')
            decision = {'offset': command['offset'], 'raw_hex': command['raw_hex'], **detail}
            decisions.append(decision)
            if result:
                if target not in index_by_offset:
                    return stop(command, f'跳转目标 0x{target:X} 不是已解析的命令边界')
                position = index_by_offset[target]
            else:
                position += 1
            continue

        if command['opcode'] == INT_GOTO:
            try:
                target = parse_int_goto(bytes.fromhex(command['raw_hex']))
            except UnsupportedCommand as error:
                return stop(command, f'int_goto 无法解析: {error}')
            if target not in index_by_offset:
                return stop(command, f'int_goto 目标 0x{target:X} 不是已解析的命令边界')
            gotos.append({'offset': command['offset'], 'name': 'int_goto',
                          'raw_hex': command['raw_hex'], 'target': target,
                          'target_hex': f'0x{target:06X}', 'effect': f'ip = 0x{target:06X}',
                          'webgal': {'mapped': True, 'reason': INT_GOTO_NOTE}})
            position = index_by_offset[target]
            continue

        if command['opcode'] == INT_CALL:
            try:
                target = parse_int_call(bytes.fromhex(command['raw_hex']))
                saved_resource = state.read_context_u32(0x52E0)
            except UnsupportedCommand as error:
                return stop(command, f'int_call 无法解析: {error}')
            return_offset = command['offset'] + 8
            if target not in index_by_offset or return_offset not in index_by_offset:
                return stop(command, 'int_call 的目标或返回地址不是已解析的命令边界')
            if len(call_stack) >= 64:
                return stop(command, '调用深度超过转换器安全上限 64')
            call_stack.append((return_offset, saved_resource))
            gotos.append({'offset': command['offset'], 'name': 'int_call', 'target': target,
                          'return_offset': return_offset, 'saved_resource': saved_resource,
                          'depth': len(call_stack), 'raw_hex': command['raw_hex']})
            position = index_by_offset[target]
            continue

        if command['opcode'] == INT_RETURN:
            try:
                parse_int_return(bytes.fromhex(command['raw_hex']))
            except UnsupportedCommand as error:
                return stop(command, f'int_return 无法解析: {error}')
            if not call_stack:
                return stop(command, 'int_return 没有对应的调用栈')
            target, saved_resource = call_stack[-1]
            if target not in index_by_offset:
                return stop(command, 'int_return 的返回地址不是已解析的命令边界')
            try:
                state.write_context_u32(0x52E0, saved_resource)
            except UnsupportedCommand as error:
                return stop(command, f'int_return 无法恢复状态: {error}')
            call_stack.pop()
            gotos.append({'offset': command['offset'], 'name': 'int_return', 'target': target,
                          'restored_resource': saved_resource, 'depth': len(call_stack),
                          'raw_hex': command['raw_hex']})
            position = index_by_offset[target]
            continue

        if command['opcode'] == 0x09:
            if runtime is not None and command['raw_hex'].startswith('0917'):
                try:
                    entry = runtime.apply_reg17(bytes.fromhex(command['raw_hex']))
                except UnsupportedCommand as error:
                    return stop(command, f'新游戏 0x17 无法执行: {error}')
                writes.append({'offset': command['offset'], 'raw_hex': command['raw_hex'], **entry})
                position += 1
                continue
            if emit_state_bytes and command['raw_hex'].startswith('0917'):
                return stop(command, '试验性状态字节输出尚不支持 reg_calc 0x17 的全局表')
            try:
                raw = bytes.fromhex(command['raw_hex'])
                runtime_lines = emit_word_write(raw, webgal_words, f'{command["offset"]:x}_{steps}') if webgal_words else []
                entry = apply_reg_calc(raw, state)
            except UnsupportedCommand as error:
                return stop(command, f'状态计算无法执行: {error}')
            writes.append({'offset': command['offset'], 'raw_hex': command['raw_hex'], **entry})
            output.extend(runtime_lines)
            if emit_state_bytes:
                dest = entry['dest']
                offset = dest['offset']
                for byte_offset in range(offset, offset + (2 if dest['kind'] == 'word' else 1)):
                    value = state.read_context_u32(byte_offset) & 0xFF
                    output.append(f'setVar:mac_b_{byte_offset:05x}={value};')
            position += 1
            continue

        if command['opcode'] == 0x5A and runtime is not None:
            try:
                entry = runtime.apply_quick_save(bytes.fromhex(command['raw_hex']))
            except UnsupportedCommand as error:
                return stop(command, f'新游戏 quick_save 无法执行: {error}')
            writes.append({'offset': command['offset'], 'raw_hex': command['raw_hex'], **entry})
            position += 1
            continue

        if command['opcode'] == 0x5A and prototype_save:
            if command['raw_hex'] != '5a020000':
                return stop(command, '简化存档模式尚未核查此 quick_save 参数')
            writes.append({'offset': command['offset'], 'raw_hex': command['raw_hex'],
                           'operation': 'prototype_save_omitted',
                           'note': '省略原存档与进度复制，依靠 WebGAL 自带存读档；'
                                   '原版全局进度及后续条件是否一致尚未验证。'})
            output.append('__commment:简化模式使用WebGAL自带存档，原进度复制暂未实现;')
            position += 1
            continue

        if command['opcode'] == 0x50:
            if prototype_title:
                if command['raw_hex'] != '50000000':
                    return stop(command, '简化标题模式尚未核查此 title_disp 参数')
                displays.append({'offset': command['offset'], 'name': 'title_disp',
                                 'raw_hex': command['raw_hex'],
                                 'webgal': {'mapped': False,
                                            'reason': '显式简化标题模式省略章节标题演出；原附带状态副作用尚待核验'}})
                output.append('__commment:简化模式暂省略章节标题演出;')
                position += 1
                continue
            if titles is None:
                return stop(command, 'title_disp 需要静态章节标题表；当前未加载 数据/章节标题静态表.json')
            try:
                detail = resolve_title_disp(bytes.fromhex(command['raw_hex']), state, titles)
            except UnsupportedCommand as error:
                return stop(command, f'title_disp 无法解释: {error}')
            displays.append({'offset': command['offset'], 'name': 'title_disp',
                             'raw_hex': command['raw_hex'], **detail})
            output.append(detail['command'])
            position += 1
            continue

        if command['opcode'] == 0x57:
            if runtime is None:
                return stop(command, 'vib_set 需要新游戏运行时状态；当前未加载')
            try:
                detail = runtime.apply_vib_set(bytes.fromhex(command['raw_hex']))
            except UnsupportedCommand as error:
                return stop(command, f'vib_set 无法执行: {error}')
            displays.append({'offset': command['offset'], 'name': 'vib_set',
                             'raw_hex': command['raw_hex'], **detail})
            position += 1
            continue

        if command['opcode'] == 0x6A and diagnostic_effects:
            # 仅用于检查此处之后的下一个阻塞；原函数有状态写入，不能当成等价运行。
            if command['raw_hex'] != '6a00010100004000f6ff000000000c000c000c000600020000000000000000000000000000000000':
                return stop(command, '诊断模式只允许已识别的 MAC_004 effect_start 参数')
            displays.append({'offset': command['offset'], 'name': 'diagnostic_effect_start_omitted',
                             'raw_hex': command['raw_hex'],
                             'reason': '仅诊断后续阻塞；原特效及其状态副作用未执行，路径不可作为等价或发布结果。'})
            position += 1
            continue

        if command['opcode'] == GRAPH_PRIO:
            try:
                detail = apply_graph_prio(bytes.fromhex(command['raw_hex']), state)
            except UnsupportedCommand as error:
                return stop(command, f'graph_prio 无法解释: {error}')
            displays.append({'offset': command['offset'], 'name': 'graph_prio',
                             'raw_hex': command['raw_hex'], **detail})
            position += 1
            continue

        if command['opcode'] == GRAPH_POS:
            try:
                detail = parse_graph_pos(bytes.fromhex(command['raw_hex']), state)
            except UnsupportedCommand as error:
                return stop(command, f'graph_pos 无法解释: {error}')
            displays.append({'offset': command['offset'], 'name': 'graph_pos',
                             'raw_hex': command['raw_hex'], **detail})
            position += 1
            continue

        if command['opcode'] == 0x13:
            try:
                detail = parse_msg_mode(bytes.fromhex(command['raw_hex']))
            except UnsupportedCommand as error:
                return stop(command, f'消息窗模式无法解释: {error}')
            displays.append({'offset': command['offset'], 'name': 'msg_mode',
                             'raw_hex': command['raw_hex'], **detail,
                             'webgal': {'mapped': False, 'reason': 'WebGAL 没有逐条修改消息窗几何的能力；'
                                                              '该模式不改显隐，只改窗口位置与宽度'}})
            position += 1
            continue

        if command['opcode'] == 0x33:
            try:
                detail = parse_graph_disp(bytes.fromhex(command['raw_hex']))
                records = resolve_graph_records(data, detail['blob_offset'], detail['count'])
            except UnsupportedCommand as error:
                return stop(command, f'画面指令无法解释: {error}')
            displays.append({'offset': command['offset'], 'name': 'graph_disp',
                             'raw_hex': command['raw_hex'], **detail, 'records': records,
                             'webgal': {'mapped': False, 'reason': '显示资源属于尚未开始的画面/立绘层；'
                                                                  '此处只记录资源与记录偏移'}})
            position += 1
            continue

        if command['opcode'] in (FILE_READ, FILE_WAIT):
            parser = parse_file_read if command['opcode'] == FILE_READ else parse_file_wait
            try:
                detail = parser(bytes.fromhex(command['raw_hex']))
            except UnsupportedCommand as error:
                return stop(command, f'文件读取指令无法解释: {error}')
            reads.append({'offset': command['offset'], 'name': command['name'],
                          'raw_hex': command['raw_hex'], **detail})
            if command['opcode'] == FILE_READ:
                staged['code'] = int(detail['code'], 16)
            position += 1
            continue

        if command['opcode'] == TIME_WAIT:
            try:
                detail = parse_time_wait(bytes.fromhex(command['raw_hex']), state)
            except UnsupportedCommand as error:
                return stop(command, f'time_wait 无法解释: {error}')
            waits.append({'offset': command['offset'], 'name': command['name'],
                          'raw_hex': command['raw_hex'], **detail})
            if emit_waits:
                output.append(detail['command'])
            position += 1
            continue

        if command['opcode'] == EXT_GOTO:
            if call_stack:
                return stop(command, '调用栈未清空时的跨剧本跳转尚未核实')
            return stop(command, '跨剧本跳转（需 --follow-goto 继续）')

        if command['opcode'] in (FADE_START, FADE_WAIT):
            try:
                if command['opcode'] == FADE_START:
                    detail = parse_fade_start(bytes.fromhex(command['raw_hex']), state, fade_color)
                    fade_color = int(detail['color'], 16)
                else:
                    detail = parse_fade_wait(bytes.fromhex(command['raw_hex']))
            except UnsupportedCommand as error:
                return stop(command, f'淡入淡出指令无法解释: {error}')
            fades.append({'offset': command['offset'], 'name': command['name'],
                          'raw_hex': command['raw_hex'], **detail})
            position += 1
            continue

        if command['opcode'] in SE_BLOCK:
            try:
                if command['opcode'] == SE_SET:
                    detail = parse_se_set(bytes.fromhex(command['raw_hex']), staged['code'])
                else:
                    detail = SE_PARSERS[command['opcode']](bytes.fromhex(command['raw_hex']))
            except UnsupportedCommand as error:
                return stop(command, f'SE 指令无法解释: {error}')
            sounds.append({'offset': command['offset'], 'name': command['name'],
                           'raw_hex': command['raw_hex'], **detail})
            position += 1
            continue

        return stop(command, '未转换的指令')


def convert_chain(scripts_by_file, rows_by_script, start_script, start_offset,
                  verified_voices, data_loader, scripts_dir, max_gotos=4, initial_state=None,
                  prototype_save=False, prototype_title=False, titles=None,
                  runtime=None, stop_after=None, max_steps=2000, diagnostic_effects=False,
                  webgal_words=()):
    """从 start_script 开始解释；遇到 ext_goto 时记录事件并跟进目标剧本入口。

    目标由 `mac_jump.parse_ext_goto` 按资源号与目标文件头核实；任何一段遇到未实现
    指令就停在原处。返回聚合后的各记录、分段与跳转表，不生成伪造的 jump 命令。
    """
    if runtime is not None:
        if initial_state is not None and initial_state is not runtime.state:
            raise ValueError('runtime 与 initial_state 必须指向同一个状态对象')
        state = runtime.state
    else:
        state = initial_state if initial_state is not None else State()
    names = ('lines', 'sources', 'pacing', 'decisions', 'writes', 'displays', 'gotos',
             'reads', 'sounds', 'fades', 'waits')
    combined = {name: [] for name in names}
    segments, jumps, scene_sequences = [], [], []
    script_name, offset = start_script, start_offset
    visited = {(start_script, start_offset)}
    stop = None
    while True:
        script = scripts_by_file.get(script_name)
        if script is None:
            raise ValueError(f'剧本未包含在入口片段中: {script_name}')
        if offset not in {command['offset'] for command in script['commands']}:
            stop = {'offset': offset, 'name': 'ext_goto_target',
                    'raw_hex': jumps[-1]['raw_hex'] if jumps else None,
                    'reason': f'目标 {script_name}+0x{offset:X} 不是已解析的命令边界',
                    'script': script_name}
            segments.append({'script': script_name, 'start': offset, 'stop': dict(stop),
                             'lines': 0, 'dialogues': 0, 'waits': 0, 'int_gotos': 0})
            scene_sequences.append({'script': script_name, 'start': offset,
                                    'stop': dict(stop), 'lines': []})
            break
        lines, sources, pacing, decisions, writes, displays, gotos, stop, reads, sounds, fades, waits = \
            convert_program(script['commands'], rows_by_script.get(script_name, {}), offset,
                            verified_voices, state=state, data=data_loader(script_name),
                            emit_waits=True, prototype_save=prototype_save, prototype_title=prototype_title,
                            titles=titles, runtime=runtime, stop_after=stop_after, max_steps=max_steps,
                            diagnostic_effects=diagnostic_effects, webgal_words=webgal_words)
        items_by_name = dict(zip(names, (lines, sources, pacing, decisions, writes, displays,
                                         gotos, reads, sounds, fades, waits)))
        for name, items in items_by_name.items():
            for item in items:
                if isinstance(item, dict):
                    item['script'] = script_name
            combined[name].extend(items)
        stop = dict(stop)
        stop['script'] = script_name
        segments.append({'script': script_name, 'start': offset, 'stop': dict(stop),
                         'lines': len(lines), 'dialogues': len(sources), 'waits': len(waits),
                         'int_gotos': len(gotos)})
        scene_sequences.append({'script': script_name, 'start': offset,
                                'stop': dict(stop), 'lines': list(lines)})
        if stop['name'] != 'ext_goto' or len(jumps) >= max_gotos:
            break
        try:
            detail = parse_ext_goto(bytes.fromhex(stop['raw_hex']), scripts_dir)
        except UnsupportedCommand as error:
            stop['reason'] = f'{stop["reason"]}；目标解析失败: {error}'
            break
        jumps.append({'script': script_name, 'offset': stop['offset'],
                      'raw_hex': stop['raw_hex'], **detail})
        target_key = (detail['target_script'], detail['target_entry'])
        if target_key in visited:
            stop['reason'] = f'{stop["reason"]}；检测到循环跳转 {target_key}'
            break
        visited.add(target_key)
        script_name, offset = target_key
    return {**combined, 'stop': stop, 'segments': segments, 'jumps': jumps,
            'scene_sequences': scene_sequences}


def scene_file_name(sequence):
    """给分段生成稳定、可在 WebGAL 场景目录中使用的文件名。"""
    return f"{Path(sequence['script']).stem.lower()}_0x{sequence['start']:06x}.txt"


def change_scene_command(scene_name):
    # webgal-parser 的 contentParser 会对 changeScene 调用 assetSetter 并加场景目录。
    return f'changeScene:{scene_name};'


def write_scene_chain(sequences, scene_dir, prefix=''):
    """把分段写成独立 WebGAL 场景，并在 ext_goto 段末接 changeScene。

    目标剧本即使没有可生成的台词/等待，也会生成场景文件；此时只写一条
    `__commment`，注明原程序执行到的停止点，不伪造剧情命令。
    """
    scene_dir = Path(scene_dir)
    scene_dir.mkdir(parents=True, exist_ok=True)
    names = [prefix + scene_file_name(sequence) for sequence in sequences]
    written = []
    for index, sequence in enumerate(sequences):
        lines = list(sequence['lines'])
        if (index + 1 < len(sequences) and sequence['stop'].get('name') == 'ext_goto'
                and sequences[index + 1]['stop'].get('name') != 'ext_goto_target'):
            lines.append(change_scene_command(names[index + 1]))
        if not lines:
            stop = sequence['stop']
            lines.append(f"__commment:{sequence['script']} 0x{sequence['start']:06X} "
                         f"执行到 0x{stop['offset']:06X} 的 {stop['name']} 后显式停止;")
        path = scene_dir / names[index]
        if path.exists():
            raise FileExistsError(path)
        path.write_text('\n'.join(lines) + '\n', encoding='utf-8', newline='\n')
        written.append({'script': sequence['script'], 'start': sequence['start'],
                        'scene': names[index], 'lines': len(lines),
                        'stop': dict(sequence['stop'])})
    return written


def convert_run(commands, rows, start, verified_voices=None):
    verified_voices = verified_voices or {}
    index = next((i for i, c in enumerate(commands) if c['offset'] == start), None)
    if index is None:
        raise ValueError('开始偏移不在入口片段中')
    output, sources = [], []
    for command in commands[index:]:
        if command['opcode'] != 0x60:
            return output, sources, {'offset': command['offset'], 'name': command['name'], 'reason': '未转换的指令'}
        row = rows.get(command['offset'])
        if not row or row['匹配状态'] != '唯一匹配' or not row['中文（原对照表）']:
            return output, sources, {'offset': command['offset'], 'name': command['name'], 'reason': '中文未唯一匹配或缺失'}
        text = row['中文（原对照表）']
        if any(c in text for c in ';:|\\\r\n'):
            return output, sources, {'offset': command['offset'], 'name': command['name'], 'reason': '文本含尚未处理的特殊字符'}
        voice = int(row['语音号'])
        if voice != -1 and voice not in verified_voices:
            return output, sources, {'offset': command['offset'], 'name': command['name'], 'reason': '自动语音映射尚未验证'}
        output.append(text + (f' -{verified_voices[voice]}' if voice != -1 else '') + ';')
        sources.append({'offset': command['offset'], 'line': int(row['行号']), 'voice': voice})
    return output, sources, {'offset': None, 'name': None, 'reason': '到达已解析范围末尾'}


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--script')
    p.add_argument('--offset', type=lambda x: int(x, 0))
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--mapping', type=Path, default=CHECKS,
                   help='可使用原汇总核查表或 v7.4 原始工程地址核查表')
    p.add_argument('--voice-manifest', type=Path, action='append',
                   help='可重复指定；多个校验清单会合并')
    p.add_argument('--voice-dir', type=Path)
    p.add_argument('--message-window', action='store_true',
                   help='跨过已核实的 msg_view/msg_wait/msg_clear 节拍命令；不加时保持只转换连续 msg_disp2')
    p.add_argument('--program', action='store_true',
                   help='带状态与条件的最小解释执行（额外支持 if 与 reg_calc 的已核实子集）')
    p.add_argument('--state-snapshot', type=Path,
                   help='实验：使用指定 PCSX2 即时存档的 EE 内存副本，不表示从该场景自然抵达起点')
    p.add_argument('--entry-prefix', action='store_true',
                   help='研究：仅当入口前区域完整解析且以 int_return 结束时纳入调用目标')
    p.add_argument('--prototype-save', action='store_true',
                   help='试验：用 WebGAL 自带存档替代已遇到的 quick_save，忽略原进度复制')
    p.add_argument('--prototype-title', action='store_true',
                   help='试验：暂省略章节标题演出及其尚未核实的状态副作用')
    p.add_argument('--title-table', type=Path,
                   help='静态章节标题清单；默认读取 数据/章节标题静态表.json')
    p.add_argument('--allow-empty', action='store_true',
                   help='允许只产生停止报告而无台词；用于诊断，不代表可玩场景')
    p.add_argument('--follow-goto', action='store_true',
                   help='遇到 ext_goto 时记录跳转并跟进目标剧本入口（默认停在 ext_goto）')
    p.add_argument('--new-game', action='store_true',
                   help='使用零初值新游戏运行时；默认从 MAC_000.bin:0x0C 开始，'
                        '执行真实的 0x17/标题/对白路径（需要 --program --follow-goto）')
    p.add_argument('--stop-after-offset', type=lambda x: int(x, 0),
                   help='执行到该偏移（含）后停止；用于生成到指定对白为止的可复核样片')
    p.add_argument('--max-goto', type=int, default=4,
                   help='最多跟进多少次 ext_goto（默认 4）')
    p.add_argument('--max-steps', type=int, default=2000,
                   help='每段剧本最多执行的指令数（默认 2000；仍保留状态判环）')
    p.add_argument('--scene-dir', type=Path,
                   help='与 --program --follow-goto 一起使用：把每段写成独立 WebGAL 场景，'
                        '并在 ext_goto 段末生成 changeScene')
    p.add_argument('--scene-prefix', default='',
                   help='场景文件名的前缀（可选）')
    args = p.parse_args()
    if args.max_steps < 1:
        raise ValueError('--max-steps 必须大于 0')
    if args.new_game:
        if not args.program or not args.follow_goto:
            raise ValueError('--new-game 必须与 --program --follow-goto 一起使用')
        if args.state_snapshot:
            raise ValueError('--new-game 不能与 --state-snapshot 同时使用')
        if args.prototype_title:
            raise ValueError('--new-game 不能与 --prototype-title 同时使用')
        if args.script is None:
            args.script = 'MAC_000.bin'
        if args.offset is None:
            args.offset = 0x0C
    elif args.script is None or args.offset is None:
        raise ValueError('--script 和 --offset 必须同时指定（或使用 --new-game）')
    if args.stop_after_offset is not None and not args.program:
        raise ValueError('--stop-after-offset 必须与 --program 一起使用')
    if args.program and args.message_window:
        raise ValueError('--program 已包含消息窗节拍，不能与 --message-window 同时使用')
    if args.scene_dir and not (args.program and args.follow_goto):
        raise ValueError('--scene-dir 只能与 --program --follow-goto 同时使用')
    if args.state_snapshot and not args.program:
        raise ValueError('--state-snapshot 必须与 --program 一起使用')
    if (args.entry_prefix or args.prototype_save or args.prototype_title) and not args.program:
        raise ValueError('简化选项和 --entry-prefix 必须与 --program 一起使用')
    if args.title_table and not args.title_table.is_file():
        raise FileNotFoundError(args.title_table)
    report = args.output.with_suffix(args.output.suffix + '.json')
    if args.output.exists() or report.exists():
        raise FileExistsError('输出文件已存在')
    if bool(args.voice_manifest) != bool(args.voice_dir):
        raise ValueError('语音清单与输出目录必须同时指定')
    voices, voice_sources = {}, {}
    for manifest_path in args.voice_manifest or []:
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        for entry in manifest['entries']:
            voice = entry['id']
            if not isinstance(voice, int) or voice < 0 or not entry['source_equal'] or not entry['pcm_equal']:
                raise ValueError('语音清单条目无效')
            source = ROOT / f'输出-保护边修复/VOICE/wav/VOICE_{voice:05}.wav'
            if hashlib.sha256(source.read_bytes()).hexdigest() != entry['wav_sha256']:
                raise ValueError(f'语音文件哈希不符: {voice}')
            filename = f'VOICE_{voice:05}.wav'
            voices[voice], voice_sources[voice] = filename, source
    scripts = json.loads(IR.read_text(encoding='utf-8'))['scripts']
    script = next((s for s in scripts if s['file'] == args.script), None)
    if script is None:
        raise ValueError('剧本未包含在入口片段中')
    if args.entry_prefix:
        from mac_reader import load_table, read_linear_range
        raw_script = (ROOT / '输出-保护边修复/MAC' / args.script).read_bytes()
        if raw_script[:8] != bytes.fromhex('0911006008000000'):
            raise ValueError('剧本头不符合入口格式')
        entry = int.from_bytes(raw_script[8:12], 'little')
        if entry <= 12:
            raise ValueError('没有入口前区域')
        prefix = read_linear_range(raw_script, 12, entry, load_table())
        if not prefix or prefix[-1].opcode != INT_RETURN:
            raise ValueError('入口前区域末尾不是 int_return，拒绝当成子程序')
        extra = [{'offset': c.offset, 'opcode': c.opcode, 'name': c.name, 'raw_hex': c.data.hex()}
                 for c in prefix]
        if {c['offset'] for c in extra} & {c['offset'] for c in script['commands']}:
            raise ValueError('入口前区域与已解析命令重叠')
        script['commands'] = extra + script['commands']
    with args.mapping.open(encoding='utf-8-sig', newline='') as f:
        all_rows = [normalize_mapping_row(row) for row in csv.DictReader(f, delimiter='\t')]
    rows_by_script = {}
    for row in all_rows:
        rows_by_script.setdefault(row['剧本'], {})[int(row['指令偏移'], 16)] = row
    rows = rows_by_script.get(args.script, {})
    pacing, decisions, writes, displays, gotos, reads, sounds, fades, waits = \
        [], [], [], [], [], [], [], [], []
    segments, jumps = [], []
    title_table = None
    title_path = args.title_table or DEFAULT_TITLE_MANIFEST
    if args.program and not args.prototype_title and title_path.is_file():
        title_table = load_title_manifest(title_path)
    if args.program:
        snapshot_state = None
        runtime = None
        if args.state_snapshot:
            from mac_state_snapshot import load_snapshot
            snapshot_state = load_snapshot(args.state_snapshot)
        if args.new_game:
            if title_table is None:
                raise FileNotFoundError('新游戏需要静态章节标题表')
            runtime = NewGameRuntime(title_table['records'])
            snapshot_state = runtime.state
        scripts_by_file = {s['file']: s for s in scripts}
        cache = {}

        def data_loader(name):
            if name not in cache:
                cache[name] = (ROOT / '输出-保护边修复/MAC' / name).read_bytes()
            return cache[name]

        if args.follow_goto:
            chain = convert_chain(scripts_by_file, rows_by_script, args.script, args.offset,
                                  voices, data_loader, ROOT / '输出-保护边修复/MAC', args.max_goto,
                                  initial_state=snapshot_state, prototype_save=args.prototype_save,
                                  prototype_title=args.prototype_title,
                                  titles=title_table['records'] if title_table else None,
                                  runtime=runtime, stop_after=args.stop_after_offset,
                                  max_steps=args.max_steps)
            lines, sources, pacing, decisions, writes, displays, gotos, reads, sounds, fades, waits = \
                (chain[k] for k in ('lines', 'sources', 'pacing', 'decisions', 'writes',
                                    'displays', 'gotos', 'reads', 'sounds', 'fades', 'waits'))
            stop, segments, jumps = chain['stop'], chain['segments'], chain['jumps']
            scene_sequences = chain['scene_sequences']
        else:
            lines, sources, pacing, decisions, writes, displays, gotos, stop, reads, sounds, fades, waits = \
                convert_program(script['commands'], rows, args.offset, voices, state=snapshot_state,
                                data=data_loader(args.script), emit_waits=True,
                                prototype_save=args.prototype_save, prototype_title=args.prototype_title,
                                titles=title_table['records'] if title_table else None,
                                runtime=runtime, stop_after=args.stop_after_offset,
                                max_steps=args.max_steps)
            if stop.get('name') == 'ext_goto':
                try:
                    detail = parse_ext_goto(bytes.fromhex(stop['raw_hex']),
                                            ROOT / '输出-保护边修复/MAC')
                    jumps.append({'script': args.script, 'offset': stop['offset'],
                                  'raw_hex': stop['raw_hex'], **detail})
                    segments.append({'script': args.script, 'start': args.offset,
                                     'stop': dict(stop), 'lines': len(lines),
                                     'dialogues': len(sources), 'waits': len(waits)})
                except UnsupportedCommand as error:
                    stop['reason'] = f'{stop["reason"]}；目标解析失败: {error}'
            scene_sequences = []
    elif args.message_window:
        lines, sources, pacing, stop = convert_message_window_run(
            script['commands'], rows, args.offset, voices)
    else:
        lines, sources, stop = convert_run(script['commands'], rows, args.offset, voices)
        scene_sequences = []
    if not lines and not args.allow_empty:
        raise ValueError(f'没有可转换的台词: {stop}')
    for voice in {item['voice'] for item in sources if item['voice'] != -1}:
        destination = args.voice_dir / voices[voice]
        # 已存在且内容相同的文件不重复拷贝，避免无意义地阻止重生成；不同则报错不覆盖。
        if destination.exists():
            if hashlib.sha256(destination.read_bytes()).hexdigest() != \
                    hashlib.sha256(voice_sources[voice].read_bytes()).hexdigest():
                raise FileExistsError(destination)
    for voice in {item['voice'] for item in sources if item['voice'] != -1}:
        args.voice_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(voice_sources[voice], args.voice_dir / voices[voice])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8', newline='\n') as f:
        f.write('\n'.join(lines) + '\n')
    warning = ('仅已核对的对白，不含前后演出或未实现的控制流。汇总表由模糊对齐生成，v7.4工程文本与最终盘内文本可能有差别；语音时机须复核。')
    if args.message_window or args.program:
        warning += ' 消息窗节拍命令（msg_view/msg_wait/msg_clear）不生成语句，只记录在 pacing 中；原版是否在同一窗口保留之前的行尚未实测。'
    if args.program:
        if args.state_snapshot:
            warning += (' 实验模式使用指定即时存档的内存副本：起始剧本和偏移不一定是快照的实际位置，'
                        '走到的分支只表示该假设状态下的静态结果，不能当作原游戏实际运行轨迹。')
        if args.new_game:
            warning += (' 新游戏模式使用零初值状态和零初值全局位表；'
                        '0x17 的下标/旧位值、title_disp 与 vib_set 均按原指令执行，'
                        '没有使用已有即时存档。')
        warning += ' fade_start/fade_wait 只记录颜色、方向与时长，不生成画面过渡；fade_wait 不等时长，样片节奏会比原版短。'
        if args.entry_prefix:
            warning += ' 入口前区域按完整线性解析和末尾 int_return 纳入；其他可能入口及动态数据仍需核验。'
        if args.prototype_save:
            warning += ' 简化存档模式省略原 quick_save 的存档和进度复制，只依靠 WebGAL 自带存读档；可能影响原版进度和条件。'
        if args.prototype_title:
            warning += ' 显式简化标题模式省略章节标题演出，原指令可能的状态副作用尚未核实。'
        elif title_table is not None and any(item.get('name') == 'title_disp' for item in displays):
            warning += (' title_disp 使用静态 INIT 的 57 条标题表生成 intro；'
                        '原版字号、延迟与 G+0x4B0+6 显示参数未逐项复刻。')
        if args.scene_dir:
            warning += ' time_wait 生成 wait 命令（按 60 Hz 换算）；ext_goto 在父场景末生成 changeScene，目标场景无台词时只写停止注释。'
        else:
            warning += ' time_wait 生成 wait 命令（按 60 Hz 换算）；ext_goto 只记录跳转事件，不生成 jump 命令。'
    payload = {'script': args.script, 'start': args.offset, 'sources': sources, 'pacing': pacing,
               'stop': stop, 'mapping': str(args.mapping), 'warning': warning}
    if args.mapping.resolve() == DISC_DIALOGUE.resolve():
        payload['translation_source'] = 'v7.4 打盘归档（按剧本和指令偏移）'
        payload['translation_note'] = '优先取盘内解码，并逐句标注工程回退。'
    elif any(row.get('译文来源') for row in rows.values()):
        payload['translation_source'] = TRANSLATION_SOURCE
        payload['translation_note'] = TRANSLATION_NOTE
    if args.program:
        if args.state_snapshot:
            payload['state_snapshot'] = {'path': str(args.state_snapshot), 'sha256': snapshot_state.snapshot_sha256,
                                         'scope': '只读内存副本；不写回原存档；游戏运行时状态尚未完整模拟'}
        if runtime is not None:
            payload['new_game_runtime'] = runtime.report()
        payload['conditions'] = decisions
        payload['state_writes'] = writes
        payload['displays'] = displays
        payload['int_gotos'] = gotos
        payload['file_reads'] = reads
        payload['se_events'] = sounds
        payload['fade_events'] = fades
        payload['wait_events'] = waits
        payload['segments'] = segments
        payload['jumps'] = jumps
        payload['jump_evidence'] = JUMP_EVIDENCE
        payload['wait_mapping'] = WAIT_NOTE
        payload['jump_mapping'] = JUMP_NOTE
        payload['int_goto_mapping'] = INT_GOTO_NOTE
        if any(item.get('name') == 'title_disp' for item in displays):
            payload['title_evidence'] = TITLE_EVIDENCE
            payload['title_table'] = {
                'path': str(title_path),
                'v74_source': title_table['v74_source'],
                'v74_sha256': title_table['v74_sha256'],
                'original_source': title_table['original_source'],
                'record_count': title_table['record_count'],
                'count_note': title_table['count_note'],
            }
        if args.scene_dir:
            written = write_scene_chain(scene_sequences, args.scene_dir, args.scene_prefix)
            payload['scene_files'] = written
            for index, jump in enumerate(jumps):
                if (index + 1 < len(written)
                        and written[index]['stop'].get('name') == 'ext_goto'
                        and written[index + 1]['stop'].get('name') != 'ext_goto_target'):
                    jump['webgal'] = {'mapped': True,
                                      'command': change_scene_command(written[index + 1]['scene']),
                                      'reason': 'ext_goto 已写成 WebGAL 场景切换；目标场景在停止点显式注释。'}
        payload['file_read_evidence'] = READ_EVIDENCE
        payload['se_evidence'] = SE_EVIDENCE
        payload['fade_evidence'] = FADE_EVIDENCE
        payload['fade_mapping'] = FADE_MAPPING_NOTE
        payload['se_mapping'] = SE_MAPPING_NOTE
        payload['file_read_mapping'] = READ_MAPPING_NOTE
        if runtime is not None:
            payload['initial_state'] = ('新游戏零初值：状态块按 0x1151E0 的 memset 清零；'
                                        '0xA98C50 位表为零；未使用任何即时存档')
        else:
            payload['initial_state'] = ('显式即时存档快照，不是零初始化，不代表实际从指定剧本偏移进入'
                                        if snapshot_state is not None else INITIAL_STATE_NOTE)
        payload['state_evidence'] = STATE_EVIDENCE
        payload['display_evidence'] = DISPLAY_EVIDENCE
        payload['display_mapping'] = DISPLAY_MAPPING_NOTE
    with report.open('x', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write('\n')
    print(f'输出 {len(lines)} 句，停止于 {stop}')


if __name__ == '__main__':
    main()
