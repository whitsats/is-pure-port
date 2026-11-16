"""按生成场景解释 setVar/jumpLabel/choose，复核结局路线的四条数值。

不依赖浏览器：直接读取 `新游戏打盘高清版/public/game/scene` 的 WebGAL 场景，
按与原剧本相同的 16 位写入和条件跳转执行。用途是从原盘分支计算代表结局的
数值，和浏览器实点选项的定点结果互相对照。

用法：
  python -B 验证/模拟数值路线.py --strategy first
  python -B 验证/模拟数值路线.py --strategy index:1 --from mac_056_0x00000c.txt
"""
from __future__ import annotations

import argparse
from functools import cache
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCENE_DIR = ROOT / '新游戏打盘高清版/public/game/scene'
VARS = ('mac_6026', 'mac_602a', 'mac_602b', 'mac_602c')


@cache
def scene_lines(scene):
    return (SCENE_DIR / scene).read_text(encoding='utf-8').splitlines()


def s16(value: int) -> int:
    value &= 0xFFFF
    return value - 0x10000 if value & 0x8000 else value


def eval_expr(expr: str, env: dict[str, int]) -> int:
    def repl(match: re.Match) -> str:
        name = match.group(0)
        return str(env.get(name, 0))
    text = re.sub(r'mac_[0-9a-zA-Z_]+', repl, expr.strip()).replace('&&', ' and ').replace('||', ' or ')
    if not re.fullmatch(r'[0-9a-zA-Z_+\-*/%() <>=!&|]+', text):
        raise ValueError(f'不支持的表达式 {expr!r} -> {text!r}')
    return int(eval(text, {'__builtins__': {}}, {}))


def eval_cond(cond: str, env: dict[str, int]) -> bool:
    cond = cond.strip()
    for op in ('!=', '==', '<=', '>=', '<', '>'):
        if op in cond:
            left, right = cond.split(op, 1)
            a, b = eval_expr(left, env), eval_expr(right, env)
            return {'!=': a != b, '==': a == b, '<=': a <= b, '>=': a >= b,
                    '<': a < b, '>': a > b}[op]
    return bool(eval_expr(cond, env))


def parse_choice(line: str):
    body = line[len('choose:'):].rstrip(';')
    options = []
    for part in body.split('|'):
        condition = None
        if '->' in part:
            condition, part = part.split('->', 1)
            condition = condition.strip()
            if condition.startswith('(') and condition.endswith(')'):
                condition = condition[1:-1]
        text, _, jump = part.partition(':')
        options.append({'text': text.strip(), 'jump': jump.strip(), 'condition': condition})
    return options


def choose_index(options, strategy, env):
    visible = [i for i, opt in enumerate(options)
               if opt['condition'] is None or eval_cond(opt['condition'], env)]
    if not visible:
        raise RuntimeError('没有可见选项')
    if strategy == 'first':
        return visible[0]
    if strategy == 'last':
        return visible[-1]
    if strategy.startswith('index:'):
        wanted = int(strategy.split(':', 1)[1])
        if wanted not in visible:
            raise RuntimeError(f'选项 {wanted} 不可见，可见 {visible}')
        return wanted
    raise ValueError(strategy)


def run(start: str, strategy: str, trace: bool, final_index=None, plan=None, stop=None, checkpoint=None):
    env = {name: 0 for name in VARS}
    env.update({'mac_6026': 20, 'mac_602a': 20, 'mac_602b': 20, 'mac_602c': 20})
    scene = start
    pc = 0
    steps = 0
    history = []
    while True:
        steps += 1
        if steps > 500000:
            raise RuntimeError('步数超限')
        lines = scene_lines(scene)
        if pc >= len(lines):
            raise RuntimeError(f'{scene} 到文件尾，没有 end/changeScene')
        line = lines[pc].strip()
        if checkpoint == (scene, pc):
            return env, history, scene
        if trace and (line.startswith('setVar:mac_602') or line.startswith('choose:')):
            print(f'{scene}:{pc + 1} {line[:160]} env={ {k: env[k] for k in VARS} }')
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
                    try:
                        pc = lines.index(f'label:{label.strip()};')
                    except ValueError as exc:
                        raise RuntimeError(f'{scene} 找不到 {label}') from exc
                continue
            pc += 1
            continue
        if line.startswith('label:'):
            pc += 1
            continue
        if line.startswith('choose:'):
            options = parse_choice(line)
            index = choose_index(options, strategy, env)
            if plan and scene in plan:
                index = plan[scene]
            if final_index is not None and scene == 'mac_056_0x00000c.txt':
                index = final_index
            opt = options[index]
            history.append(opt['text'])
            print(f'CHOOSE {scene}:{pc + 1} -> {opt["text"]}')
            if stop and stop == f'{scene}:{pc + 1}':
                print('STOP', {k: env[k] for k in VARS}, 'OPTIONS', [o['text'] for o in options])
                return env, history
            target = f'label:{opt["jump"]} -next;'
            try:
                pc = lines.index(target)
            except ValueError:
                pc += 1
            continue
        if line.startswith('changeScene:'):
            target = line[len('changeScene:'):].rstrip(';').strip()
            if line.endswith(';') and ' -when=' in target:
                target, _, condition = target.partition(' -when=')
                if not eval_cond(condition, env):
                    pc += 1
                    continue
            scene = target
            pc = 0
            continue
        if line.startswith('end'):
            print(f'END {scene}:{pc + 1} steps={steps}')
            break
        pc += 1
    if checkpoint is not None:
        raise ValueError(f'路线未经过 {checkpoint[0]}:{checkpoint[1] + 1}')
    print('FINAL', {k: env[k] for k in VARS})
    print('ROUTE', ' / '.join(history))
    return env, history, scene


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--strategy', default='first')
    parser.add_argument('--from', dest='start', default='mac_000_0x00000c.txt')
    parser.add_argument('--trace', action='store_true')
    parser.add_argument('--final-index', type=int, default=None)
    parser.add_argument('--choice', action='append', default=[])
    parser.add_argument('--stop', default=None)
    parser.add_argument('--checkpoint', help='输出指定场景行执行前的状态，格式为 场景文件:一基行号')
    args = parser.parse_args()
    plan = dict(item.split('=', 1) for item in args.choice)
    plan = {k: int(v) for k, v in plan.items()}
    if args.checkpoint:
        import contextlib
        import io

        scene, _, line = args.checkpoint.rpartition(':')
        position = (scene, int(line) - 1)
        with contextlib.redirect_stdout(io.StringIO()):
            variables, history, reached = run(args.start, args.strategy, args.trace, args.final_index,
                                              plan, args.stop, checkpoint=position)
        if reached != scene:
            raise ValueError(f'路线未经过 {args.checkpoint}')
        print(json.dumps({'scene': scene, 'sourceLine': position[1], 'GameVar': variables, 'choices': history}))
    else:
        run(args.start, args.strategy, args.trace, args.final_index, plan, args.stop)
