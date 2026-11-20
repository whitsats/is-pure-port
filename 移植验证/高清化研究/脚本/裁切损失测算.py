"""裁切到目标比例会损失多少（16:9 / 16:10 两种目标）。"""
ROWS = [
    ("EV 640x448", 640, 448),
    ("满幅 BG 640x448（8 张）", 640, 448),
    ("BG 主体 640x280（131 张）", 640, 280),
    ("EV 竖图 640x896（1 张）", 640, 896),
    ("ETC 640x448（UI，90 张）", 640, 448),
]
TARGETS = [("16:9 (1920×1080)", 1920 / 1080), ("16:10 (1920×1200)", 1920 / 1200)]


def analyse(w, h, T):
    a = w / h
    if abs(a - T) < 0.005:
        return "无需裁切", "0%", (w, h)
    if a > T:                     # 太宽 → 裁左右
        nw = round(h * T)
        cut = w - nw
        return f"左右各裁 {cut//2}px", f"{cut/w*100:.1f}% 宽", (nw, h)
    nh = round(w / T)             # 太窄 → 裁上下
    cut = h - nh
    return f"上下各裁 {cut//2}px", f"{cut/h*100:.1f}% 高", (w, nh)


def main():
    for label, T in TARGETS:
        print(f"\n=== 裁切到 {label} ===")
        print(f"{'素材':<26}{'裁切方式':<22}{'损失':<12}{'裁后尺寸'}")
        for name, w, h in ROWS:
            mode, pct, left = analyse(w, h, T)
            print(f"{name:<26}{mode:<22}{pct:<12}{left[0]}x{left[1]}")


if __name__ == "__main__":
    main()
