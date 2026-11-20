"""手机适配模拟：严格等比缩放 + 背景填充，绝不拉伸。

生成：
  手机模拟/横屏_<W>x<H>_BG满宽.png      BG 640×280 等比放大铺满宽度，上下用背景填充
  手机模拟/横屏_<W>x<H>_原构图留边.png   640×448 整幅等比缩放，两侧留边
  手机模拟/竖屏_<H>x<W>_<填充方式>.png   竖屏重构（BG 作画窗 + 填充背景）
另输出 缩放比例表.txt
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent.parent
SRC = HERE.parent / "输出-保护边修复"
SR = HERE / "超分结果"
OUT = HERE / "手机模拟"
TOOLS = Path(r"E:\Entertainment\IS\is-pure-zh\工具\超分")
RR = TOOLS / "realesrgan-ncnn-vulkan.exe"

BG_SRC = SRC / "BG/BG_0218.png"
CHR_SRC = SRC / "CHR/CHR_0000.png"
BG_MASTER = SR / "BG_0218__esrgan_v3_x4.png"
CHR_MASTER = SR / "CHR_0000__esrgan_v3_x4.png"


def cjk(sz: int):
    for p in ("C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simhei.ttf"):
        try:
            return ImageFont.truetype(p, sz)
        except Exception:  # noqa: BLE001
            continue
    return ImageFont.load_default()


def content_of(master: Image.Image, master_scale: int = 4) -> Image.Image:
    """去掉超分结果里原图的透明边距，只保留内容区（等比，不裁剪画面内容）。"""
    a = np.asarray(master.convert("RGBA"))[..., 3]
    ys = np.where((a > 8).mean(axis=1) > 0.02)[0]
    xs = np.where((a > 8).mean(axis=0) > 0.02)[0]
    if len(ys) == 0 or len(xs) == 0:
        return master
    return master.crop((int(xs[0]), int(ys[0]), int(xs[-1]) + 1, int(ys[-1]) + 1))


def fit_w(img: Image.Image, w: int) -> Image.Image:
    """等比缩放到指定宽度（唯一允许的缩放方式）。"""
    h = max(1, round(img.height * w / img.width))
    return img.resize((w, h), Image.LANCZOS)


def edge_colors(bg: Image.Image) -> tuple[tuple, tuple]:
    a = np.asarray(bg.convert("RGB"))
    top = tuple(int(v) for v in a[:3].reshape(-1, 3).mean(axis=0))
    bot = tuple(int(v) for v in a[-3:].reshape(-1, 3).mean(axis=0))
    return top, bot


def mirror_fill(bg: Image.Image, W: int, H: int) -> Image.Image:
    """用 BG 自身镜像延伸填满画布（不缩放变形，保持像素比例）。"""
    tile = bg
    canvas = Image.new("RGB", (W, H))
    # 先等比放到宽度 W
    t = fit_w(tile, W)
    # 垂直方向镜像平铺
    y = 0
    flip = False
    while y < H:
        seg = t if not flip else t.transpose(Image.FLIP_TOP_BOTTOM)
        canvas.paste(seg, (0, y))
        y += seg.height
        flip = not flip
    return canvas


def blur_fill(bg: Image.Image, W: int, H: int, radius: int = 60) -> Image.Image:
    from PIL import ImageFilter
    t = bg.resize((W, max(1, round(bg.height * W / bg.width))), Image.LANCZOS)
    canvas = Image.new("RGB", (W, H))
    y = 0
    while y < H:
        canvas.paste(t, (0, y))
        y += t.height
    return canvas.filter(ImageFilter.GaussianBlur(radius))


def textbox(canvas: Image.Image, box_h: int, text: str, speaker: str):
    d = ImageDraw.Draw(canvas, "RGBA")
    W, H = canvas.size
    margin = int(W * 0.03)
    top = H - box_h
    d.rounded_rectangle([margin, top, W - margin, H - int(H * 0.02)],
                        radius=int(W * 0.012), fill=(10, 12, 24, 205),
                        outline=(210, 190, 140, 230), width=max(2, W // 500))
    f_name = cjk(max(20, int(W * 0.030)))
    f_text = cjk(max(22, int(W * 0.033)))
    d.text((margin + W * 0.02, top + box_h * 0.10), speaker,
           fill=(240, 220, 150, 255), font=f_name)
    # 简单折行
    max_w = W - 2 * margin - W * 0.04
    line, lines = "", []
    for ch in text:
        if d.textlength(line + ch, font=f_text) > max_w:
            lines.append(line)
            line = ch
        else:
            line += ch
    lines.append(line)
    y = top + box_h * 0.34
    for ln in lines[:3]:
        d.text((margin + W * 0.02, y), ln, fill=(245, 245, 245, 255), font=f_text)
        y += box_h * 0.22


def compose_landscape(W: int, H: int, bg_content: Image.Image, chr_content: Image.Image,
                      mode: str, out: Path):
    canvas = Image.new("RGB", (W, H), (0, 0, 0))
    if mode == "bg_fill":
        # BG 等比铺满宽度，高度不足部分用背景色填充（上=顶行色，下=底行色）
        bg = fit_w(bg_content, W)
        top, bot = edge_colors(bg_content)
        y0 = (H - bg.height) // 2
        canvas.paste(Image.new("RGB", (W, H), bot), (0, 0))
        canvas.paste(bg, (0, y0))
        if y0 > 0:
            canvas.paste(Image.new("RGB", (W, y0), top), (0, 0))
            canvas.paste(Image.new("RGB", (W, H - y0 - bg.height), bot), (0, y0 + bg.height))
        # 立绘：按高度等比放到 0.82H，靠右
        ch = chr_content
        target_h = int(H * 0.82)
        scale = target_h / ch.height
        cw, chh = max(1, round(ch.width * scale)), target_h
        sprite = ch.resize((cw, chh), Image.LANCZOS)
        canvas.paste(sprite, (int(W * 0.55), H - chh), sprite)
    else:
        # 原构图：640×448 整幅等比缩放，两侧留边
        src = Image.open(SRC / "BG/BG_0000.png")  # 黑帧不是好例子，改用 BG 内容+立绘合成分辨率说明
        frame = Image.new("RGB", (640, 448), (0, 0, 0))
        bgm = fit_w(bg_content, 640)
        frame.paste(bgm, (0, (448 - bgm.height) // 2))
        ch = chr_content
        scale = (448 * 0.82) / ch.height
        sprite = ch.resize((max(1, round(ch.width * scale)), int(448 * 0.82)), Image.LANCZOS)
        frame.paste(sprite, (300, 448 - sprite.height), sprite)
        k = min(W / 640, H / 448)
        fw, fh = round(640 * k), round(448 * k)
        canvas.paste(frame.resize((fw, fh), Image.LANCZOS), ((W - fw) // 2, (H - fh) // 2))
    textbox(canvas, int(H * 0.30), "伊织「我很喜欢通过角色扮演去体验不同的人群」", "伊织")
    canvas.save(out)
    print(f"  {out.name} {canvas.size}")


def compose_portrait(W: int, H: int, bg_content: Image.Image, chr_content: Image.Image,
                     fill_mode: str, out: Path):
    canvas = Image.new("RGB", (W, H), (0, 0, 0))
    if fill_mode == "solid":
        top, bot = edge_colors(bg_content)
        grad = Image.new("RGB", (1, H))
        for y in range(H):
            t = y / max(1, H - 1)
            grad.putpixel((0, y), tuple(int(top[i] * (1 - t) + bot[i] * t) for i in range(3)))
        canvas = grad.resize((W, H))
    elif fill_mode == "mirror":
        canvas = mirror_fill(bg_content, W, H)
    else:
        canvas = blur_fill(bg_content, W, H)

    # BG 作画窗：等比铺满宽度
    band = fit_w(bg_content, W)
    band_y = int(H * 0.10)
    canvas.paste(band, (0, band_y))
    # 立绘：等比放到 0.55H，居中偏下
    target_h = int(H * 0.52)
    scale = target_h / chr_content.height
    sprite = chr_content.resize((max(1, round(chr_content.width * scale)), target_h), Image.LANCZOS)
    sx = (W - sprite.width) // 2
    canvas.paste(sprite, (sx, band_y + band.height - int(target_h * 0.12)), sprite)
    textbox(canvas, int(H * 0.26), "伊织「我很喜欢通过角色扮演去体验不同的人群」", "伊织")
    canvas.save(out)
    print(f"  {out.name} {canvas.size}")


def scale_table():
    rows = []
    phones = [
        ("16:9", 1920, 1080), ("19.5:9", 2340, 1080), ("20:9", 2400, 1080),
        ("16:9 1440p", 2560, 1440), ("20:9 1440p", 3200, 1440),
        ("21:9", 2520, 1080), ("竖屏 19.5:9", 1080, 2340), ("竖屏 20:9", 1080, 2400),
    ]
    for name, W, H in phones:
        if W >= H:
            kw = W / 640
            kh = H / 280
            k = min(kw, kh)
            bgw, bgh = round(640 * k), round(280 * k)
            pad = H - bgh
            rows.append((name, f"{W}×{H}", f"{k:.3f}×", f"{bgw}×{bgh}",
                         f"上下各 {pad//2}px" if pad >= 0 else "需裁剪"))
        else:
            k = W / 640
            rows.append((name, f"{W}×{H}", f"{k:.3f}×", f"{W}×{round(280*k)}",
                         f"竖屏需重构，剩余 {H - round(280*k)}px 用背景填充"))
    txt = ["手机分辨率 → BG(640×280) 等比适配表", "",
           f"{'机型比例':<14}{'分辨率':<14}{'等比系数':<10}{'BG 显示尺寸':<16}{'处理'}"]
    for r in rows:
        txt.append(f"{r[0]:<14}{r[1]:<14}{r[2]:<10}{r[3]:<16}{r[4]}")
    txt += ["", "说明：",
            "1) 只按「等比系数」缩放，绝不分别拉伸宽高；",
            "2) 多出的高度用背景填充（顶/底行颜色或镜像延伸），不裁剪画面；",
            "3) 超分母版为 ×4（BG 2560×1120），显示系数 ≤4 时是缩小采样（质量最好）；",
            "   1440p 机型(3200 宽)需要 5.0× > 4，母版略显不足，可后续补 ×5/×6 母版。"]
    (OUT / "缩放比例表.txt").write_text("\n".join(txt), encoding="utf-8")
    print("\n=== 缩放比例表 ===")
    print("\n".join(txt))


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    if not BG_MASTER.exists() or not CHR_MASTER.exists():
        raise SystemExit("缺少超分母版，请先跑 关键样本对比.py")
    bg = content_of(Image.open(BG_MASTER))
    ch = content_of(Image.open(CHR_MASTER))
    print(f"BG 母版内容区 {bg.size}，CHR 母版内容区 {ch.size}")

    compose_landscape(2400, 1080, bg, ch, "bg_fill", OUT / "横屏_2400x1080_BG满宽.png")
    compose_landscape(1920, 1080, bg, ch, "bg_fill", OUT / "横屏_1920x1080_BG满宽.png")
    compose_landscape(2340, 1080, bg, ch, "bg_fill", OUT / "横屏_2340x1080_BG满宽.png")
    compose_landscape(3200, 1440, bg, ch, "bg_fill", OUT / "横屏_3200x1440_BG满宽.png")
    compose_landscape(2400, 1080, bg, ch, "frame", OUT / "横屏_2400x1080_原构图留边.png")

    compose_portrait(1080, 2400, bg, ch, "solid", OUT / "竖屏_1080x2400_纯色填充.png")
    compose_portrait(1080, 2400, bg, ch, "mirror", OUT / "竖屏_1080x2400_镜像填充.png")
    compose_portrait(1080, 2400, bg, ch, "blur", OUT / "竖屏_1080x2400_模糊填充.png")
    scale_table()


if __name__ == "__main__":
    main()
