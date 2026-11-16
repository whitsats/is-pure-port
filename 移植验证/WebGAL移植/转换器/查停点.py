"""按站点查停点：打印原盘字节、编译后的场景行与到达它的实跑记录。

用法（在 移植验证/WebGAL移植）：
    python -B 转换器/查停点.py MAC_056:0x2D88
    python -B 转换器/查停点.py --table          # 重建 数据/主线停点表.tsv
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
GRAPH = BASE / '数据/全盘剧情候选图.json'
BATCH = BASE / '数据/批量章节扫描_写入2.json'
RUN = BASE / '数据/主线实跑_全流程.json'
SCENES = BASE / '新游戏打盘版/public/game/scene'
TABLE = BASE / '数据/主线停点表.tsv'

RUN_COMMAND = ('node 浏览器测试环境/跑主线到终点.cjs --pick 0 '
               '--report 数据/主线实跑_全流程.json')


def load(path: Path):
    return json.loads(path.read_text(encoding='utf-8'))


def node_of(graph, site):
    for node in graph['nodes']:
        if node['id'] == site:
            return node
    return None


def scene_lines_for(site, graph):
    """该站点编译出的场景与边界行。"""
    script, offset = site.split(':')
    entry = f"{script.lower()}_0x{int(offset, 16):06x}.txt"
    path = SCENES / entry
    if not path.exists():
        return None, []
    lines = [line.rstrip() for line in path.read_text(encoding='utf-8').splitlines()
             if '本版边界' in line or line.startswith('end;')]
    return entry, lines


def describe(site):
    graph = load(GRAPH)
    node = node_of(graph, site)
    if node is None:
        print(f'候选图里没有 {site}')
        return 1
    entry, lines = scene_lines_for(site, graph)
    print(f'站点      {site}')
    print(f'剧本      {node["script"]}')
    print(f'偏移      0x{node["offset"]:X}')
    print(f'指令      {node["name"]}')
    print(f'原始字节  {node["raw_hex"]}')
    print(f'后继      {[edge["target"] for edge in node.get("edges", [])]}')
    print(f'场景      {entry or "（未生成独立场景）"}')
    for line in lines:
        print(f'  {line}')
    return 0


def table():
    graph = load(GRAPH)
    batch = load(BATCH)
    run = load(RUN) if RUN.exists() else {}
    rows = []

    ends = {}
    for blocker in batch.get('blockers', []):
        if blocker.get('category') != 'end':
            continue
        for item in blocker.get('items', []):
            ends.setdefault(item['stop'], []).append(item)

    for stop, items in sorted(ends.items()):
        node = node_of(graph, stop)
        entry, lines = scene_lines_for(items[0]['site'], graph)
        rows.append({
            '类别': 'end（离线结束指令）',
            '剧本': node['script'] if node else stop.split(':')[0],
            '偏移': f'0x{node["offset"]:X}' if node else stop.split(':')[1],
            '原始字节': (node.get('raw_hex') if node else '') or items[0].get('raw_hex', ''),
            '停因': '原版 end；结局演出与回标题未还原，7 条支线共用此终点',
            '入口数': len(items),
            '证据': f'{entry}：{lines[0] if lines else ""}',
            '复现命令': RUN_COMMAND,
        })

    stall = (run.get('runtime') or {}).get('stall')
    if stall:
        rows.append({
            '类别': 'stall（实跑无推进）',
            '剧本': stall.get('scene', ''),
            '偏移': '',
            '原始字节': '',
            '停因': stall.get('showText', ''),
            '入口数': 1,
            '证据': json.dumps(stall, ensure_ascii=False),
            '复现命令': RUN_COMMAND,
        })

    header = ['类别', '剧本', '偏移', '原始字节', '停因', '入口数', '证据', '复现命令']
    with TABLE.open('w', encoding='utf-8', newline='') as handle:
        handle.write('\t'.join(header) + '\n')
        for row in rows:
            handle.write('\t'.join(str(row[key]).replace('\t', ' ') for key in header) + '\n')
    print(f'写入 {TABLE}（{len(rows)} 行）')
    return 0


def main(argv):
    if not argv or argv[0] in {'-h', '--help'}:
        print(__doc__)
        return 0
    if argv[0] == '--table':
        return table()
    return describe(argv[0])


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
