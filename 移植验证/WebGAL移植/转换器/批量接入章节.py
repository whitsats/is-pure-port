"""一次编译从指定站点起所有可达章节，输出统一的停点表。

与逐章生成器不同，这里沿 `数据/全盘主线接线_打盘版.json` 的跨剧本目标自动
发现章节入口，先批量核验这些章节实际引用的语音，再对每章调用
`compile_chapter`，把目标场景、语音和状态变量在同一次运行里核对完，并把
仍未核实的指令按「剧本 + 偏移 + 原字节 + 停点」汇总成一张表。

用法（在 `移植验证/WebGAL移植` 下）：

    python -B 转换器/批量接入章节.py --from MAC_007:0x4314 \
        --report 数据/批量章节扫描.json --verify-voices
    python -B 转换器/批量接入章节.py --from MAC_007:0x4314 \
        --report 数据/批量章节扫描.json --verify-voices --write 新游戏打盘版/public

`--verify-voices` 会用 `转换器/校验语音样本.py` 一次性核对缺失的语音编号并
追加清单；`--write` 把场景写进样片、补齐语音并初始化新增状态字。
报告拒绝覆盖。特效只使用已核实的参数（类型 1 / 类型 3 / 已记录的调色板），
其余参数作为待核项留在报告里，不跳过。
"""
import argparse
import json
import re
import shutil
import subprocess
import sys
from collections import deque
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE / '转换器'))
from mac_chapter_scene import compile_chapter
from mac_disc_graphics import commands_for, deploy_asset, source_sizes
from mac_release import DISC_WIRING, deploy_ending_video, ending_video_filename
from mac_runtime_scene import collect_operands, load_commands, load_rows
from mac_story_wiring import scene_name
from 生成新游戏MAC004样片 import check_layout
from 验证新游戏首选项 import DATA, VOICE_DIR, verified_voices

DEFAULT_MANIFESTS = ('语音校验_MAC007_语音1391至1723.json',
                     '语音校验_MAC008至MAC009_语音新增.json',
                     '语音校验_MAC010开篇_语音1851至1915.json')


def parse_site(text):
    script, offset = text.split(':')
    return (script if script.endswith('.bin') else f'{script}.bin'), int(offset, 0)


def site_name(script, offset):
    return f'{script.removesuffix(".bin")}:0x{offset:X}'


def node_of_scene(name):
    match = re.fullmatch(r'mac_(\d+)_0x([0-9a-f]+)\.txt', name)
    return f'MAC_{match.group(1)}:0x{int(match.group(2), 16):X}' if match else None


def discover(nodes, start_site):
    """遍历整张候选图，按第一次跨剧本进入的顺序收集章节入口。

    跨剧本边之前可能隔着很多同剧本节点，所以不能只看跨剧本边。
    """
    entries, order, seen = {}, [], {start_site}
    pending = deque([start_site])
    while pending:
        site = pending.popleft()
        node = nodes.get(site)
        if node is None:
            continue
        for edge in node['edges']:
            target = edge['target']
            if target in seen or edge.get('unresolved'):
                continue
            seen.add(target)
            if edge['kind'] == 'cross_script':
                script, offset = parse_site(target)
                if script not in entries:
                    entries[script] = offset
                    order.append(script)
            pending.append(target)
    return [(script, entries[script]) for script in order]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--from', dest='start', required=True, help='起始站点，例如 MAC_007:0x4314')
    parser.add_argument('--report', required=True, type=Path)
    parser.add_argument('--write', type=Path, help='把场景写进该样片的 public 目录')
    parser.add_argument('--manifests', nargs='*', default=list(DEFAULT_MANIFESTS),
                        help='已核验的语音清单（默认沿用本轮三份）')
    parser.add_argument('--verify-voices', action='store_true',
                        help='用 校验语音样本.py 一次性核对缺失语音并追加清单')
    parser.add_argument('--no-effects', action='store_true', help='不启用已核实的特效适配（用于对照）')
    parser.add_argument('--hd', action='store_true', help='按原盘图形记录接入高清母版')
    parser.add_argument('--new-game', action='store_true', help='同时编译 --from 入口并接到开始游戏')
    parser.add_argument('--allow-blockers', action='store_true',
                        help='保留已记录的转换停点/缺语音，仅写入其余已编译场景（用于已有样片的定点修复）')
    args = parser.parse_args()
    if args.report.exists():
        raise FileExistsError(f'拒绝覆盖已有报告: {args.report}')

    graph = json.loads((DATA / '全盘剧情候选图.json').read_text(encoding='utf-8'))
    wiring = json.loads(DISC_WIRING.read_text(encoding='utf-8'))['emitted']
    nodes = {node['id']: node for node in graph['nodes']}
    manifests = list(args.manifests)
    start_script, start_offset = parse_site(args.start)
    if site_name(start_script, start_offset) not in nodes:
        raise ValueError(f'候选图里没有站点: {args.start}')
    chapters = discover(nodes, site_name(start_script, start_offset))
    if args.new_game:
        chapters.insert(0, (start_script, start_offset))
    if not chapters:
        raise ValueError('起始站点之后没有跨剧本目标')

    # 先按剧本取证语音，再一次性校验缺失编号。
    required, rows_by_script = {}, {}
    for script, _ in chapters:
        rows_by_script[script] = load_rows(script)
        required[script] = {int(row['语音号']) for row in rows_by_script[script].values()
                            if int(row['语音号']) >= 0}
    voices = verified_voices(tuple(manifests))
    missing = sorted(set().union(*required.values()) - voices.keys())
    verified_report = None
    if missing and args.verify_voices:
        name = f'语音校验_批量章节_语音{missing[0]}至{missing[-1]}.json'
        target = DATA / name
        if target.exists():
            raise FileExistsError(f'语音清单已存在，请直接把它加入 --manifests: {target}')
        subprocess.run([sys.executable, '-B', str(BASE / '转换器/校验语音样本.py'),
                        '--output', str(target), *map(str, missing)], check=True)
        manifests.append(name)
        voices = verified_voices(tuple(manifests))
        missing = sorted(set().union(*required.values()) - voices.keys())
        verified_report = name

    # 章节编译
    scenes, failures, chapter_reports = {}, [], []
    sizes = source_sizes() if args.hd else {}
    graphics_assets = set()
    linked = {edge['target'] for node in graph['nodes'] for edge in node['edges']
              if edge['kind'] == 'cross_script' and not edge.get('unresolved')}
    for script, entry in chapters:
        report = {'site': site_name(script, entry), 'scenes': {}}
        try:
            commands = load_commands(script)
            conditions = {int(option['condition']['raw'], 16) for node in graph['nodes']
                          if node['script'] == script for option in node.get('options', [])
                          if option['condition']['kind'] != 'value'}
            words = tuple(sorted(set(conditions) | set(collect_operands(commands, entry))))
            check_layout(words)
            report['words'] = [f'0x{word:04X}' for word in words]
            graphics = None
            if args.hd:
                source_commands = [command for command in commands if site_name(script, command['offset']) in nodes]
                graphics, assets = commands_for(script, source_commands, sizes)
                graphics_assets.update(assets)
            result = compile_chapter(script, entry, graph, wiring, words, rows_by_script[script], voices,
                                     screen_effects=not args.no_effects,
                                     particle_effects=not args.no_effects,
                                     linked_targets=linked, graphics=graphics)
        except (ValueError, KeyError) as error:
            failures.append({'script': script, 'entry': f'0x{entry:X}', 'reason': str(error)})
            chapter_reports.append(report)
            continue
        for name, (piece, tail) in result.items():
            site = site_name(piece.script, piece.start)
            scenes[site] = (piece, tail, scene_name(site))
            stop = piece.stop.as_dict() if piece.stop else None
            wired = stop is not None and stop['category'] in ('choice', 'cross_script') and any(
                line.startswith(('changeScene:', 'choose:')) for line in tail)
            wired = wired or (stop is not None and stop['name'] == 'end' and tail == ['end;'])
            report['scenes'][site] = {
                'scene': scene_name(site), 'lines': len(piece.lines), 'voices': len(piece.used_voices),
                'stop': stop, 'wired': wired,
                'ignored': [record for record in piece.ignored if record['category'] != 'pass_through']}
            target = next((line.split(':', 1)[1].rstrip(';') for line in tail
                           if line.startswith('changeScene:')), None)
            if target:
                following = nodes.get(node_of_scene(target))
                if following is not None and following['script'] != script:
                    report.setdefault('next', [])
                    if following['id'] not in report['next']:
                        report['next'].append(following['id'])
        chapter_reports.append(report)

    # 目标场景与语音核对
    generated = {name for _, _, name in scenes.values()}
    on_disk = {path.name for path in (args.write / 'game/scene').glob('*.txt')} if args.write else set()
    targets = {line.split(':', 1)[1].rstrip(';') for _, tail, _ in scenes.values()
               for line in tail if line.startswith('changeScene:')}
    missing_scenes = sorted(name for name in targets if name not in generated | on_disk) if args.write else []
    used = {number for piece, _, _ in scenes.values() for number in piece.used_voices}

    # 待核指令：跨章接续算已接线，其余按类别留剧本、偏移、原字节与停点
    blockers = {}
    for chapter in chapter_reports:
        for site, info in chapter.get('scenes', {}).items():
            stop = info['stop']
            if not stop or info['wired'] or stop['category'] == 'range_end':
                continue
            entry = blockers.setdefault(stop['category'], {'category': stop['category'], 'count': 0, 'items': []})
            entry['count'] += 1
            entry['items'].append({'site': site, 'stop': f"{stop['script']}:0x{stop['offset']:X}",
                                   'name': stop['name'], 'raw_hex': stop['raw_hex'],
                                   'detail': stop['reason']})
    report = {
        'scope': f'从 {args.start} 自动发现并编译可达章节；语音、目标场景与状态变量在同一轮核对。',
        'start': args.start,
        'effects': not args.no_effects,
        'voice_manifests': manifests,
        'verified_voices': verified_report,
        'chapters': chapter_reports,
        'scene_count': len(scenes),
        'used_voices': len(used),
        'missing_voices': missing,
        'missing_scenes': missing_scenes,
        'blockers': [blockers[key] for key in sorted(blockers)],
        'failures': failures,
        'graphics_assets': [dest for _, dest in sorted(graphics_assets)],
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    print(f'章节 {len(chapter_reports)}，场景 {len(scenes)}，语音 {len(used)}')
    for chapter in chapter_reports:
        stops = {}
        for info in chapter.get('scenes', {}).values():
            if info['stop'] and not info['wired']:
                stops[info['stop']['category']] = stops.get(info['stop']['category'], 0) + 1
        print(f"  {chapter['site']:<16} 场景 {len(chapter.get('scenes', {})):>3}  待核 {stops or '无'}")
    for entry in report['blockers']:
        print(f"  {entry['category']:<14} {entry['count']:>3}")
    if missing:
        print('缺语音:', len(missing), f'（{missing[0]}…{missing[-1]}）')
    if verified_report:
        print('新增语音清单:', verified_report)
    if failures:
        print('无法编译的章节:', failures)
    print('缺场景:', missing_scenes[:8])
    print('报告:', args.report)

    if args.write:
        if (failures or missing or missing_scenes) and not args.allow_blockers:
            raise ValueError('章节、场景或语音核对失败，保留现有样片；详情见报告')
        if args.new_game and blockers and not args.allow_blockers:
            raise ValueError('新游戏入口尚有转换停点，保留现行剧情；详情见报告')
        if not args.write.is_dir():
            raise FileNotFoundError(args.write)
        ending_command = f'playVideo:{ending_video_filename(hd=args.hd)}'
        if any(line.startswith((ending_command + ';', ending_command + ' '))
               for piece, _, _ in scenes.values() for line in piece.lines):
            deploy_ending_video(args.write, hd=args.hd)
        for asset, filename in graphics_assets:
            target = args.write / 'game' / filename
            deploy_asset(asset, target)
        scene_dir = args.write / 'game/scene'
        for _, (piece, tail, name) in scenes.items():
            (scene_dir / name).write_text('\n'.join([*piece.lines, *tail]) + '\n', encoding='utf-8')
        start_file = scene_dir / 'start.txt'
        start_text = start_file.read_text(encoding='utf-8')
        initialized = {int(value, 16) for value in
                       re.findall(r'^setVar:mac_([0-9a-f]{4})=0 -next;$', start_text, re.M)}
        extra = sorted({word for chapter in chapter_reports for word in
                        (int(item, 16) for item in chapter.get('words', []))} - initialized)
        if args.new_game:
            all_words = sorted(initialized | set(extra))
            opening = [f'setVar:mac_{word:04x}=0 -next;' for word in all_words]
            opening.extend(['setVar:mac_effect_0_phase=0 -next;', 'setVar:mac_effect_2_phase=0 -next;',
                            f'changeScene:{scene_name(site_name(start_script, start_offset))};'])
            start_file.write_text('\n'.join(opening) + '\n', encoding='utf-8')
        elif extra:
            start_file.write_text(''.join(f'setVar:mac_{word:04x}=0 -next;\n' for word in extra) + start_text,
                                  encoding='utf-8')
        copied = []
        for number in sorted(used):
            wav = f'VOICE_{number:05}.wav'
            target = args.write / 'game/vocal' / wav
            if not target.exists():
                shutil.copy2(VOICE_DIR / wav, target)
                copied.append(wav)
        flowchart = args.write / 'game/flowchart.json'
        if args.hd and args.new_game and flowchart.exists():
            from 生成流程图 import write_flowcharts

            write_flowcharts(flowchart, args.report, args.write / 'game')
        print('已写入场景', len(scenes), '新增状态字', [f'0x{word:04X}' for word in extra],
              '复制语音', len(copied))


if __name__ == '__main__':
    main()
