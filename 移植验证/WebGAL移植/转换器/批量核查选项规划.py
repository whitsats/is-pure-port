"""以静态清单遍历已识别 0x72 选项，按全零状态评估，结果仅供覆盖核查。"""
import argparse
import csv
import json
from pathlib import Path

from mac_choice import plan_choice
from mac_reader import ROOT, load_table
from mac_state import State


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    checks = json.loads((ROOT / 'MAC_命令表/脚本验证.json').read_text(encoding='utf-8'))
    with (ROOT / 'MAC_命令表/选项分支静态映射.tsv').open(encoding='utf-8-sig', newline='') as f:
        rows = list(csv.DictReader(f, delimiter='\t'))
    groups = {}
    for row in rows:
        groups.setdefault((row['文件'], int(row['选项指令偏移'], 16)), []).append(row)
    table = load_table()
    plans, failures = [], []
    for (filename, offset), expected in sorted(groups.items()):
        try:
            info = checks[filename]
            data = (ROOT / '输出-保护边修复/MAC' / filename).read_bytes()
            plan = plan_choice(data, info['boundary'], info['text_start'], offset, table, State())
            targets = [(o['index'], o['target']) for o in plan['options']]
            expected_targets = [(int(r['假设返回值']), int(r['静态跳转目标'], 16)) for r in expected]
            if targets != expected_targets:
                raise ValueError('原始表序号或目标与清单不符')
            plans.append({'script': filename, **plan})
        except (ValueError, KeyError, OSError) as exc:
            failures.append({'script': filename, 'offset': f'0x{offset:06X}', 'reason': str(exc)})
    result = {'scope': '按全零状态对已识别模式做批量结构核查；不是实际剧情状态或通关验证。',
              'groups_in_manifest': len(groups), 'options_in_manifest': len(rows),
              'planned_groups': len(plans), 'planned_options': sum(len(p['options']) for p in plans),
              'failures': failures, 'plans': plans}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
        f.write('\n')
    print(f"groups {len(plans)}/{len(groups)}, options {result['planned_options']}/{len(rows)}, failures {len(failures)}")
    print('Output:', args.output)


if __name__ == '__main__':
    main()
