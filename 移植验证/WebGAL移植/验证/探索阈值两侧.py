"""穷举到达 mac_003 阈值点的选项组合，找出 602C<21 成立与不成立两侧。

复用 `模拟数值路线.py` 的条件/选项解析，不写任何变量；只枚举真实可见选项。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from 模拟数值路线 import SCENE_DIR, eval_cond, eval_expr, parse_choice, s16, VARS

TARGET = ('mac_003_0x00000c.txt', 886)
found = []
seen = set()


def dfs(scene, pc, env, history, depth=0):
    if depth > 30:
        return
    path = SCENE_DIR / scene
    lines = path.read_text(encoding='utf-8').splitlines()
    while 0 <= pc < len(lines):
        line = lines[pc].strip()
        if scene == TARGET[0] and pc + 1 == TARGET[1]:
            found.append((dict(env), history[:], [o['text'] for o in parse_choice(line)]))
            return
        if line.startswith('setVar:'):
            body = line[len('setVar:'):].rstrip(';').removesuffix(' -next')
            name, expr = body.split('=', 1)
            env[name.strip()] = s16(eval_expr(expr, env))
            pc += 1
            continue
        if line.startswith('jumpLabel:'):
            body = line[len('jumpLabel:'):].rstrip(';')
            label, _, condition = body.partition(' -when=')
            if not condition or eval_cond(condition, env):
                target = f'label:{label.strip()} -next;'
                try:
                    pc = lines.index(target)
                except ValueError:
                    pc = lines.index(f'label:{label.strip()};')
                continue
            pc += 1
            continue
        if line.startswith('label:'):
            pc += 1
            continue
        if line.startswith('choose:'):
            for index, opt in enumerate(parse_choice(line)):
                if opt['condition'] is not None and not eval_cond(opt['condition'], env):
                    continue
                target = f'label:{opt["jump"]} -next;'
                try:
                    next_pc = lines.index(target)
                except ValueError:
                    next_pc = pc + 1
                key = (scene, next_pc, tuple(sorted(env.items())))
                if key in seen:
                    continue
                seen.add(key)
                dfs(scene, next_pc, dict(env), history + [f'{scene}:{opt["text"]}'], depth + 1)
            return
        if line.startswith('changeScene:'):
            target = line[len('changeScene:'):].rstrip(';').strip()
            if line.endswith(';') and ' -when=' in target:
                target, _, condition = target.partition(' -when=')
                if not eval_cond(condition, env):
                    pc += 1
                    continue
            scene, pc = target, 0
            lines = (SCENE_DIR / scene).read_text(encoding='utf-8').splitlines()
            continue
        if line.startswith('end'):
            return
        pc += 1


dfs('mac_000_0x00000c.txt', 0, {k: 20 for k in VARS}, [])
print('到达阈值点组合数', len(found))
for env, history, options in found:
    side = '602C<21 成立' if env['mac_602c'] < 21 else '602C<21 不成立'
    print(side, {k: env[k] for k in VARS}, '选项', options, '路线', ' / '.join(history[-8:]))
