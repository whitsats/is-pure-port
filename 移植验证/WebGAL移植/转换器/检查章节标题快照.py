"""关联用户已有快照中的 0x17 状态与 title_disp 标题表。"""
import argparse
import json
from pathlib import Path

from mac_state_snapshot import load_snapshot
from mac_title_snapshot import inspect_title, invert_author_table


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--savestate', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--operand', type=lambda x: int(x, 0), default=1)
    args = p.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    state = load_snapshot(args.savestate)
    inverse = invert_author_table()
    before = inspect_title(state.memory, state.gp, inverse)
    effect = state.apply_reg17(bytes([9, 0x17, args.operand & 255, args.operand >> 8, 0, 0, 0, 0]))
    after = inspect_title(state.memory, state.gp, inverse)
    result = {'savestate_sha256': state.snapshot_sha256, 'before': before,
              'hypothetical_reg17': effect, 'after': after,
              'scope': '在现有存档内存副本上假设执行；不是原游戏同一场景的运行前后录制。'}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
        f.write('\n')
    print('存档中当前标题候选:', before['title'], '假设编号', args.operand, '后的标题候选:', after['title'])
    print('输出:', args.output)


if __name__ == '__main__':
    main()
