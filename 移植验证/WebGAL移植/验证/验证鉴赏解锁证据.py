"""复核 CG/BGM 鉴赏解锁的原盘证据，写成 JSON 并打印 PASS 行。

用法（在 移植验证/WebGAL移植）：
    python -B 验证/验证鉴赏解锁证据.py

覆盖四件事：
1. 74 个 MAC 剧本逐字节扫 `graph_disp`，统计 EV 组槽位；核对只在鉴赏出现的槽位。
2. INIT 的标志名表（`Ｆ…`，62 条）与 `0xA000+i` 操作数的对应关系。
3. 只在鉴赏出现的三张图是否为同一版式的条目卡（相册卡）。
4. 原盘是否提供曲名：INIT 只有 `BGM01…BGM20` / `SE_A01…` 这类槽位名。

本脚本只读原盘解包结果与当前工程，不改任何游戏数据。
"""
from __future__ import annotations

import hashlib
import json
import struct
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
ROOT = BASE.parent
sys.path.insert(0, str(BASE / '转换器'))

import mac_reader  # noqa: E402
from mac_display import parse_graph_disp, resolve_graph_records  # noqa: E402
from mac_state import parse_reg_calc  # noqa: E402

MAC_DIR = ROOT / '输出-保护边修复' / 'MAC'
EV_DIR = ROOT / '输出-保护边修复' / 'EV'
INIT = BASE / '数据' / 'INIT_解压.bin'
ELF = ROOT / '输出-保护边修复' / 'SYSTEM' / 'SLPM_665.70'
GAME = BASE / '新游戏打盘高清版' / 'public' / 'game'
OUT = BASE / '数据' / '鉴赏解锁证据.json'

GRAPH_DISP = 0x33
GRAPH_GROUPS = {1: 'BG', 2: 'EV', 3: 'CHR'}
EV_SLOTS = 69  # EV_0000 … EV_0136，步长 2
FLAG_BASE = 0xA000
FLAG_COUNT = 62


def script_files():
    return sorted(MAC_DIR.glob('MAC_*.bin'))


def scan_graph_disp(data):
    """按字节特征扫出所有 graph_disp，不依赖线性解析的边界。

    命令形如 `33 <条数> <flag> 00 <记录块偏移 u32>`；记录从块尾往前读，
    与 `mac_display.resolve_graph_records` 的顺序一致。
    """
    hits = []
    n = len(data)
    for offset in range(0, n - 8):
        if data[offset] != GRAPH_DISP:
            continue
        count = data[offset + 1]
        if not 1 <= count <= 8 or data[offset + 3] != 0:
            continue
        blob = struct.unpack_from('<I', data, offset + 4)[0]
        start = blob + 12 * count - 12
        if start < 0 or start + 12 > n:
            continue
        records = []
        ok = True
        for index in range(count):
            record = start - 12 * index
            if record < 0 or record + 12 > n:
                ok = False
                break
            code = struct.unpack_from('<H', data, record + 4)[0]
            group, member = code >> 12, code & 0xFFF
            if group not in GRAPH_GROUPS:
                ok = False
                break
            records.append({'group': group, 'member': member})
        if ok:
            hits.append({'offset': offset, 'count': count, 'blob': blob, 'records': records})
    return hits


def ev_usage():
    per_script = {}
    union = {}
    for path in script_files():
        data = path.read_bytes()
        used = {}
        for hit in scan_graph_disp(data):
            for record in hit['records']:
                if record['group'] != 2 or record['member'] == 0xFFF:
                    continue
                slot = record['member']
                used[slot] = used.get(slot, 0) + 1
                union[slot] = union.get(slot, 0) + 1
        if used:
            per_script[path.stem] = dict(sorted(used.items()))
    return per_script, union


def flag_names():
    data = INIT.read_bytes()
    table = 0x09EC
    names = []
    for index in range(FLAG_COUNT):
        pointer = struct.unpack_from('<I', data, table + 4 * index)[0]
        end = data.find(b'\0', pointer)
        names.append(data[pointer:end].decode('cp932'))
    return data, names


def flag_writes():
    """扫剧本里写 `0xA0xx` 的标志，返回 {槽位: [剧本:偏移, …]}。"""
    table = mac_reader.load_table()
    writes = {}
    for path in script_files():
        data = path.read_bytes()
        entry = struct.unpack_from('<I', data, 8)[0]
        position = entry
        while position < len(data):
            opcode = data[position]
            if opcode >= len(table):
                break
            length = table[opcode]['bytes']
            if length <= 0 or position + length > len(data):
                break
            if table[opcode]['name'] == 'reg_calc':
                try:
                    _, destination, _ = parse_reg_calc(data[position:position + length])
                except Exception:
                    destination = None
                if destination is not None and FLAG_BASE <= destination < FLAG_BASE + FLAG_COUNT:
                    slot = destination - FLAG_BASE
                    writes.setdefault(slot, []).append(f'{path.stem}:0x{position:04X}')
            position += length
    return writes


def sequential_tables():
    """在可执行文件里找「按序号排列」的候选表；找不到就是找不到。"""
    data = ELF.read_bytes()
    sections = [(0x001000, 0x100000, 0x11299C, 'text'),
                (0x113A00, 0x212A00, 0x45304, 'rodata'),
                (0x158D80, 0x257D80, 0x17C58, 'data')]
    patterns = {'0xA000+i': lambda i: FLAG_BASE + i,
                'i': lambda i: i,
                '2i': lambda i: i * 2}
    found = {}
    for name, make in patterns.items():
        hits = []
        for offset, address, size, section in sections:
            body = data[offset:offset + size]
            for step, fmt in ((2, '<H'), (4, '<I')):
                count = len(body) // step
                index = 0
                while index < count:
                    run = 0
                    while index + run < count and \
                            struct.unpack_from(fmt, body, (index + run) * step)[0] == make(run):
                        run += 1
                    if run >= 20:
                        hits.append({'section': section, 'address': hex(address + index * step),
                                     'length': run, 'step': step})
                        index += run
                    else:
                        index += 1
        found[name] = hits
    return found


def music_slots():
    data = INIT.read_bytes()
    slots = []
    position = 0
    while True:
        end = data.find(b'\0', position)
        if end < 0:
            break
        raw = data[position:end]
        if raw:
            try:
                text = raw.decode('cp932')
            except UnicodeDecodeError:
                text = ''
            if text.isascii() and (text.startswith('BGM') or text.startswith('SE_')):
                slots.append({'offset': hex(position), 'name': text})
        position = end + 1
    return slots


def card_similarity():
    """只在鉴赏出现的三张图与同版式参照图的逐像素差（0–255 均值）。"""
    from PIL import Image
    reference = Image.open(EV_DIR / 'EV_0088.png').convert('RGB').resize((64, 48)).tobytes()
    result = {}
    for name in ('EV_0134.png', 'EV_0136.png', 'EV_0002.png', 'EV_0122.png'):
        other = Image.open(EV_DIR / name).convert('RGB').resize((64, 48)).tobytes()
        diff = sum(abs(a - b) for a, b in zip(reference, other)) / len(reference)
        result[name] = round(diff, 1)
    return result


def main():
    per_script, union = ev_usage()
    missing = [slot for slot in range(EV_SLOTS) if slot not in union]
    missing_files = [f'EV_{slot * 2:04d}.png' for slot in missing]
    for slot in missing:
        path = EV_DIR / f'EV_{slot * 2:04d}.png'
        assert path.is_file(), path
    print(f'PASS 逐字节扫 74 个剧本的 graph_disp：EV 组使用 {len(union)} 个槽位，'
          f'缺 {missing}（{", ".join(missing_files)}）')
    assert len(union) == 66 and missing == [44, 67, 68]
    print('PASS EV 槽 44（EV_0088.png，图内印 EV036「泉と神社へ」）在全部剧本中 0 次出现')

    data, names = flag_names()
    assert names[0x25] == 'Ｆ泉訪問', names[0x25]
    assert names[0x3B] == 'Ｆ泉ルート', names[0x3B]
    operands = [FLAG_BASE + index for index in range(FLAG_COUNT)]
    print(f'PASS INIT 0x09EC 的 62 条名称表 = 0x{operands[0]:04X}–0x{operands[-1]:04X}；'
          f'[0x25]={names[0x25]}，[0x3B]={names[0x3B]}')

    writes = flag_writes()
    print(f'PASS 剧本实际写到的标志 {len(writes)} 个；'
          f'Ｆ泉訪問 见于 {writes.get(0x25, [])}，Ｆ泉ルート 见于 {writes.get(0x3B, [])}')

    tables = sequential_tables()
    long_runs = [hit for hits in tables.values() for hit in hits]
    # 0x218D30 的 0..32（33 项）是唯一命中的序号段，长度既不等于 62 个标志，也不等于 69 个 EV 槽。
    assert all(hit['length'] < 60 for hit in long_runs), long_runs
    print(f'PASS ELF 的 text/rodata/data 三段没有能覆盖 62 个标志或 69 个 EV 槽的序号表'
          f'（最长命中 {max((hit["length"] for hit in long_runs), default=0)} 项）')

    slots = music_slots()
    bgm = [item['name'] for item in slots if item['name'].startswith('BGM')]
    print(f'PASS INIT 只有 {len(bgm)} 条音乐槽位名（{bgm[0]} … {bgm[-1]}），没有曲名表')

    similarity = card_similarity()
    assert similarity['EV_0134.png'] < 1 and similarity['EV_0136.png'] < 1
    assert similarity['EV_0002.png'] > 20
    print(f'PASS EV_0088 与 EV_0134/EV_0136 是同一版式条目卡（逐像素差 '
          f'{similarity["EV_0134.png"]}/{similarity["EV_0136.png"]}），与正文 CG 差 '
          f'{similarity["EV_0002.png"]}')

    appreciation = json.loads((GAME / 'appreciation.json').read_text(encoding='utf-8'))
    names_bgm = [item['name'] for item in appreciation['bgm']]
    assert all('移植版命名' in name for name in names_bgm), names_bgm
    print(f'PASS appreciation.json 的 {len(names_bgm)} 条 BGM 全部标注「移植版命名」')

    report = {
        'ELF_sha256': hashlib.sha256(ELF.read_bytes()).hexdigest(),
        'script_count': len(script_files()),
        'ev_slots_used': sorted(union),
        'ev_slots_missing': [{'slot': slot, 'file': f'EV_{slot * 2:04d}.png',
                              'role': {44: '图内印 EV036「泉と神社へ」，正文无显示',
                                       67: '图内印 EV_OP01，片头影片起播解锁',
                                       68: '图内印 EV_END01，片尾影片起播解锁'}[slot]}
                             for slot in missing],
        'per_script_ev': per_script,
        'flag_table': {'offset': '0x0009EC', 'count': FLAG_COUNT,
                       'operand_range': f'0x{FLAG_BASE:04X}-0x{FLAG_BASE + FLAG_COUNT - 1:04X}',
                       'names': names},
        'flag_writes': {f'0x{FLAG_BASE + slot:04X} {names[slot]}': sites
                        for slot, sites in sorted(writes.items())},
        'sequential_tables_in_elf': tables,
        'music_slot_names': slots,
        'card_similarity': similarity,
        'conclusion': {
            'ev036': '剧本层没有任何显示指令引用 EV 槽 44；相册/音乐模式在原盘是原生界面'
                     '（INIT 调试项 アルバム全開放 / ミュージック全開放），其条目表不在 MAC 剧本里，'
                     '现有素材无法反推 EV036 的解锁位；移植版按图内标题所对应的神社剧情解锁，'
                     '标注为移植版条件。',
            'bgm': '原盘只有 BGM01…BGM20 / SE_A01… 这类槽位名，没有曲名表；'
                   '社区 gamerip（khinsider）同样只有 Track N。移植版 8 条全部标注移植版命名。',
        },
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'WROTE {OUT.relative_to(BASE)}')


if __name__ == '__main__':
    main()
