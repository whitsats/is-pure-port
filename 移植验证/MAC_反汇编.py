"""MAC 剧本全量反汇编：输出每脚本的指令清单与全局操作码统计。"""
from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path

import MAC_解析 as P

OUT = Path(__file__).resolve().parent / "MAC_反汇编"


def main():
    data = P.load()
    rows = P.entries(data)
    OUT.mkdir(exist_ok=True)
    freq = Counter()
    pats = defaultdict(Counter)
    exact = 0
    total = 0
    text_total = 0
    for r in rows:
        if not r["size"]:
            continue
        scr = P.script(data, r)
        ops, text_start, = P.split_script(scr)
        end_of_ops = ops[-1][0] + (8 if ops[-1][3] is not None else 4) if ops else 0
        exact += (end_of_ops == text_start)
        tl = P.texts(scr, ops)
        text_total += len(tl)
        lines = [f"; {r['name']}   指令区 0x0..0x{text_start:X}  文本区 0x{text_start:X}..  "
                 f"指令 {len(ops)}  文本 {len(tl)}"]
        for k, (pos, op, args, ptr) in enumerate(ops):
            if ptr is not None:
                lines.append(f"{pos:06X}  60  ptr={ptr:06X}")
                continue
            if k > 0 and ops[k - 1][3] is not None:
                # 文本记录尾：行号 + 语音号
                nop = op
                line = nop | (args[0] << 8)
                vid = args[1] | (args[2] << 8)
                lines.append(f"{pos:06X}      line={line:<5} voice="
                             f"{'--' if vid == 0xFFFF else vid}")
                continue
            freq[op] += 1
            pats[op][args] += 1
            total += 1
            lines.append(f"{pos:06X}  {op:02X}  {args[0]:02X} {args[1]:02X} {args[2]:02X}")
        # 文本内容附在文件末尾，便于阅读
        lines.append("")
        lines.append(";; ---- 文本 ----")
        for _pos, line, vid, txt in tl:
            lines.append(f";; [{line:>4}] {'--' if vid == 0xFFFF else f'{vid:>5}'}  {txt}")
        (OUT / f"{r['i']:02d}_{r['name']}.asm").write_text("\n".join(lines), encoding="utf-8")

    print(f"反汇编 {len([r for r in rows if r['size']])} 份 → {OUT}")
    print(f"指令区恰好衔接文本区：{exact}/74；非文本指令 {total} 条；文本记录 {text_total} 条")

    stat = [f"操作码统计（非文本指令 {total} 条，文本记录 {text_total} 条）", ""]
    print("\n=== 操作码频率 top 40 ===")
    for op, n in freq.most_common(40):
        top = "; ".join(f"{a}×{c}" for a, c in pats[op].most_common(3))
        line = f"0x{op:02X}  {n:>7}    {top}"
        print("  " + line)
        stat.append(line)
    (OUT / "MAC_操作码统计.txt").write_text("\n".join(stat), encoding="utf-8")


if __name__ == "__main__":
    main()
