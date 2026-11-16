"""把某段脚本范围内的指令连同原字节导出，便于和生成的场景逐条对照。"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mac_reader  # noqa: F401,E402

BASE = Path(__file__).resolve().parents[1]


def parse_segment(text):
    script, start, end = text.rsplit(':', 2)
    return script, int(start, 0), int(end, 0)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--script')
    parser.add_argument('--start', type=lambda v: int(v, 0))
    parser.add_argument('--end', type=lambda v: int(v, 0))
    parser.add_argument('--segment', action='append', type=parse_segment, metavar='SCRIPT:START:END',
                        help='可重复；跨剧本时逐段导出，脚本名含扩展名')
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    segments = args.segment or []
    if not segments:
        if None in (args.script, args.start, args.end):
            parser.error('需要 --script/--start/--end，或至少一个 --segment')
        segments = [(args.script, args.start, args.end)]
    data = json.loads((BASE / '数据/入口片段.json').read_text(encoding='utf-8'))
    fragments = {s['file']: s for s in data['scripts']}
    blocks, all_commands = [], []
    for script, start, end in segments:
        fragment = fragments.get(script)
        if fragment is None:
            raise ValueError(f'剧本未包含在入口片段中: {script}')
        picked = [{'offset': f'0x{c["offset"]:04X}', 'name': c['name'], 'raw_hex': c['raw_hex']}
                  for c in fragment['commands'] if start <= c['offset'] < end]
        if not picked:
            raise ValueError(f'范围内没有指令: {script} 0x{start:X}–0x{end:X}')
        blocks.append({'script': script, 'start': f'0x{start:04X}', 'end': f'0x{end:04X}',
                       'commands': picked})
        all_commands.extend({'script': script, **c} for c in picked)
    if len(blocks) == 1:
        payload = {'script': blocks[0]['script'], 'start': blocks[0]['start'], 'end': blocks[0]['end'],
                   'source': '数据/入口片段.json（按已知长度线性读取，不代表完整控制流）',
                   'commands': blocks[0]['commands']}
    else:
        payload = {'source': '数据/入口片段.json（按已知长度线性读取，不代表完整控制流）',
                   'segments': blocks, 'commands': all_commands}
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'输出 {len(all_commands)} 条指令（{len(blocks)} 段）: {args.output}')


if __name__ == '__main__':
    main()
