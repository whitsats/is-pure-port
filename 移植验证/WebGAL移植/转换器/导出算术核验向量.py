"""导出乘/除/取余的 WebGAL 生成行与 Python 期望值，供浏览器核验。

生成的行来自 `mac_webgal_state.emit_word_write`（与真实转换器同一函数），
期望值由 `mac_state` 的 R5900 语义算出（16 位截断、除法/取余向零截断），
两边互相独立，浏览器测试只负责确认 WebGAL 运行时得到同一个数。
"""
import argparse
import json
from pathlib import Path
import struct
import sys

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / '转换器'))
from mac_state import _signed_div, to_s16
from mac_webgal_state import emit_word_write

DESTINATION = 0x602C
CASES = [
    ('mul_small', 3, 7, 6),
    ('mul_wrap_positive', 3, 30000, 2),
    ('mul_wrap_negative', 3, -300, 300),
    ('div_positive', 4, 7, 2),
    ('div_negative_dividend', 4, -7, 2),
    ('div_negative_divisor', 4, 7, -2),
    ('div_wrap', 4, -32768, -1),
    ('mod_positive', 5, 7, 2),
    ('mod_negative_dividend', 5, -7, 2),
    ('mod_negative_divisor', 5, 7, -2),
]


def expected(operation, left, right):
    if operation == 3:
        return to_s16(left * right)
    if operation == 4:
        return to_s16(_signed_div(left, right))
    if operation == 5:
        return to_s16(left - _signed_div(left, right) * right)
    raise ValueError(operation)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(f'拒绝覆盖已有文件: {args.output}')
    vectors = []
    for name, operation, left, right in CASES:
        raw = bytes([0x09, operation]) + struct.pack('<HH', DESTINATION, right & 0xFFFF) + b'\x00\x00'
        lines = emit_word_write(raw, (DESTINATION,), f'arithmetic_{name}')
        if not lines:
            raise ValueError(f'没有生成状态写入: {name}')
        vectors.append({'name': name, 'operation': operation,
                        'input': left, 'operand': right,
                        'lines': lines, 'expected': expected(operation, left, right)})
    payload = {'destination': f'mac_{DESTINATION:04x}',
               'source': '转换器/mac_webgal_state.py 的 emit_word_write',
               'expectation': '转换器/mac_state.py 的 R5900 语义（to_s16 截断、除法向零）',
               'vectors': vectors}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    for vector in vectors:
        print(f"{vector['name']}: {vector['input']} op{vector['operation']} {vector['operand']} -> {vector['expected']}")
    print('向量:', args.output)


if __name__ == '__main__':
    main()
