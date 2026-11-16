"""把原剧本的一段指令编译成可共享的 WebGAL 场景，并输出阻塞分类报告。

用法（在 `移植验证/WebGAL移植` 下）：

    python -B 转换器/编译动态场景.py --script MAC_003.bin --start 0x34B8 \
        --scene 数据/动态场景_MAC003_0x34B8.txt --report 数据/动态场景编译报告_MAC003_0x34B8.json

    python -B 转换器/编译动态场景.py --script MAC_004.bin --start 0x0C --scan-only \
        --report 数据/动态场景编译报告_MAC004_0x0C.json

- `--scene` 写出可直接放进 WebGAL 场景目录的正文（拒绝覆盖已有文件）。
- `--report` 写出编译结果与阻塞分类；`--scan-only` 时只做静态分类扫描。
- 两者都不修改任何现有样片；被测区间不是原版完整轨迹，报告里保留源偏移。
"""
import argparse
import json
from pathlib import Path
import sys

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / '转换器'))
from mac_runtime_scene import collect_operands, compile_range, load_commands, scan_blockers


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--script', required=True)
    parser.add_argument('--start', required=True, type=lambda n: int(n, 0))
    parser.add_argument('--end', type=lambda n: int(n, 0))
    parser.add_argument('--words', nargs='*', type=lambda n: int(n, 0),
                        help='已跟踪的状态操作数；默认用 mac_runtime_scene.OPERANDS')
    parser.add_argument('--scene', type=Path)
    parser.add_argument('--report', type=Path)
    parser.add_argument('--scan-only', action='store_true')
    args = parser.parse_args()
    if not args.scene and not args.report:
        parser.error('至少需要 --scene 或 --report')
    for path in (args.scene, args.report):
        if path is not None and path.exists():
            raise FileExistsError(f'拒绝覆盖已有文件: {path}')
    words = tuple(args.words) if args.words else None

    if words is None:
        payload = {'scope': f'{args.script} 从 0x{args.start:X} 起编译'
                            + (f'至 0x{args.end:X}' if args.end is not None else ''),
                   'note': '区间由调用者指定；这不是原版完整轨迹。'
                           '跟踪操作数按区间实际引用推导，字/位共用地址会显式报错。',
                   'tracked_operands': 'derived'}
    else:
        payload = {'scope': f'{args.script} 从 0x{args.start:X} 起编译'
                            + (f'至 0x{args.end:X}' if args.end is not None else ''),
                   'note': '区间由调用者指定；这不是原版完整轨迹，状态写入只覆盖调用者给的操作数。',
                   'tracked_operands': [f'0x{w:04X}' for w in words]}
    if args.scan_only:
        payload['scan'] = scan_blockers(args.script, args.start, args.end, words)
    else:
        result = compile_range(args.script, args.start, args.end, words=words, strict=False)
        if words is None:
            payload['tracked_operands'] = [f'0x{w:04X}' for w in collect_operands(load_commands(args.script), args.start)]
        payload['compile'] = {
            'lines': len(result.lines),
            'labels': [f'0x{offset:X}' for offset in result.labels],
            'targets': sorted(f'0x{offset:X}' for offset in result.targets),
            'unresolved_targets': sorted(f'0x{offset:X}' for offset in result.unresolved_targets),
            'used_voices': len(result.used_voices),
            'ignored': result.ignored,
            'stop': result.stop.as_dict() if result.stop else None}
        payload['scan'] = scan_blockers(args.script, args.start, args.end, words)
        if args.scene:
            args.scene.parent.mkdir(parents=True, exist_ok=True)
            args.scene.write_text('\n'.join(result.lines) + '\n', encoding='utf-8')
            payload['scene_file'] = str(args.scene)
        stop = result.stop
        print('场景行:', len(result.lines), '语音:', len(result.used_voices),
              '停止:', f'{stop.script} 0x{stop.offset:X} {stop.name}' if stop and stop.offset is not None
              else (stop.reason if stop else '无'))
    scan = payload['scan']
    print('阻塞合计:', scan['blocker_total'], '类别:', [b['category'] for b in scan['blockers']])
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print('报告:', args.report)
    missing = [b['category'] for b in scan['blockers'] if not b['note']]
    if missing:
        print('缺少说明的类别:', missing, file=sys.stderr)
        raise SystemExit(1)


if __name__ == '__main__':
    main()
