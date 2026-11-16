"""Generate the WebGAL flowcharts from the scenes shipped with the current disc build."""
import argparse
from collections import Counter, deque
from graphlib import CycleError, TopologicalSorter
import hashlib
import json
from pathlib import Path
import re

BASE = Path(__file__).resolve().parents[1]
DATA = BASE / '数据'
GAME = BASE / '新游戏打盘高清版/public/game'
REPORT = DATA / '全盘高清剧情构建_EV修复与音频写入_5.json'
CONTROL = re.compile(r'^(jumpLabel|changeScene):([^;]+);$')
CHAPTER = re.compile(r'^mac_(\d+)_')


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def chapter_title(index, records):
    record = records[index]
    title = record.get('title') or record.get('first_text') or f'MAC_{index:03d}'
    return f'第{index + 1:02d}话 {title}'


def node(node_id, label, location, kind, *, root=False):
    scene, line = location
    data = {'label': label, 'sceneName': scene}
    if line is not None:
        data['sourceLine'] = line
    if root:
        data['isRoot'] = True
    return {'id': node_id, 'type': kind, 'position': {'x': 0, 'y': 0}, 'data': data}


def edge(source, target):
    return {'id': f'{source}-{target}', 'source': source, 'target': target}


def read_choices(line):
    body, _, _ = line.removeprefix('choose:').removesuffix(';').partition(' -')
    for option in re.split(r'(?<!\\)\|', body):
        match = re.match(r'^(?:\(.*?\)|\[.*?\])+->', option)
        if match:
            option = option[match.end():]
        text, target = re.split(r'(?<!\\):', option, maxsplit=1)
        yield text.replace(r'\:', ':').strip(), target.strip()


def build_scene_graph(scene_files, scene_dir):
    lines_by_scene = {
        name: (scene_dir / name).read_text(encoding='utf-8').splitlines() for name in scene_files
    }
    choices = {}
    successors = {}
    for name, lines in lines_by_scene.items():
        labels = {line.removeprefix('label:').split(' -', 1)[0].removesuffix(';'): index
                  for index, line in enumerate(lines) if line.startswith('label:')}
        for index, line in enumerate(lines):
            here = (name, index)
            fallthrough = [(name, index + 1)] if index + 1 < len(lines) else []
            if line.startswith('choose:'):
                options = []
                for text, target in read_choices(line):
                    if target.endswith('.txt'):
                        location = (target, 0)
                    else:
                        location = (name, labels[target])
                    options.append((text, location))
                choices[here] = options
                successors[here] = []
                continue
            if line == 'end;':
                successors[here] = []
                continue
            control = CONTROL.fullmatch(line)
            if control is None:
                successors[here] = fallthrough
                continue
            command, arguments = control.groups()
            target, _, flags = arguments.partition(' -')
            destination = (name, labels[target]) if command == 'jumpLabel' else (target, 0)
            successors[here] = [destination, *fallthrough] if 'when=' in flags else [destination]
    return lines_by_scene, choices, successors


def distances_from(start, successors):
    distances = {start: 0}
    pending = deque([start])
    while pending:
        here = pending.popleft()
        for after in successors.get(here, ()):
            if after in distances:
                continue
            distances[after] = distances[here] + 1
            pending.append(after)
    return distances


def unavoidable(start, target, successors):
    """Check that a path cannot stop or loop before reaching the proposed merge."""
    before = {}
    pending = [start]
    while pending:
        here = pending.pop()
        if here == target or here in before:
            continue
        after = successors.get(here, ())
        if not after:
            return False
        before[here] = [point for point in after if point != target]
        pending.extend(before[here])
    try:
        tuple(TopologicalSorter(before).static_order())
    except CycleError:
        return False
    return True


def merge_target(options, successors, junctions):
    starts = [location for _, location in options]
    distances = [distances_from(start, successors) for start in starts]
    common = set.intersection(*(set(mapping) for mapping in distances)) & junctions.union(starts)
    ranked = sorted(common, key=lambda loc: (max(m[loc] for m in distances), sum(m[loc] for m in distances), loc))
    for location in ranked:
        if all(unavoidable(start, location, successors) for start in starts):
            return location
    return None


def build(report_path=REPORT, game=GAME):
    titles = read_json(DATA / '章节标题静态表.json')['records']
    report = read_json(report_path)
    scene_files = sorted({entry['scene'] for chapter in report['chapters'] for entry in chapter['scenes'].values()})
    programs, choices, successors = build_scene_graph(scene_files, game / 'scene')
    incoming = Counter(after for targets in successors.values() for after in targets)
    junctions = {location for location, count in incoming.items() if count > 1}

    chapters = [node(f'chapter_{i:03d}', chapter_title(i, titles), (f'mac_{i:03d}_0x00000c.txt', None),
                     'root' if i == 0 else 'chapter', root=i == 0) for i in range(len(titles))]
    chapter_edges = [edge(a['id'], b['id']) for a, b in zip(chapters, chapters[1:])]
    endings = []
    for name in scene_files:
        for index, line in enumerate(programs[name]):
            if line == 'end;':
                ending_id = f'ending_{Path(name).stem}'
                endings.append(node(ending_id, f'结局 {len(endings) + 1}', (name, index), 'ending'))
                chapter_edges.append(edge(chapters[-1]['id'], ending_id))
    charts = [{'id': 'main', 'name': '《I’s Pure》主线', 'type': 'main',
               'nodes': chapters + endings, 'edges': chapter_edges}]

    per_chapter = Counter()
    for location, options in sorted(choices.items()):
        name, _ = location
        chapter = int(CHAPTER.match(name).group(1))
        per_chapter[chapter] += 1
        number = per_chapter[chapter]
        chart_id = 'mac_001_branch' if (chapter, number) == (1, 1) else f'mac_{chapter:03d}_choice_{number:02d}'
        choice_node = node('choice', '选择', location, 'root', root=True)
        outcomes = [node(f'option_{i}', label, target, 'branch') for i, (label, target) in enumerate(options)]
        nodes = [choice_node, *outcomes]
        edges = [edge('choice', option['id']) for option in outcomes]
        merge = merge_target(options, successors, junctions)
        if merge is not None:
            merge_name = '汇合'
            if merge[1] == 0:
                i = int(CHAPTER.match(merge[0]).group(1))
                if i != chapter:
                    merge_name = chapter_title(i, titles)
            nodes.append(node('merge', merge_name, merge, 'event'))
            edges.extend(edge(option['id'], 'merge') for option in outcomes)
        charts.append({'id': chart_id, 'name': f'第{chapter + 1:02d}话 · 选项 {number}', 'type': 'character',
                       'revealNodeId': 'choice', 'nodes': nodes, 'edges': edges})
    for chart in charts:
        for item in chart['nodes']:
            data = item['data']
            scene = data['sceneName']
            if scene not in programs or not 0 <= data.get('sourceLine', 0) < len(programs[scene]):
                raise ValueError(f'流程图指向无效语句 {chart["id"]}/{item["id"]}: {data}')
    revision = hashlib.sha256(json.dumps(programs, ensure_ascii=False).encode('utf-8')).hexdigest()[:16]
    return {'snapshotRevision': revision, 'flowcharts': charts}


def write_flowcharts(path, report_path=REPORT, game=GAME):
    data = build(report_path, game)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return data


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=GAME / 'flowchart.json')
    parser.add_argument('--report', type=Path, default=REPORT)
    args = parser.parse_args()
    data = write_flowcharts(args.output, args.report)
    charts = data['flowcharts'][1:]
    print(f'流程图 {len(charts)} 组选项、{sum(len(g["nodes"]) - 1 - any(n["id"] == "merge" for n in g["nodes"]) for g in charts)} 个选项结果、'
          f'{sum(any(n["id"] == "merge" for n in g["nodes"]) for g in charts)} 处汇合')


if __name__ == '__main__':
    main()
