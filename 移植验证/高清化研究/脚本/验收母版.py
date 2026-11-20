"""母版验收：数量、尺寸、alpha、体积、失败清单 + 生成总览图。"""
from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent.parent
SRC = HERE.parent / "输出-保护边修复"
OUT = HERE.parent / "输出-高清化-×4"
REPORT = HERE / "母版验收报告.md"
OVERVIEW = HERE / "对比"

CATS = ["BG", "CHR", "EV", "ETC"]


def cjk(sz=14):
    for p in ("C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simhei.ttf"):
        try:
            return ImageFont.truetype(p, sz)
        except Exception:  # noqa: BLE001
            continue
    return ImageFont.load_default()


def main():
    print("=== 母版验收 ===")
    lines = ["# 高清化母版验收报告", "", "输出目录：`移植验证/输出-高清化-×4/`", ""]
    rows = []
    total_mb = 0.0
    ok_all = True
    for cat in CATS:
        sd, od = SRC / cat, OUT / cat
        sfiles = sorted(sd.glob("*.png"))
        ofiles = sorted(od.glob("*.png")) if od.exists() else []
        sset = {p.name for p in sfiles}
        oset = {p.name for p in ofiles}
        missing = sorted(sset - oset)
        extra = sorted(oset - sset)
        # 尺寸校验（全量）
        bad_dim = []
        alpha_bad = []
        mb = 0.0
        for p in ofiles:
            try:
                with Image.open(p) as im:
                    o = im.size
                with Image.open(sd / p.name) as im2:
                    s = im2.size
                if o != (s[0] * 4, s[1] * 4):
                    bad_dim.append(p.name)
                mb += p.stat().st_size / 1048576
            except Exception:  # noqa: BLE001
                bad_dim.append(p.name)
        total_mb += mb
        # alpha 抽样校验（每类最多 40 张）
        for p in ofiles[:: max(1, len(ofiles) // 40)][:40]:
            try:
                with Image.open(p) as im:
                    oa = np.asarray(im.convert("RGBA"))[..., 3].mean()
                with Image.open(sd / p.name) as im2:
                    sa = np.asarray(im2.convert("RGBA"))[..., 3].mean()
                if abs(oa - sa) > 3:
                    alpha_bad.append((p.name, round(abs(oa - sa), 1)))
            except Exception:  # noqa: BLE001
                pass
        status = "✅" if not missing and not bad_dim else "❌"
        if missing or bad_dim:
            ok_all = False
        print(f"{status} {cat:<4} 源 {len(sfiles):>4} / 母版 {len(ofiles):>4}  缺 {len(missing)}  "
              f"尺寸异常 {len(bad_dim)}  alpha异常 {len(alpha_bad)}  体积 {mb/1024:.2f} GB")
        lines.append(f"| {cat} | {len(sfiles)} | {len(ofiles)} | {len(missing)} | "
                     f"{len(bad_dim)} | {len(alpha_bad)} | {mb/1024:.2f} GB |")
        rows.append((cat, sfiles, ofiles, missing, bad_dim, alpha_bad, mb))
        if missing[:5]:
            print(f"   缺: {missing[:5]}")
        if bad_dim[:5]:
            print(f"   尺寸异常: {bad_dim[:5]}")

    lines.insert(4, "| 类别 | 源数量 | 母版数量 | 缺失 | 尺寸异常 | alpha异常 | 体积 |")
    lines.insert(5, "|---|---|---|---|---|---|---|")
    lines.append("")
    lines.append(f"**合计体积：{total_mb/1024:.2f} GB**")
    lines.append("")

    # 质检日志统计（按文件去重，取最后一次状态 —— 日志是追加写，早期失败后已回退成功）
    log = OUT / "质检日志.csv"
    if log.exists():
        latest = {}
        with log.open(encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                latest[(r["类别"], r["文件"])] = (r["状态"], r["说明"])
        c = Counter()
        reasons = Counter()
        for (cat, fn), (st, why) in latest.items():
            c[st] += 1
            if "回退" in st:
                reasons[why[:60]] += 1
        lines.append("## 质检日志统计（按文件去重，最终状态）")
        lines.append("")
        for k, v in sorted(c.items()):
            lines.append(f"- {k}：{v}")
        if reasons:
            lines.append("")
            lines.append("AI 质检未过、已回退为整像素无损的贴图（噪声/速度线类结构，AI 会改写其纹理）：")
            for k, v in reasons.most_common(20):
                lines.append(f"- {k} × {v}")
        print("\n质检日志(去重):", dict(c))

    # 母版清单 CSV
    manifest = OUT / "母版清单.csv"
    with manifest.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["类别", "文件", "源尺寸", "母版尺寸", "体积MB"])
        for cat, sfiles, ofiles, *_ in rows:
            for p in ofiles:
                with Image.open(p) as im:
                    o = im.size
                with Image.open(SRC / cat / p.name) as im2:
                    s = im2.size
                w.writerow([cat, p.name, f"{s[0]}x{s[1]}", f"{o[0]}x{o[1]}",
                            f"{p.stat().st_size/1048576:.2f}"])
    print(f"清单 → {manifest}")

    # 总览图：每类抽若干张，缩到 200 宽拼 8 列
    OVERVIEW.mkdir(parents=True, exist_ok=True)
    for cat, sfiles, ofiles, *_ in rows:
        if not ofiles:
            continue
        pick = ofiles[:: max(1, len(ofiles) // 40)][:40]
        cols = 8
        cw = 200
        tiles = []
        for p in pick:
            with Image.open(p) as im:
                im = im.convert("RGBA")
                k = cw / im.width
                t = im.resize((cw, max(1, round(im.height * k))), Image.LANCZOS)
            bg = Image.new("RGB", t.size, (30, 30, 30))
            bg.paste(t, (0, 0), t)
            tiles.append(bg)
        if not tiles:
            continue
        row_h = max(t.height for t in tiles) + 18
        nrow = (len(tiles) + cols - 1) // cols
        sheet = Image.new("RGB", (cw * cols, row_h * nrow), (12, 12, 12))
        d = ImageDraw.Draw(sheet)
        for i, t in enumerate(tiles):
            x, y = (i % cols) * cw, (i // cols) * row_h
            d.text((x + 3, y + 2), pick[i].stem, fill=(200, 200, 120), font=cjk(11))
            sheet.paste(t, (x, y + 16))
        path = OVERVIEW / f"母版总览_{cat}.png"
        sheet.save(path)
        print(f"总览 → {path.name} {sheet.size}")

    lines.append("## 结论")
    lines.append("")
    if ok_all:
        lines.append("所有类别数量与尺寸校验通过，母版可用于引擎接入。")
    else:
        lines.append("存在缺失或尺寸异常，见上表。")
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n报告 → {REPORT}")


if __name__ == "__main__":
    main()
