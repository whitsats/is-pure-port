"""把原剧本的一段指令编译成可共享的 WebGAL 场景。

这取代原先写死在 `MAC_003:0x24D0–0x34AC` 的固定实现：编译入口按
「剧本名 + 起始偏移 (+ 可选结束偏移)」工作，保留每条指令的源偏移，
并把不能转换的内容按类别汇总，而不是只报第一处错误。

分工：
- `compile_range`：真正生成场景行；遇到第一个阻塞项就停在它之前，
  并给出 `Stop`（类别 + 源偏移 + 原字节）。`strict=True` 时改为抛错，
  报错文字与旧实现一致，供既有样片生成器继续使用。
- `scan_blockers`：对同一区间做静态扫描，把**所有**阻塞项按
  `choice / cross_script / effect / title / if_parameter / reg_calc /
  dynamic_wait / translation / unresolved_target / opcode` 分类汇总，
  用于批量试编时先看清障碍分布。它不执行状态、不产生场景行。
- `continuation`：第三组选项之后的既有区间，行为与旧实现逐字节一致。

状态写入只覆盖 `OPERANDS` 里已跟踪的字/位；其他目的操作数属于
「未跟踪」，会被列为 `reg_calc` 类别，不会静默丢弃。
"""
from dataclasses import dataclass, field
import csv
import json
from functools import cache

from emit_webgal import normalize_mapping_row
from mac_effect import emit_particle_effect, emit_screen_effect
from mac_jump import parse_ext_goto, parse_int_goto
from mac_release import DISC_DIALOGUE, ENGINEERING_DIALOGUE, ending_video_filename, restore_disc_dialogue
from mac_state import COMPARISONS, State, UnsupportedCommand, parse_if, parse_reg_calc
from mac_title_table import load_title_manifest, resolve_title_disp
from mac_wait import parse_time_wait
from mac_wiring import wired_for
from mac_webgal_state import emit_word_write, variable
from 验证新游戏首选项 import DATA, MAC, verified_voices

WORDS = (0x6000, 0x6007, 0x600E, 0x6026, 0x602A, 0x602B, 0x602C)
OPERANDS = (*WORDS, 0xA012)

# 已核实「不改变脚本前进、也不改剧情状态」的指令：只记账，不生成 WebGAL 语句。
# 与 emit_webgal 把同类指令写进 displays/file_reads/se_events 的处理保持一致。
PASS_THROUGH = {
    'graph_disp', 'graph_pos', 'graph_prio', 'msg_mode', 'msg_view', 'msg_wait',
    'msg_clear', 'fade_start', 'fade_wait', 'file_read', 'file_wait', 'se_set',
    'se_del', 'se_speed', 'se_req', 'se_vol', 'se_wait', 'vib_set', 'quick_save',
    # 存档锁只影响能否存档，原处理器推进 4 字节，不改剧情状态。
    'save_lock',
}

# 需要调用方决定如何接续的指令类别。
CATEGORY_BY_NAME = {
    'sel_disp4': 'choice',
    'sel_req': 'choice',
    'ext_goto': 'cross_script',
    'ext_call': 'cross_script',
    'ext_return': 'cross_script',
    'effect_start': 'effect',
    'effect_wait': 'effect',
    'title_disp': 'title',
    'end': 'end',
}

CATEGORY_NOTES = {
    'choice': '选项需要玩家输入；选项表解析见 mac_choice.py，编译停在该指令之前。',
    'cross_script': '跨剧本跳转/返回；需要目标剧本的场景与入口，未在此区间内解析。',
    'effect': '特效指令的状态副作用未核实，严格模式不执行（见 验证/effect_start_wait_隔离执行.json）。',
    'title': '章节标题需要 57 条静态标题表与 0x440/0x4B0 参数，未在此区间内展开。',
    'if_parameter': 'if 的参数/比较码超出已核实范围（0 参数、比较码 0–5）。',
    'reg_calc': 'reg_calc 的运算码、目的操作数或来源超出已跟踪范围。',
    'dynamic_wait': 'time_wait 的时长来自运行时变量，未核实换算。',
    'translation': '缺少唯一对应的 v7.4 译文，或文本含未处理特殊字符。',
    'unresolved_target': '跳转目标不在本次编译区间内，会生成悬空标签。',
    'opcode': '尚未核实的剧本指令。',
    'end': '原版结束指令；新版在此收尾，结局演出与回标题尚未还原。',
}


class Blocked(Exception):
    """单条指令无法转换；携带可汇总的类别。"""

    def __init__(self, category, detail):
        super().__init__(detail)
        self.category = category
        self.detail = detail


@dataclass
class Stop:
    script: str
    offset: int | None
    name: str | None
    raw_hex: str | None
    category: str
    reason: str

    def as_dict(self):
        return {'script': self.script, 'offset': self.offset, 'name': self.name,
                'raw_hex': self.raw_hex, 'category': self.category, 'reason': self.reason}


@dataclass
class Shadow:
    """编译期影子状态：只为 `reg_calc 0x17` 进度位与 `title_disp` 的静态解析服务。

    原程序把已播放的章节号写进上下文 `+0x440`（u16）与 `+0x4B0`（u32），并置
    `0xA98C50` 位表；`title_disp` 再读这两个字段选标题。本类按新游戏零初值
    重现这条链，不把进度位写进 WebGAL 变量（见 `progress_bit` 记账）。
    """
    state: State = field(default_factory=State)
    visited: set = field(default_factory=set)
    titles: list | None = None

    def title_records(self):
        if self.titles is None:
            self.titles = load_title_manifest()['records']
        return self.titles


@dataclass
class CompileResult:
    script: str
    start: int
    end: int | None
    lines: list = field(default_factory=list)
    used_voices: set = field(default_factory=set)
    labels: list = field(default_factory=list)
    targets: set = field(default_factory=set)
    ignored: list = field(default_factory=list)
    stop: Stop | None = None
    unresolved_targets: set = field(default_factory=set)
    ext_jumps: list = field(default_factory=list)

    @property
    def source_offsets(self):
        return [entry['offset'] for entry in self.ignored if 'offset' in entry]


@cache
def _command_index():
    return {entry['file']: entry['commands'] for entry in
            json.loads((DATA / '入口片段.json').read_text(encoding='utf-8'))['scripts']}


def load_commands(script):
    source = _command_index().get(script)
    if source is None:
        raise ValueError(f'入口片段里没有剧本: {script}')
    return source


@cache
def _row_index(mapping):
    rows = {}
    with mapping.open(encoding='utf-8-sig', newline='') as file:
        for row in csv.DictReader(file, delimiter='\t'):
            rows.setdefault(row['剧本'], {})[int(row['指令偏移'], 16)] = restore_disc_dialogue(
                normalize_mapping_row(row), mapping)
    return rows


def load_rows(script, mapping=DISC_DIALOGUE):
    return _row_index(mapping).get(script, {}).copy()


def collect_operands(commands, start=None):
    """推导一段区间实际引用的字/位操作数，供批量编译直接使用。

    与手写的 `OPERANDS` 相比，它不会漏掉区间里新出现的状态字（例如 MAC_003
    后半段的 0x6010/0x6014/0x601A）。推导只做地址归类：字覆盖两个字节、位只占
    一位；字与其他任一跟踪项共用地址时属于未完成的共享字节模型，会显式报错，
    不交给 WebGAL 变量近似。
    """
    layout = State()
    found = set()
    for command in commands:
        if start is not None and command['offset'] < start:
            continue
        raw = bytes.fromhex(command['raw_hex'])
        name = command['name']
        if name == 'reg_calc' and len(raw) == 8 and raw[:2] != b'\x09\x17':
            try:
                _, destination, source = parse_reg_calc(raw)
            except UnsupportedCommand:
                continue
            found.update((destination, source))
        elif name == 'if':
            try:
                _, left, right, _ = parse_if(raw)
            except UnsupportedCommand:
                continue
            found.update((left, right))
        elif name == 'time_wait':
            found.add(int.from_bytes(raw[2:4], 'little'))
    operands = {}
    for item in found:
        description = layout.describe(item)
        if description['kind'] == 'word':
            operands[item] = ('word', description['offset'], description['offset'] + 1)
        elif description['kind'] == 'bit':
            operands[item] = ('bit', description['offset'], description['offset'])
    for raw, (kind, low, high) in sorted(operands.items()):
        conflicts = [other for other, (other_kind, other_low, other_high) in operands.items()
                     if other != raw and other_low <= high and low <= other_high
                     and (kind != 'bit' or other_kind != 'bit')]
        if conflicts:
            raise ValueError(f'状态操作数共享地址，需先完成共享字节模型: {raw:#06x} 与 '
                             + ', '.join(f'{other:#06x}' for other in sorted(conflicts)))
    return tuple(sorted(operands))


def operand(encoded, words=OPERANDS):
    description = State().describe(encoded)
    if description['kind'] == 'value':
        return description['value']
    if encoded not in words:
        raise Blocked('if_parameter', f'未追踪的条件操作数: {encoded:#x}')
    return variable(encoded)


def _emit_progress_bit(raw, shadow, offset, ignored):
    """`reg_calc 0x17`：只写进度位与标题下标，不生成 WebGAL 语句。

    按 `0x00118FD0`：先把下标写进 `+0x440`（u16）与旧位 `+0x4B0`（u32），再置位；
    57 位全为 1 时调 `0x001174B8(3)` 走场景表，那一段仍未接，所以显式拒绝。
    """
    if shadow is None:
        raise Blocked('reg_calc', f'{offset:#x}: 进度位 0x17 需要编译期影子状态')
    records = shadow.title_records()
    bit = int.from_bytes(raw[2:4], 'little')
    if bit >= len(records):
        raise Blocked('reg_calc', f'{offset:#x}: 0x17 下标 {bit} 超出 {len(records)} 条进度位')
    previous = 1 if bit in shadow.visited else 0
    if all(index in shadow.visited for index in range(len(records)) if index != bit):
        raise Blocked('reg_calc', f'{offset:#x}: 进入 0x17 全置位分支，需要 0xB25554 场景表')
    shadow.state.write_context_u16(0x440, bit)
    shadow.state.write_context_u32(0x4B0, previous)
    shadow.visited.add(bit)
    ignored.append({'offset': offset, 'name': 'reg_calc', 'category': 'progress_bit',
                    'operand': bit, 'previous': previous,
                    'note': '只置原程序进度位与标题下标；WebGAL 侧不持久化'})
    return []


def _emit_title(raw, shadow, offset):
    """`title_disp`：用区间内 `0x17` 写入的下标选静态 57 条标题。"""
    if shadow is None or 0x440 not in shadow.state.memory_bytes or 0x441 not in shadow.state.memory_bytes:
        raise Blocked('title', f'{offset:#x}: 标题下标不是本区间内 0x17 写入的')
    try:
        resolved = resolve_title_disp(raw, shadow.state, shadow.title_records())
    except UnsupportedCommand as exc:
        raise Blocked('title', f'{offset:#x}: {exc}') from exc
    return [resolved['command']]


CONTROL_CODE = __import__('re').compile(r'%[A-Za-z]')
CONTROL_TOKEN = __import__('re').compile(r'%[A-Za-z]{1,2}')
CONTROL_ONLY = __import__('re').compile(r'(?:%[A-Za-z]{1,2}|[…　 ])+')


def _control_only(row):
    """纯控制码对白：原字节只有 %p/%P/%K 与省略号，盘上因此没有中文。

    这些 `msg_disp2` 的文本槽本身以 0 结尾，后面的正文属于下一条指令；
    去掉控制码后为空就只是推进，剩下省略号时照原字符显示。
    """
    if row.get('仅控制行'):
        return ''
    if row.get('匹配状态') != '原字节不变' or row.get('中文（原对照表）'):
        return None
    original = row.get('日文原文') or ''
    if not original or CONTROL_ONLY.fullmatch(original) is None:
        return None
    return CONTROL_CODE.sub('', original).replace('　', ' ').strip()


def _emit(command, rows, voices, words, targets, used_voices, ignored, shadow=None,
          particle_effects=False, target_scenes=None, screen_effects=False, hd=False):
    """把一条指令换成 WebGAL 行；不能转换时抛 Blocked。"""
    offset = command['offset']
    raw = bytes.fromhex(command['raw_hex'])
    name = command['name']
    if screen_effects and name in ('effect_start', 'effect_wait', 'graph_pal'):
        if name == 'graph_pal' and raw in (b'\x30\x01\x0d\x00', b'\x30\x02\x0d\x00', b'\x30\x03\x0d\x00'):
            lines, phase = [], f'palette_slot_{raw[1]}'
        else:
            try:
                lines, phase = emit_screen_effect(raw)
            except UnsupportedCommand as exc:
                raise Blocked('effect', f'{offset:#x}: {exc}') from exc
        ignored.append({'offset': offset, 'name': name, 'category': 'screen_visual_omitted',
                        'phase': phase, 'raw_hex': raw.hex()})
        return lines
    if name == 'nop' and raw == b'\0' * 4:
        return []
    if particle_effects and name in ('effect_start', 'effect_wait'):
        try:
            lines, phase = emit_particle_effect(raw)
        except UnsupportedCommand as exc:
            raise Blocked('effect', f'{offset:#x}: {exc}') from exc
        ignored.append({'offset': offset, 'name': name, 'category': 'particle_visual_omitted',
                        'phase': phase, 'raw_hex': raw.hex()})
        return lines
    if name == 'reg_calc' and raw[:2] == b'	':
        return _emit_progress_bit(raw, shadow, offset, ignored)
    if name == 'title_disp':
        return _emit_title(raw, shadow, offset)
    if name == 'if':
        try:
            target, left, right, comparison = parse_if(raw)
        except UnsupportedCommand as exc:
            raise Blocked('if_parameter', f'{offset:#x}: {exc}') from exc
        operator = COMPARISONS[comparison][0]
        condition = f'{operand(left, words)}{operator}{operand(right, words)}'
        if target_scenes and target in target_scenes:
            return [f'changeScene:{target_scenes[target]} -when={condition};']
        targets.add(target)
        return [f'jumpLabel:mac_{target:x} -when={condition};']
    if name == 'int_goto':
        target = parse_int_goto(raw)
        if target_scenes and target in target_scenes:
            return [f'changeScene:{target_scenes[target]};']
        targets.add(target)
        return [f'jumpLabel:mac_{target:x};']
    if name == 'reg_calc':
        try:
            output = emit_word_write(raw, words, f'continuation_{offset:x}')
        except UnsupportedCommand as exc:
            raise Blocked('reg_calc', f'{offset:#x}: {exc}') from exc
        if not output:
            raise Blocked('reg_calc', f'{offset:#x}: 状态写入缺少运行时映射（目的操作数未跟踪）')
        return output
    if name == 'msg_disp2':
        row = rows.get(offset)
        if row is not None and (text := _control_only(row)) is not None:
            ignored.append({'offset': offset, 'name': name, 'category': 'control_code_line',
                            'raw_text': row['日文原文'], 'text': text,
                            'note': '去掉 % 控制码后的可见内容；空字符串表示只推进'})
            return [f'{text};'] if text else []
        line = row['中文（原对照表）'] if row else ''
        if row and not line:
            # v7.4 打盘包没有译这一行（文本槽仍是日文）。按原样显示日文，
            # 并把剧本、偏移与原字节记入报告，不拦下整章。
            original = row.get('日文原文') or ''
            line = CONTROL_TOKEN.sub('', original).strip()
            if not line:
                raise Blocked('translation', f'{offset:#x}: 缺少可用对白或文本含特殊字符')
            line = line.translate(str.maketrans({';': '；', '|': '｜', ':': '：'}))
            ignored.append({'offset': offset, 'name': name, 'category': 'untranslated_japanese',
                            'raw_text': original, 'text': line,
                            'note': 'v7.4 打盘包的文本槽仍为日文，按原文显示；待补译'})
        elif not row or row['匹配状态'] != '唯一匹配' or any(c in line for c in ';:|\\\r\n'):
            raise Blocked('translation', f'{offset:#x}: 缺少可用对白或文本含特殊字符')
        voice = int(row['语音号'])
        if voice >= 0:
            if voice not in voices:
                raise Blocked('translation', f'{offset:#x}: 语音 {voice} 未通过校验')
            used_voices.add(voice)
            line += f' -{voices[voice]}'
        res = [f'{line};']
        if hd and line.startswith('我一个人走进了神社。'):
            res.append('unlockCg:EV_0088.png -name=EV036「泉と神社へ」 -order=88 -thumb=thumb/EV_0088.webp -next;')
        return res
    if name == 'time_wait':
        source_operand = int.from_bytes(raw[2:4], 'little')
        if State().describe(source_operand)['kind'] != 'value':
            raise Blocked('dynamic_wait', f'{offset:#x}: 未支持的动态等待')
        return [parse_time_wait(raw, State())['command']]
    if name == 'movie_play':
        if raw == bytes.fromhex('52010100'):
            resource = ending_video_filename(hd=hd)
            ignored.append({'offset': offset, 'name': name, 'category': 'movie_mapped',
                            'raw_hex': raw.hex(), 'resource': resource})
            if hd:
                return [f'playVideo:{resource} -unlockfile=EV_0136.png -unlockname=EV_END01「エンディング」 '
                        '-unlockorder=136 -unlockthumb=thumb/EV_0136.webp;']
            return [f'playVideo:{resource};']
        ignored.append({'offset': offset, 'name': name, 'category': 'movie_omitted',
                        'raw_hex': raw.hex(), 'note': '原作在此播放影片；样片不渲染视频，直接推进'})
        return []
    if name in PASS_THROUGH:
        ignored.append({'offset': offset, 'name': name, 'category': 'pass_through'})
        return []
    category = CATEGORY_BY_NAME.get(name, 'opcode')
    raise Blocked(category, f'{offset:#x}: 未支持的剧本指令 {name}')


def compile_range(script, start, end=None, stop_names=('sel_disp4',), words=None, strict=False,
                  extra_labels=(), shadow=None, ext_scene=None, particle_effects=False, target_scenes=None,
                  rows=None, voices=None, screen_effects=False, graphics=None):
    """编译 script 从 start（含）到阻塞项或 end（含）之前的场景行。

    返回值保留源偏移（`ignored` 记录只记账的指令），并在 `stop` 里说明为什么停下。
    `words=None` 时从区间实际引用推导跟踪操作数（`collect_operands`），
    传入元组时只用调用者给的集合（既有样片靠这个保持逐字节一致）。
    `strict=True` 时遇到阻塞项直接抛 ValueError，文字与旧实现一致。
    `extra_labels` 是额外要生成 `label` 的偏移（例如选项表里的分支目标，它们不是
    `if`/`int_goto` 的目标），必须落在命令边界且在本区间内。
    `shadow` 是编译期影子状态（进度位与标题下标）；不给时新建一个零初值实例。
    `ext_scene` 是 `(目标剧本名, 入口偏移) -> 场景文件名` 的映射；给出时 `ext_goto`
    在段末写成 `changeScene` 并停下，调用方负责生成目标场景。
    `particle_effects` 仅用于调用方核实了结束请求与完成检查配对的场景，省略粒子画面。
    `target_scenes` 将同剧本中另外编译的目标偏移接成场景切换。
    """
    commands = load_commands(script)
    shadow = Shadow() if shadow is None else shadow
    if words is None:
        words = collect_operands(commands, start)
    offsets = [c['offset'] for c in commands]
    if start not in offsets:
        raise ValueError(f'开始偏移不是命令边界: {start:#x}（{script}）')
    missing = [offset for offset in extra_labels if offset not in offsets or offset < start]
    if missing:
        raise ValueError(f'额外标签不是区间内的命令边界: {[hex(x) for x in missing]}（{script}）')
    if target_scenes and not set(target_scenes).issubset(offsets):
        raise ValueError(f'外接场景的目标不在 {script} 命令边界')
    rows = load_rows(script) if rows is None else rows
    voices = verified_voices() if voices is None else voices
    result = CompileResult(script=script, start=start, end=end)
    pending, jumped_at = [], {}
    stop = None
    for command in commands[offsets.index(start):]:
        offset = command['offset']
        if end is not None and offset > end:
            stop = Stop(script, offset, command['name'], command['raw_hex'], 'range_end',
                        f'超出指定范围末尾 0x{end:X}')
            break
        if command['name'] in stop_names:
            stop = Stop(script, offset, command['name'], command['raw_hex'],
                        CATEGORY_BY_NAME.get(command['name'], 'choice'),
                        CATEGORY_NOTES.get(CATEGORY_BY_NAME.get(command['name'], 'choice'),
                                           '我在此停止编译。'))
            break
        if command['name'] == 'end':
            stop = Stop(script, offset, command['name'], command['raw_hex'], 'end', CATEGORY_NOTES['end'])
            break
        if command['name'] == 'ext_goto' and ext_scene is not None:
            raw = bytes.fromhex(command['raw_hex'])
            try:
                jump = parse_ext_goto(raw, MAC)
            except UnsupportedCommand as exc:
                stop = Stop(script, offset, command['name'], command['raw_hex'], 'cross_script',
                            f'{offset:#x}: {exc}')
                if strict:
                    raise ValueError(stop.reason) from exc
                break
            scene = ext_scene(jump['target_script'], jump['target_entry'])
            change = f'changeScene:{scene};'
            pending.append((offset, [change]))
            jumped_at[offset] = set()
            jump['webgal'] = {'mapped': True, 'command': change,
                              'reason': '目标场景由调用方生成；原程序不生成其他伪造命令。'}
            result.ext_jumps.append({**jump, 'scene': scene})
            stop = Stop(script, offset, command['name'], command['raw_hex'], 'cross_script',
                        f'{offset:#x}: 已写成 {change}（{jump["effect"]}）')
            break
        before = set(result.targets)
        try:
            if graphics and offset in graphics:
                output = graphics[offset]
            else:
                output = _emit(command, rows, voices, words, result.targets, result.used_voices,
                               result.ignored, shadow, particle_effects, target_scenes, screen_effects,
                               hd=graphics is not None)
        except Blocked as exc:
            if strict:
                raise ValueError(exc.detail) from exc
            stop = Stop(script, offset, command['name'], command['raw_hex'], exc.category, exc.detail)
            break
        jumped_at[offset] = result.targets - before
        pending.append((offset, output))
    else:
        stop = Stop(script, None, None, None, 'range_end', '到达已解析范围末尾')
    result.targets.update(extra_labels)
    covered = {offset for offset, _ in pending}
    if stop is not None and stop.offset is not None:
        covered.add(stop.offset)
    unreachable = set(result.targets) - covered
    if unreachable:
        # 跳到区间外的标签会生成悬空 jumpLabel；截断到第一处这样的指令。
        first = next((offset for offset, added in jumped_at.items() if added & unreachable), stop.offset if stop else None)
        detail = f'{sorted(hex(x) for x in unreachable)}'
        if strict:
            raise ValueError(f'存在未解析的跳转目标: {sorted(unreachable)}')
        result.unresolved_targets = unreachable
        keep = [(offset, block) for offset, block in pending if first is None or offset < first]
        dropped = [(offset, block) for offset, block in pending if first is not None and offset >= first]
        for offset, _ in dropped:
            result.ignored.append({'offset': offset, 'name': next(
                c['name'] for c in commands if c['offset'] == offset), 'category': 'unsupported_after_stop'})
        pending = keep
        command = next((c for c in commands if c['offset'] == first), None)
        stop = Stop(script, first, command['name'] if command else None,
                    command['raw_hex'] if command else None, 'unresolved_target',
                    f'跳转目标不在编译区间: {detail}；{CATEGORY_NOTES["unresolved_target"]}')
    result.stop = stop
    lines = []
    synthetic = [(offset, block) for offset, block in pending]
    if stop is not None and stop.offset is not None:
        synthetic.append((stop.offset, []))
    for offset, block in synthetic:
        if offset in result.targets:
            lines.append(f'label:mac_{offset:x} -next;')
            result.labels.append(offset)
        lines.extend(block)
    result.lines = lines
    return result


def scan_blockers(script, start, end=None, words=None, sample_limit=5, shadow=None, particle_effects=False,
                  rows=None, voices=None, screen_effects=False):
    """静态扫描区间内所有阻塞项，按类别汇总；不执行状态、不生成场景行。

    与 `compile_range` 相反，它越过阻塞项继续看后面的指令，用于批量试编前
    先了解障碍分布（例如某段只剩 effect_start 和跨剧本跳转）。
    `words=None` 时同样按区间引用推导跟踪操作数。

    已经接进样片的点（见 `mac_wiring.WIRED`）不算阻塞，单独列在 `wired` 里并
    带原类别，所以 `blocker_total` 就是真实剩余数，不需要调用方再手工扣减。
    """
    commands = load_commands(script)
    if words is None:
        words = collect_operands(commands, start)
    offsets = [c['offset'] for c in commands]
    if start not in offsets:
        raise ValueError(f'开始偏移不是命令边界: {start:#x}（{script}）')
    rows = load_rows(script) if rows is None else rows
    voices = verified_voices() if voices is None else voices
    summary, order, passed = {}, [], {}
    wired = []
    shadow = Shadow() if shadow is None else shadow
    for command in commands[offsets.index(start):]:
        if end is not None and command['offset'] > end:
            break
        wiring = wired_for(script, command['offset'])
        if wiring is not None:
            wired.append({'offset': f'0x{command["offset"]:X}', 'name': command['name'],
                          **wiring})
            continue
        try:
            _emit(command, rows, voices, words, set(), set(), [], shadow, particle_effects,
                  screen_effects=screen_effects)
        except Blocked as exc:
            entry = summary.setdefault(exc.category, {'category': exc.category, 'count': 0,
                                                      'offsets': [], 'samples': [],
                                                      'note': CATEGORY_NOTES.get(exc.category, '')})
            if exc.category not in order:
                order.append(exc.category)
            entry['count'] += 1
            if len(entry['offsets']) < sample_limit:
                entry['offsets'].append(f'0x{command["offset"]:X}')
            if len(entry['samples']) < 2:
                entry['samples'].append(exc.detail)
        else:
            passed[command['name']] = passed.get(command['name'], 0) + 1
        if command['name'] in PASS_THROUGH:
            passed.setdefault('pass_through', 0)
    return {'script': script, 'start': start, 'end': end,
            'handled': dict(sorted(passed.items())),
            'blockers': [summary[name] for name in order],
            'blocker_total': sum(entry['count'] for entry in summary.values()),
            'wired': wired,
            'wired_total': len(wired)}


def continuation():
    """第三组选项之后的既有区间；输出必须与旧实现一致。"""
    result = compile_range('MAC_003.bin', 0x24D0, end=0x34AC, words=OPERANDS, strict=True,
                           rows=load_rows('MAC_003.bin', ENGINEERING_DIALOGUE))
    if result.stop is None or (result.stop.offset, result.stop.name) != (0x34AC, 'sel_disp4'):
        raise ValueError('第四组选项的剧本范围有变化')
    return result.lines, result.used_voices
