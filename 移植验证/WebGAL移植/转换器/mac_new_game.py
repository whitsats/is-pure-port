"""从零初值执行新游戏所需的已核实运行时子集。

`MAC_000.bin:0x0C` 是新游戏入口。原程序在 VM 初始化时把
`*(gp-0x6D44)` 起 `0x0D38680` 字节清零（`0x001151E0` 的 memset 证据）；
同一状态块的 `if`/`reg_calc` 读写由 `mac_state.State` 表示。

`reg_calc 0x17` 另外使用三块运行时数据：

* `0xA98C50`：已读/已解锁位表；
* `0xB1EC20`：位表检查的计数；
* `0xB25554`：场景表指针，`0xB25558` 是其长度。

这四块地址都落在 ELF 最后一个 PT_LOAD 的零填充区（文件末段从
`0x270A1C` 起 `0x1931BEC` 字节，`memsz > filesz`），没有静态初始内容。
本次新游戏指令流只执行脚本 `0x0C` 起的命令，不执行原生初始化调用
`0x001042B0`；本模块因此不把任何原生“批量解锁”写入模型，位表
`0xA98C50` 保持 BSS 的零初值。空白卡隔离冷启动实测：标题态位表为全 0，
两次 `0x17` 的旧位也都是 0，与本零初值一致；用户全通关卡上的 57 位全 1 是
另一个运行时状态（全通关进度），不能反推新游戏初值。见
`数据/运行期取证/隔离空白卡_新游戏初值.json`。

`0xB1EC20` 的实际计数取 57：标题静态表从 `0xAE8` 起有 57 条、每条 12 字节，
第 56 条在 `0xD88`，下一条 `0xD94` 的首指针为 0；这是**静态表长推导**。
ELF 中没有找到直接以 `0xEC20` 为偏移的存储指令，运行期写入点未取得，
也没有把它当成已证的新游戏运行时初值。旧存档在开场阶段的值同样只是旁证。
它是循环上界；新游戏路径还没有把 57 位填满，所以不会进入场景表分支。
为了避免把未装载的场景表当成空表，真进入“全部置位”分支时本模块显式拒绝，
而不是静默跳过。

`vib_set`（0x57）不读取剧情位表，只读取指令字节 1..5，写入状态
`+0x299..+0x29D`，再调用 `0x0013ED30`；后者清零 `+0x28C/+0x290/+0x294`。
WebGAL 没有对应硬件振动命令，本模块保留这些状态写入并把硬件效果记为
未映射，不把指令当空操作。

`quick_save` 的原始实现涉及记忆卡和辅助复制函数。这里的运行时只做
内存检查点记录并继续；它不伪造原版记忆卡写入，也不把检查点当成
已经还原的 `0x1161C0/0x116AD0`。
"""
from dataclasses import dataclass, field
import struct

from mac_state import State, UnsupportedCommand

NEW_GAME_SCRIPT = 'MAC_000.bin'
NEW_GAME_OFFSET = 0x0C
TITLE_RECORD_COUNT = 57
VISITED_BITS_BYTES = (TITLE_RECORD_COUNT + 7) // 8


@dataclass
class NewGameRuntime:
    """新游戏零初值运行时；只保存解释器实际会读写的状态和全局位表。"""

    title_records: list
    story_count: int = TITLE_RECORD_COUNT
    state: State = field(default_factory=State)
    visited_bits: bytearray = field(default_factory=lambda: bytearray(VISITED_BITS_BYTES))
    scene_table: tuple | None = None
    quick_saves: int = 0
    quick_save_checkpoints: list = field(default_factory=list)

    def __post_init__(self):
        if self.story_count < 0:
            raise ValueError('新游戏位表计数不能为负')
        if len(self.title_records) != self.story_count:
            raise ValueError('标题记录数与 0xB1EC20 的静态推导值不一致')
        expected = (self.story_count + 7) // 8
        if len(self.visited_bits) < expected:
            self.visited_bits.extend(b'\0' * (expected - len(self.visited_bits)))

    def bit(self, index):
        if index < 0:
            raise UnsupportedCommand('位表下标不能为负')
        if index >= self.story_count:
            raise UnsupportedCommand(f'0x17 下标 {index} 超出新游戏位表计数 {self.story_count}')
        return (self.visited_bits[index // 8] >> (index % 8)) & 1

    def set_bit(self, index):
        self.visited_bits[index // 8] |= 1 << (index % 8)

    def apply_reg17(self, raw):
        """按 0x00118FD0 的实际顺序执行一条 reg_calc 0x17。"""
        if len(raw) != 8 or raw[0] != 0x09 or raw[1] != 0x17:
            raise UnsupportedCommand('不是 8 字节 reg_calc 0x17')
        operand = struct.unpack_from('<H', raw, 2)[0]
        if operand >= self.story_count:
            raise UnsupportedCommand(
                f'0x17 操作数 {operand} 超出新游戏 {self.story_count} 条位表')
        previous = self.bit(operand)
        # 0x00117288 先置位，再按 0xB1EC20 的计数逐位检查；
        # 全部相关位为 1 时才调用 0x001174B8(3)。
        would_be_all_set = all(self.bit(i) or i == operand for i in range(self.story_count))
        if would_be_all_set and self.scene_table is None:
            raise UnsupportedCommand(
                '新游戏路径走到了 0x17 全置位分支，但未装载 0xB25554 场景表；'
                '拒绝把未知场景表当作空表')
        self.state.write_context_u16(0x440, operand)
        self.state.write_context_u32(0x4B0, previous)
        self.set_bit(operand)
        scene_indices = []
        if would_be_all_set:
            for index, entry in enumerate(self.scene_table):
                if len(entry) >= 12 and struct.unpack_from('<H', entry, 8)[0] == 3:
                    scene_indices.append(index)
        return {
            'operation': 'reg_calc_17_new_game',
            'operand': operand,
            'previous_bit': previous,
            'story_count': self.story_count,
            'bits_after': sum(self.bit(i) for i in range(self.story_count)),
            'all_set': would_be_all_set,
            'scene_flag_indices_set': scene_indices,
            'state_writes': {'+0x440': operand, '+0x4B0': previous},
            'bit_table': '0xA98C50',
            'evidence': {
                'state_zero': '0x001151E0 memset 0x0D38680 字节',
                'initial_bits': '0xA98C50 在 ELF 零填充区；本路径未执行原生 0x001042B0，不批量置位',
                'story_count': ('静态推导：标题表 0xAE8 起 57×12，末项 0xD88，下一项 0xD94 首指针 0；'
                                'ELF 直接存储扫描未发现运行期写入点'),
                'path': '0x00118FD0 → 0x00117270/0x00117288 → 0x001174B8',
            },
        }

    def apply_vib_set(self, raw):
        """实现 0x0011EF80 的状态字节写入，硬件振动只记录不模拟。"""
        if len(raw) != 8 or raw[0] != 0x57:
            raise UnsupportedCommand('不是 8 字节 vib_set')
        values = list(raw[1:6])
        writes = {f'+0x{0x299 + index:03X}': value for index, value in enumerate(values)}
        for index, value in enumerate(values):
            self.state.write_context_u8(0x299 + index, value)
        # 0x0013ED30 在调用外部振动对象后清零这三个字。
        for offset in (0x28C, 0x290, 0x294):
            self.state.write_context_u32(offset, 0)
            writes[f'+0x{offset:03X}'] = 0
        return {
            'operation': 'vib_set',
            'handler': '0x0011EF80',
            'raw_hex': raw.hex(),
            'bytes_1_to_5': values,
            'unused_bytes': raw[6:].hex(),
            'state_writes': writes,
            'hardware_call': '0x0013ED30（硬件振动对象；WebGAL 无对应命令）',
            'webgal': {'mapped': False,
                       'reason': '状态字节已按原处理函数写入；硬件振动不生成 WebGAL 命令，也不跳过本指令。'},
            'evidence': {
                'argument_bytes': '0x0011EF9C–0x0011EFEC 读取 ip[1..5]',
                'state_offsets': '0x0011EFA8–0x0011EFFC 写 G+0x299..0x29D',
                'zeroed_offsets': '0x0013ED84–0x0013ED9C 清零 G+0x28C/+0x290/+0x294',
            },
        }

    def apply_quick_save(self, raw):
        """记录内存检查点；不伪造原版记忆卡或辅助复制函数。"""
        if raw != bytes.fromhex('5a020000'):
            raise UnsupportedCommand(f'未核实的 quick_save 参数: {raw.hex()}')
        self.quick_saves += 1
        # 只保存稀疏状态，供本进程内诊断；不写入任何外部文件。
        self.quick_save_checkpoints.append(dict(self.state.memory_bytes))
        return {
            'operation': 'new_game_quick_save_checkpoint',
            'raw_hex': raw.hex(),
            'checkpoint_index': self.quick_saves,
            'state_changed': False,
            'original_internal_copy': ('0x0011D888 → 0x001161C0/0x00116AD0；'
                                       '本运行时不执行记忆卡和系统调用侧行为'),
            'note': '检查点只用于本进程诊断；原版记忆卡写入未实现，但本路径不依赖它进入对白。',
        }

    def report(self):
        return {
            'profile': 'new_game_zero_initial',
            'entry': {'script': NEW_GAME_SCRIPT, 'offset': f'0x{NEW_GAME_OFFSET:06X}'},
            'story_count': self.story_count,
            'story_count_status': 'static_derivation',
            'story_count_source': {
                'table_offset': '0x000AE8', 'record_size': 12, 'record_count': 57,
                'last_record_offset': '0x000D88', 'next_record_offset': '0x000D94',
                'next_record_first_pointer': '0x00000000',
                'runtime_write_point': '未取得；ELF 直接存储扫描为空，未排除 memcpy/表复制',
            },
            'visited_set_count': sum(self.bit(i) for i in range(self.story_count)),
            'visited_bits_hex': self.visited_bits.hex(),
            'scene_table': 'not_loaded',
            'quick_saves': self.quick_saves,
            'evidence': {
                'state_block_zero': ('0x001151E0 memset: *(gp-0x6D44) 起 0x0D38680 字节，值 0'),
                'global_tables_bss': ('0xA98C50、0xA98D10、0xB1EC20、0xB25554 均在 ELF 最后一个 '
                                      'PT_LOAD 的零填充区（0x270A1C 起），无静态文件初值'),
                'initial_bits': ('0xA98C50、0xA98D10 在 ELF 最后一个 PT_LOAD 的零填充区；'
                                 '本路径不执行原生 0x001042B0，不批量置位'),
                'story_count': ('静态推导：标题表 0xAE8 起 57×12，末项 0xD88，下一项 0xD94 首指针 0；'
                                '运行期写入点未取得，但空白卡冷启动 PINE 实读 0xB1EC20=57'),
                'scene_table': ('转换器零模型下 new_game 首次 0x17 不会让 57 位全为 1；'
                                '若全置位则显式拒绝，不把未知场景表当空表。'
                                '空白卡隔离冷启动实测新游戏位表为全 0、两次 0x17 旧位均为 0，'
                                '与零模型一致；全通关卡上的 57 位全 1 属于该存档进度，见运行期取证'),
                'vib_set': ('0x0011EF80 只读 ip[1..5] 并写 G+0x299..0x29D；'
                            '0x0013ED30 清零 G+0x28C/+0x290/+0x294'),
            },
        }
