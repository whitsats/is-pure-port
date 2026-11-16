"""复核两条代表结局的最终四值。

路线由 `模拟数值路线.py` 解释生成场景得到；所有选择都来自真实可见选项。
- 全选第一项：走到 mac_056_0x002d30.txt，四值 35/26/20/25。
- 全选最后一项、最终章选「伊织的事」：走到 mac_056_0x0024f8.txt，四值 15/17/24/21。
"""
from __future__ import annotations

import contextlib
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from 模拟数值路线 import run

ROOT = Path(__file__).resolve().parents[1]
CASES = [
    {'name': '全选第一项', 'strategy': 'first', 'final_index': None,
     'end': 'mac_056_0x002d30.txt', 'values': {'mac_6026': 35, 'mac_602a': 26, 'mac_602b': 20, 'mac_602c': 25}},
    {'name': '全选最后一项→伊织的事', 'strategy': 'last', 'final_index': 0,
     'end': 'mac_056_0x0024f8.txt', 'values': {'mac_6026': 15, 'mac_602a': 17, 'mac_602b': 24, 'mac_602c': 21}},
]

rows = []
for case in CASES:
    with contextlib.redirect_stdout(io.StringIO()):
        env, history, ending = run('mac_000_0x00000c.txt', case['strategy'], False, case['final_index'])
    assert ending == case['end'], (case['name'], ending)
    values = {k: env[k] for k in case['values']}
    assert values == case['values'], (case['name'], values)
    rows.append({'case': case['name'], 'ending': ending, 'values': values,
                 'choices': len(history), 'last_choices': history[-4:]})
    print(f"PASS {case['name']} -> {ending} {values}")
(ROOT / '数据/数值结局路线.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print('WROTE 数据/数值结局路线.json')
