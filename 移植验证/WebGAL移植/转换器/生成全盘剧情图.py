"""Command-line entry point for the original MAC story graph."""
import argparse
import json
from pathlib import Path

from mac_story_graph import ROOT, trace
from mac_release import DISC_OPTIONS
from mac_story_wiring import emit_transitions, read_translations

DATA = Path(__file__).resolve().parents[1] / '数据'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--wiring', type=Path, help='另存已知选项与跨剧本接线片段')
    parser.add_argument('--translations', type=Path, default=DISC_OPTIONS)
    args = parser.parse_args()
    if args.output.exists() or (args.wiring and (args.wiring.exists() or args.wiring == args.output)):
        parser.error('输出路径已存在或重复')
    index = json.loads((DATA / '入口片段_扩展候选.json').read_text(encoding='utf-8'))
    checks = json.loads((ROOT / 'MAC_命令表/脚本验证.json').read_text(encoding='utf-8'))
    report = trace(index, checks, ROOT / '输出-保护边修复/MAC')
    with args.output.open('x', encoding='utf-8') as output:
        json.dump(report, output, ensure_ascii=False, separators=(',', ':'))
        output.write('\n')
    print(f"{len(report['reached_scripts'])} 个剧本，{report['choice_groups']} 组选项，"
          f"{len(report['reached_end_candidates'])} 个结束指令，{len(report['pending_controls'])} 处待查边界")
    if args.wiring:
        wiring = emit_transitions(report, read_translations(args.translations))
        with args.wiring.open('x', encoding='utf-8') as output:
            json.dump(wiring, output, ensure_ascii=False, indent=2)
            output.write('\n')
        print(f"已生成 {len(wiring['emitted'])} 处接线，待补 {len(wiring['missing'])} 处")


if __name__ == '__main__':
    main()
