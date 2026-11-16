"""导出新游戏 0x17 初值的可复核证据。

这里只固化能从仓库中的 ELF、静态标题表和原指令字节直接核对的内容：
* 状态块 memset 的调用点和长度；
* 位表/场景标志/计数字所在 ELF 中的位置；
* 0x17、vib_set 的处理函数和读取/写入指令；
* 标题表边界及 57 的来源。

`0xB1EC20` 没有找到独立的运行期写入指令；本脚本把它标成 `static_derivation`，
并在 `runtime_write_point` 明确写“未取得”，不把它伪装成已证的新游戏初值。
"""
import argparse
import hashlib
import json
import struct
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path[:0] = [str(HERE), str(ROOT.parent)]

import MAC_命令表提取 as common  # noqa: E402
import 状态字证据 as state_evidence  # noqa: E402
from capstone import Cs, CS_ARCH_MIPS, CS_MODE_MIPS64, CS_MODE_LITTLE_ENDIAN  # noqa: E402

DEFAULT_TITLE = ROOT / '数据/章节标题静态表.json'
DEFAULT_OUTPUT = ROOT / '数据/新游戏0x17证据.json'

STATE_BLOCK_CALL = 0x1151E0
VIB_SET_HANDLER = 0x11EF80
REG17_HANDLER = 0x118FD0
READ_COUNT = (0x117204, 0x1172AC)
BSS_ADDRESSES = {
    'visited_bit_table': 0xA98C50,
    'scene_flag_table': 0xA98D10,
    'story_count': 0xB1EC20,
    'scene_table_pointer': 0xB25554,
}


def section_table(data):
    ident = data[:16]
    if ident[4] != 1:
        raise ValueError('只支持 ELF32')
    hdr = struct.unpack_from('<16sHHIIIIIHHHHHH', data, 0)
    _, _, _, _, _, _, shoff, _, _, _, _, shentsize, shnum, shstrndx = hdr
    sections = [struct.unpack_from('<IIIIIIIIII', data, shoff + index * shentsize)
                for index in range(shnum)]
    strings = sections[shstrndx]
    names = data[strings[4]:strings[4] + strings[5]]

    def name(offset):
        end = names.find(b'\0', offset)
        return names[offset:end].decode('latin1')

    return [{'name': name(item[0]), 'type': item[1], 'address': item[3],
             'size': item[5], 'offset': item[4]} for item in sections]


def instruction(d, address, mnemonic, op):
    item = d.find(address, 0x40, mnemonic, op)
    return {'address': item['at'], 'instruction': f'{mnemonic} {op}',
            'bytes': item['bytes']}


def direct_store_scan(data, segs, address):
    """只扫描直接使用 0xEC20 低偏移的存储；不声称覆盖 memcpy/表复制。"""
    hits = []
    for kind, offset, vaddr, _, filesz, _, flags, _ in segs:
        if kind != 1 or not (flags & 1):
            continue
        for cursor in range(0, filesz, 4):
            word = struct.unpack_from('<I', data, offset + cursor)[0]
            opcode = word >> 26
            if opcode in (0x28, 0x29, 0x2B, 0x3F) and (word & 0xFFFF) == 0xEC20:
                hits.append(f'0x{vaddr + cursor:08X}')
    return hits


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument('--title-table', type=Path, default=DEFAULT_TITLE)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)

    data = common.ELF.read_bytes()
    segs = state_evidence.segments(data)
    d = state_evidence.Dis(data, segs)
    sections = section_table(data)
    bss = next(item for item in sections if item['name'] == '.bss')
    if bss['type'] != 8:
        raise ValueError('.bss 不是 NOBITS')
    if not (bss['address'] <= min(BSS_ADDRESSES.values())
            and max(BSS_ADDRESSES.values()) < bss['address'] + bss['size']):
        raise ValueError('地址不在 .bss 范围内')

    memset_call = d.find(STATE_BLOCK_CALL, 0x10, 'jal', '0x1fbb84')
    memset_call_address = memset_call['at']
    # 0x001151B8 的 a0 是 *(gp-0x6D44)，a1=0，a2=0xD38680。
    memset_code = []
    for item in d.read(0x1151B8, 0x30):
        memset_code.append({'address': item['at'], 'instruction':
                            f'{item["mnemonic"]} {item["op"]}', 'bytes': item['bytes']})
    if d.find(0x1151B8, 0x10, 'lw', '$a0, -0x6d44($gp)') is None:
        raise ValueError('状态块 memset 的 a0 不符合')
    if d.find(0x1151B8, 0x20, 'ori', '$a2, $a2, 0x8680') is None:
        raise ValueError('状态块 memset 长度不符合')

    title = json.loads(args.title_table.read_text(encoding='utf-8'))
    records = title['records']
    if title['record_count'] != len(records) or len(records) != 57:
        raise ValueError('标题表记录数不是 57')
    last = records[-1]
    if last['record_offset'] != '0x000D88' or title['next_record_offset'] != '0x000D94':
        raise ValueError('标题表边界与清单不一致')
    if title['next_record_first_pointer'] != '0x00000000':
        raise ValueError('标题表第 57 项首指针不是 0')

    branch17 = [{'address': f'0x{item["at"]}', 'instruction': f'{item["mnemonic"]} {item["op"]}',
                 'bytes': item['bytes']} for item in d.read(REG17_HANDLER, 0x20)]
    count_reads = []
    for address in READ_COUNT:
        item = d.find(address, 0x10, 'lw', '$s1, -0x13e0($v0)')
        count_reads.append({'address': item['at'],
                            'instruction': 'lw $s1, -0x13e0($v0)',
                            'bytes': item['bytes']})
    vib = [{'address': f'0x{item["at"]}', 'instruction': f'{item["mnemonic"]} {item["op"]}',
            'bytes': item['bytes']} for item in d.read(VIB_SET_HANDLER, 0x50)]
    store_scan = direct_store_scan(data, segs, BSS_ADDRESSES['story_count'])

    payload = {
        'elf': str(common.ELF),
        'elf_sha256': hashlib.sha256(data).hexdigest(),
        'title_table': {
            'path': str(args.title_table),
            'sha256': hashlib.sha256(args.title_table.read_bytes()).hexdigest(),
            'table_offset': title['table_offset'],
            'record_size': title['record_size'],
            'record_count': title['record_count'],
            'last_record_offset': last['record_offset'],
            'next_record_offset': title['next_record_offset'],
            'next_record_first_pointer': title['next_record_first_pointer'],
        },
        'bss': {'address': f'0x{bss["address"]:08X}',
                'size': f'0x{bss["size"]:X}',
                'section_type': 'SHT_NOBITS',
                'addresses': {key: f'0x{value:06X}' for key, value in BSS_ADDRESSES.items()}},
        'items': {
            'state_block': {
                'status': 'code_evidence',
                'source': 'ELF 0x001151B8–0x001151E0；状态块清零',
                'call': {'address': memset_call_address,
                         'instruction': 'jal 0x1FBB84', 'bytes': memset_call['bytes']},
                'a0': '*(gp-0x6D44)', 'a1': 0, 'size': '0x0D38680',
                'code': memset_code,
            },
            'visited_bit_table': {
                'status': 'static_derivation',
                'source': 'ELF .bss；0x00117270/0x00117288 的读写路径',
                'initial': '0xA98C50 在 NOBITS .bss 中，初始为零',
            },
            'scene_flag_table': {
                'status': 'static_derivation',
                'source': 'ELF .bss；0x001174B8/0x00117638 的场景标志路径',
                'initial': '0xA98D10 在 NOBITS .bss 中，初始为零',
            },
            'story_count': {
                'status': 'static_derivation',
                'value': 57,
                'source': '标题表 0x000AE8 起 57 条 × 12 字节；0xB1EC20 是 0x117204/0x1172AC 的读取上界',
                'runtime_write_point': '未取得：ELF 中直接以 0xEC20 为偏移的存储扫描为空；'
                                       '未排除 memcpy/表复制写点',
                'static_direct_store_hits': store_scan,
                'reads': count_reads,
            },
            'scene_table_pointer': {
                'status': 'unknown',
                'source': 'ELF .bss 中 0xB25554 初始为零；运行期由未知装载器写入（旧快照为 0xA58A8C）',
                'initial': '本路径不执行全置位分支，因此未读取',
            },
            'reg17': {
                'status': 'code_evidence',
                'address': '0x00118FD0',
                'instruction': branch17,
                'state_writes': {'G+0x440': '操作数下标（sh at 0x00118FE0）',
                                 'G+0x4B0': '设置前位值（sw at 0x00118FEC）'},
            },
            'vib_set': {
                'status': 'code_evidence',
                'address': '0x0011EF80',
                'instruction': vib,
                'state_offsets': ['G+0x299..G+0x29D'],
                'zero_offsets': ['G+0x28C', 'G+0x290', 'G+0x294'],
                'webgal': '硬件振动不映射，但状态写入不跳过',
            },
            'quick_save': {
                'status': 'unknown',
                'note': '本轮只记录进程内检查点；未实现 0x001161C0/0x00116AD0 的记忆卡/内部复制',
            },
        },
        'status_values': {
            'code_evidence': '原程序指令/字节直接核对',
            'static_derivation': '由静态表/ELF 布局推导，运行期写入点未取得',
            'unknown': '当前没有足够证据，不当作已证初值',
        },
    }
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n',
                           encoding='utf-8')
    print('输出', args.output)
    print('story_count:', payload['items']['story_count']['status'],
          '57; direct_store_hits=', len(store_scan))


if __name__ == '__main__':
    main()
