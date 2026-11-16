"""准备分支扫描用的样片副本：每个 worker 一份场景目录，音频/背景用目录联接指回现行样片。

用法（在 移植验证/WebGAL移植）：
    python -B 转换器/准备分支扫描.py --workers 2
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
SAMPLE = BASE / '新游戏打盘版/public/game'
ROOT = BASE / 'scan'   # ASCII 路径：Vite 对中文路径做 URI 解码会报 URI malformed
LINKS = ('vocal', 'background', 'bgm', 'figure', 'animation', 'template')


def junction(link: Path, target: Path) -> None:
    if link.exists():
        return
    script = (f"New-Item -ItemType Junction -Path '{link}' -Target '{target}' | Out-Null")
    subprocess.run(['powershell', '-NoProfile', '-Command', script], check=True)


def prepare(workers: int) -> None:
    for index in range(workers):
        game = ROOT / f'w{index}' / 'public/game'
        if (game / 'scene').exists():
            shutil.rmtree(game / 'scene')
        game.mkdir(parents=True, exist_ok=True)
        shutil.copytree(SAMPLE / 'scene', game / 'scene')
        shutil.copy2(SAMPLE / 'config.txt', game / 'config.txt')
        for name in LINKS:
            junction(game / name, SAMPLE / name)
        print(f'w{index}: {len(list((game / "scene").glob("*.txt")))} 个场景')


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--workers', type=int, default=2)
    args = parser.parse_args()
    prepare(args.workers)


if __name__ == '__main__':
    main()
