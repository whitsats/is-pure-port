"""生成「台词 ↔ 语音」对照表（移植可直接使用）。

输出 MAC_文本语音/<序号>_<脚本>.tsv：行号 / 语音号 / 日文 / 中文
中文来自 对照/*.tsv，按「假名+标点」核心串做窗口模糊对齐（TSV 的日文列混有简体字）。
"""
from __future__ import annotations

import re
from pathlib import Path

import MAC_解析 as P

from 本地路径 import ZH_ROOT

TSV_DIR = ZH_ROOT / '对照'
OUT = Path(__file__).resolve().parent / "MAC_文本语音"
WINDOW = 6


def load_tsv() -> dict[str, list[tuple[str, str]]]:
    out: dict[str, list[tuple[str, str]]] = {}
    for p in sorted(TSV_DIR.glob("*.tsv")):
        cur = None
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.startswith("#"):
                cur = line[1:].strip().lower()
                out.setdefault(cur, [])
            elif cur and line.startswith("No."):
                parts = line.split("\t")
                if len(parts) >= 3:
                    out[cur].append((parts[1], parts[2]))
    return out


def core(s: str) -> str:
    s = s.replace("%K%P", "").replace("%K", "").replace("%P", "")
    s = re.sub(r"\s+", "", s)
    return "".join(ch for ch in s if not ("\u4e00" <= ch <= "\u9fff"))


def sim(a: str, b: str) -> float:
    ca, cb = core(a), core(b)
    if not ca or not cb:
        return 0.0
    if len(ca) > len(cb):
        ca, cb = cb, ca
    best = 0.0
    for start in range(0, max(1, len(cb) - len(ca) + 1)):
        seg = cb[start : start + len(ca)]
        best = max(best, sum(1 for x, y in zip(ca, seg) if x == y) / len(ca))
    return best


def align(mac: list[str], ref: list[tuple[str, str]]) -> list[int]:
    mapping = [-1] * len(mac)
    j = 0
    for i, txt in enumerate(mac):
        best_j, best_s = -1, 0.0
        for k in range(max(0, j - 2), min(len(ref), j + WINDOW)):
            s = sim(txt, ref[k][0])
            if s > best_s:
                best_s, best_j = s, k
        if best_s >= 0.6 and best_j >= 0:
            mapping[i] = best_j
            j = best_j + 1
        else:
            j = min(j + 1, len(ref))
    return mapping


def main():
    data = P.load()
    rows = P.entries(data)
    ts = load_tsv()
    OUT.mkdir(exist_ok=True)
    total = matched = voiced = 0
    report = []
    for r in rows:
        if not r["size"] or P.is_debug(r["name"]):
            continue
        scr = P.script(data, r)
        ops, _t = P.split_script(scr)
        tl = P.texts(scr, ops)
        key = r["name"].lower().replace(".bip", "")
        ref = ts.get(key, [])
        mapping = align([t[3] for t in tl], ref) if ref else [-1] * len(tl)
        lines = ["行号\t语音号\t日文\t中文"]
        ok = 0
        for i, (_pos, line_no, vid, jp) in enumerate(tl):
            cn = ref[mapping[i]][1] if mapping[i] >= 0 else ""
            ok += bool(cn)
            lines.append(f"{line_no}\t{-1 if vid == 0xFFFF else vid}\t{jp}\t{cn}")
        (OUT / f"{r['i']:02d}_{r['name']}.tsv").write_text("\n".join(lines), encoding="utf-8")
        total += len(tl)
        matched += ok
        voiced += sum(1 for t in tl if t[2] != 0xFFFF)
        report.append((r["i"], r["name"], len(tl), ok, len(ref)))
    print(f"输出 {len(report)} 份 → {OUT}")
    print(f"台词 {total}，带语音 {voiced}，中文匹配 {matched}（{matched/max(total,1)*100:.1f}%）")
    low = [(i, nm, n, m, rl) for i, nm, n, m, rl in report if rl and m < n * 0.9]
    if low:
        print("\n匹配率偏低：")
        for i, nm, n, m, rl in low:
            print(f"  {i:>2} {nm:<16} 台词 {n:>5} 匹配 {m:>5} TSV {rl:>5}")


if __name__ == "__main__":
    main()
