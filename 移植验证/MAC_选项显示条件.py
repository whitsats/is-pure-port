"""把已提取的选项可见性编码转成可审查的描述，不猜测游戏状态。"""
from collections import Counter
from pathlib import Path
import csv

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "MAC_命令表" / "选项分支静态映射.tsv"
OUT = ROOT / "MAC_命令表" / "选项显示条件.tsv"


def describe(raw):
    kind = raw & 0xC000
    bank = 1 if raw & 0x2000 else 0
    index = raw & 0x1FFF
    if kind == 0x4000:
        return f"状态区{bank}的16位值[{index}]非零时显示"
    if kind == 0x8000:
        return f"状态区{bank}的位[{index}]为1时显示"
    value = raw if raw < 0x8000 else raw - 0x10000
    return "恒显示" if value else "恒不显示"


def main():
    with SRC.open(encoding="utf-8-sig", newline="") as f:
        source = list(csv.DictReader(f, delimiter="\t"))
    if OUT.exists():
        raise FileExistsError(f"Not overwriting {OUT}")
    counts = Counter()
    with OUT.open("x", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f, delimiter="\t")
        writer.writerow(["剧本", "选项指令偏移", "记录序号", "日文选项", "条件原值", "显示条件", "高16位原值", "假设返回值", "静态跳转目标"])
        for row in source:
            field = int(row["记录字段2"], 16)
            raw = field & 0xFFFF
            desc = describe(raw)
            counts["恒显示" if desc == "恒显示" else "依赖状态或其他"] += 1
            writer.writerow([row["原剧本名"], row["选项指令偏移"], row["假设返回值"], row["日文选项"],
                             f"0x{raw:04X}", desc, f"0x{field >> 16:04X}", row["假设返回值"], row["静态跳转目标"]])
    print("条目数", len(source), "统计", dict(counts), "输出", OUT)


if __name__ == "__main__":
    main()
