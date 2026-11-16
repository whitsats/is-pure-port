"""记录 ELF 中画面资源加载器及资源描述表的静态证据。"""
import argparse
import hashlib
import json
import struct
from pathlib import Path

from capstone import Cs, CS_ARCH_MIPS, CS_MODE_LITTLE_ENDIAN, CS_MODE_MIPS64
from mac_reader import ROOT
import MAC_命令表提取 as common


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    data = common.ELF.read_bytes()

    def segment(address, length):
        hdr = struct.unpack_from('<16sHHIIIIIHHHHHH', data)
        for index in range(hdr[10]):
            kind, off, va, _, size, _, _, _ = struct.unpack_from('<8I', data, hdr[5] + index * hdr[9])
            if kind == 1 and va <= address and address + length <= va + size:
                return data[off + address - va:off + address - va + length]
        raise ValueError(f'ELF 地址无文件数据: {address:#x}')

    md = Cs(CS_ARCH_MIPS, CS_MODE_MIPS64 | CS_MODE_LITTLE_ENDIAN)
    shifts = []
    for address in (0x12D870, 0x12D888, 0x12D8A0):
        instruction = list(md.disasm(segment(address, 4), address))
        if len(instruction) != 1 or instruction[0].mnemonic != 'sll' or instruction[0].op_str != '$a1, $a1, 1':
            raise ValueError(f'资源索引移位指令不符: {address:#x}')
        shifts.append({'address': hex(address), 'instruction': 'sll $a1, $a1, 1'})
    jump_addresses = list(struct.unpack('<8I', segment(0x259FD0, 32)))
    if jump_addresses[:4] != [0x12D850, 0x12D860, 0x12D878, 0x12D890]:
        raise ValueError('资源组跳转表与预期不符')
    descriptors = []
    for index in range(8):
        address = 0x212E50 + 0x20 * index
        words = struct.unpack('<8I', segment(address, 32))
        name = segment(words[2], 16).split(b'\0')[0].decode('ascii')
        descriptors.append({'slot': index, 'descriptor': hex(address), 'archive': name, 'field4': words[4]})
    if [x['archive'] for x in descriptors] != ['mac.afs', 'bg.afs', 'ev.afs', 'chr.afs', 'bgm.afs', 'se.afs', 'voice.afs', 'etc.afs']:
        raise ValueError('资源描述表名称与预期不符')
    report = {'elf_sha256': hashlib.sha256(data).hexdigest(), 'dispatch_table': hex(0x259FD0),
              'dispatch_targets': [hex(x) for x in jump_addresses], 'double_index_instructions': shifts,
              'archive_descriptors': descriptors,
              'scope': '描述表排列和加载器按组索引共同支持资源候选；初始化时描述表与加载器资源指针的连接仍待追踪。'}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
        f.write('\n')
    print('ELF 校验通过，资源描述表:', [x['archive'] for x in descriptors])


if __name__ == '__main__':
    main()
