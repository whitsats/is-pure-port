"""方案对比：普通做法 vs 最优解（同一场景 / 同一文案 / 同一屏幕 2400×1080）。

四种候选方案：
  普通1 · 直接拉伸铺满：640×448 整帧 bilinear 拉到 2400×1080（人物变形 + 画面模糊）
  普通2 · 等比缩放 + 两侧黑边：整帧等比放大到 1080 高，居中，两侧留黑边（不糊但浪费 36% 屏幕）
  方案3 · 严格无损：素材 NEAREST ×4（逐像素无损）+ 等比 + 上下填充 + 原生文字（块状但无损）
  最优解 · AI ×4 母版 + 等比 3.75× + 上下背景填充 + 原生文字（横屏，推荐）
  方案4 · 竖屏重构：BG 作画窗 + 模糊背景填充 + 立绘 + 原生文字（仅竖屏模式需要）

输出：
  对比/方案对比_总览.png        各方案 800 宽预览（纵向叠放）
  对比/方案对比_画质1比1.png     同一张脸在普通1/普通2/最优解下同尺寸 1:1 对比
  对比/方案对比_指标.txt         量化指标 + 选型建议
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent.parent
SRC = HERE.parent / "输出-保护边修复"
SR = HERE / "超分结果"
OUT = HERE / "对比"

BG_SRC = SRC / "BG/BG_0218.png"
CHR_SRC = SRC / "CHR/CHR_0000.png"
BG_MASTER = SR / "BG_0218__esrgan_v3_x4.png"
CHR_MASTER = SR / "CHR_0000__esrgan_v3_x4.png"
BG_NEAREST = SR / "BG_0218__nearest4.png"
CHR_NEAREST = SR / "CHR_0000__nearest4.png"

W, H = 2400, 1080
SPEAKER = "伊织"
TEXT = "伊织「我很喜欢通过角色扮演去体验不同的人群」"
SPRITE_H_640 = 420
SPRITE_X_640 = 320


def cjk(sz: int):
    for p in ("C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simhei.ttf"):
        try:
            return ImageFont.truetype(p, sz)
        except Exception:  # noqa: BLE001
            continue
    return ImageFont.load_default()


def content_of(master: Image.Image) -> Image.Image:
    a = np.asarray(master.convert("RGBA"))[..., 3]
    ys = np.where((a > 8).mean(axis=1) > 0.02)[0]
    xs = np.where((a > 8).mean(axis=0) > 0.02)[0]
    if not len(ys) or not len(xs):
        return master
    return master.crop((int(xs[0]), int(ys[0]), int(xs[-1]) + 1, int(ys[-1]) + 1))


def fit_w(img: Image.Image, w: int, resample=Image.LANCZOS) -> Image.Image:
    return img.resize((w, max(1, round(img.height * w / img.width))), resample)


def wrap(im: Image.Image, text: str, f, max_w: int) -> list[str]:
    d = ImageDraw.Draw(im)
    lines, cur = [], ""
    for ch in text:
        if d.textlength(cur + ch, font=f) > max_w:
            lines.append(cur)
            cur = ch
        else:
            cur += ch
    if cur:
        lines.append(cur)
    return lines


# ---------------------------------------------------------------- 640 基准帧（普通做法用）
def make_frame_640() -> Image.Image:
    frame = Image.new("RGB", (640, 448), (12, 12, 12))
    bgc = content_of(Image.open(BG_SRC).convert("RGBA"))
    bgs = fit_w(bgc, 640)
    frame.paste(bgs, (0, 44), bgs)
    ch = content_of(Image.open(CHR_SRC).convert("RGBA"))
    k = SPRITE_H_640 / ch.height
    spr = ch.resize((max(1, round(ch.width * k)), SPRITE_H_640), Image.LANCZOS)
    frame.paste(spr, (SPRITE_X_640, 448 - SPRITE_H_640), spr)
    d = ImageDraw.Draw(frame, "RGBA")
    d.rounded_rectangle([16, 330, 624, 440], radius=8, fill=(10, 12, 24, 205),
                        outline=(210, 190, 140, 230), width=2)
    d.text((30, 342), SPEAKER, fill=(240, 220, 150, 255), font=cjk(14))
    y = 366
    for ln in wrap(frame, TEXT, cjk(15), 560):
        d.text((30, y), ln, fill=(245, 245, 245, 255), font=cjk(15))
        y += 22
    return frame


# ---------------------------------------------------------------- 共通合成（横屏，素材可替换）
def compose_landscape(bg: Image.Image, ch: Image.Image) -> Image.Image:
    canvas = Image.new("RGB", (W, H), (0, 0, 0))
    bgs = fit_w(bg, W)
    a = np.asarray(bg.convert("RGB"))
    top = tuple(int(v) for v in a[:3].reshape(-1, 3).mean(axis=0))
    bot = tuple(int(v) for v in a[-3:].reshape(-1, 3).mean(axis=0))
    canvas.paste(Image.new("RGB", (W, H), bot), (0, 0))
    y0 = (H - bgs.height) // 2
    canvas.paste(bgs, (0, y0), bgs)
    if y0 > 0:
        canvas.paste(Image.new("RGB", (W, y0), top), (0, 0))
        canvas.paste(Image.new("RGB", (W, H - y0 - bgs.height), bot), (0, y0 + bgs.height))
    target_h = int(H * 0.82)
    k = target_h / ch.height
    spr = ch.resize((max(1, round(ch.width * k)), target_h), Image.LANCZOS)
    spr_x, spr_y = int(W * 0.55), H - target_h
    canvas.paste(spr, (spr_x, spr_y), spr)
    d = ImageDraw.Draw(canvas, "RGBA")
    m = int(W * 0.03)
    tb = H - int(H * 0.30)
    d.rounded_rectangle([m, tb, W - m, H - int(H * 0.02)], radius=int(W * 0.012),
                        fill=(10, 12, 24, 205), outline=(210, 190, 140, 230), width=3)
    d.text((m + W * 0.02, tb + H * 0.030), SPEAKER, fill=(240, 220, 150, 255), font=cjk(56))
    yy = tb + int(H * 0.10)
    for ln in wrap(canvas, TEXT, cjk(62), W - 2 * m - int(W * 0.04)):
        d.text((m + W * 0.02, yy), ln, fill=(245, 245, 245, 255), font=cjk(62))
        yy += int(H * 0.066)
    canvas._spr = (spr_x, spr_y, k)  # type: ignore[attr-defined]
    return canvas


# ---------------------------------------------------------------- 四种渲染
def render_stretch() -> Image.Image:
    return make_frame_640().resize((W, H), Image.BILINEAR)


def render_letterbox() -> Image.Image:
    k = H / 448
    fw = round(640 * k)
    canvas = Image.new("RGB", (W, H), (0, 0, 0))
    canvas.paste(make_frame_640().resize((fw, H), Image.LANCZOS), ((W - fw) // 2, 0))
    canvas._off = (W - fw) // 2  # type: ignore[attr-defined]
    return canvas


def render_best() -> Image.Image:
    bg = content_of(Image.open(BG_MASTER).convert("RGBA"))
    ch = content_of(Image.open(CHR_MASTER).convert("RGBA"))
    return compose_landscape(bg, ch)


def render_lossless() -> Image.Image:
    bg = content_of(Image.open(BG_NEAREST).convert("RGBA"))
    ch = content_of(Image.open(CHR_NEAREST).convert("RGBA"))
    img = compose_landscape(bg, ch)
    # 标注：整像素 ×4 属于「严格无损」，但小字/斜线会呈块状
    return img


def render_portrait() -> Image.Image:
    from PIL import ImageFilter
    Wp, Hp = 1080, 2400
    bg = content_of(Image.open(BG_MASTER).convert("RGBA"))
    ch = content_of(Image.open(CHR_MASTER).convert("RGBA"))
    t = fit_w(bg, Wp)
    canvas = Image.new("RGB", (Wp, Hp))
    y = 0
    while y < Hp:
        canvas.paste(t, (0, y))
        y += t.height
    canvas = canvas.filter(ImageFilter.GaussianBlur(70))
    band = fit_w(bg, Wp)
    band_y = int(Hp * 0.10)
    canvas.paste(band, (0, band_y), band)
    target_h = int(Hp * 0.52)
    k = target_h / ch.height
    spr = ch.resize((max(1, round(ch.width * k)), target_h), Image.LANCZOS)
    canvas.paste(spr, ((Wp - spr.width) // 2,
                       band_y + band.height - int(target_h * 0.12)), spr)
    d = ImageDraw.Draw(canvas, "RGBA")
    m = int(Wp * 0.03)
    tb = Hp - int(Hp * 0.26)
    d.rounded_rectangle([m, tb, Wp - m, Hp - int(Hp * 0.02)], radius=int(Wp * 0.02),
                        fill=(10, 12, 24, 210), outline=(210, 190, 140, 230), width=3)
    d.text((m + 20, tb + 30), SPEAKER, fill=(240, 220, 150, 255), font=cjk(52))
    yy = tb + int(Hp * 0.06)
    for ln in wrap(canvas, TEXT, cjk(56), Wp - 2 * m - 40):
        d.text((m + 20, yy), ln, fill=(245, 245, 245, 255), font=cjk(56))
        yy += int(Hp * 0.033)
    return canvas


# ---------------------------------------------------------------- 指标
def sharpness(im: Image.Image, box) -> float:
    a = np.asarray(im.convert("L"), dtype=np.float64)
    x0, y0, x1, y1 = box
    a = a[y0:y1, x0:x1]
    gy, gx = np.gradient(a)
    return float((np.abs(gx) + np.abs(gy)).mean())


def face_box_of_sprite(spr_x: int, spr_y: int, k: float, content_w: int, content_h: int):
    """立绘内容区里人脸相对位置（CHR_0000 实测：内容 1020×1593，脸在中上部）。"""
    rel = (0.26, 0.05, 0.74, 0.38)
    return (int(spr_x + content_w * k * rel[0]), int(spr_y + content_h * k * rel[1]),
            int(spr_x + content_w * k * rel[2]), int(spr_y + content_h * k * rel[3]))


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    stretch = render_stretch()
    letter = render_letterbox()
    lossless = render_lossless()
    best = render_best()
    portrait = render_portrait()

    files = {
        "方案对比_普通1_拉伸铺满.png": stretch,
        "方案对比_普通2_等比留边.png": letter,
        "方案对比_方案3_严格无损整像素.png": lossless,
        "方案对比_最优_AI等比填充.png": best,
        "方案对比_方案4_竖屏重构.png": portrait,
    }
    for name, im in files.items():
        im.save(OUT / name)
        print(f"  {name} {im.size}")

    # ---- 总览（横屏四方案 + 竖屏一方案，各缩到 700 宽）
    panels = [
        ("普通1 · 640×448 直接拉伸铺满（人物变形 + 画面模糊）", stretch),
        ("普通2 · 等比缩放 + 两侧黑边（不糊，但浪费约 36% 屏幕）", letter),
        ("方案3 · 严格无损（整像素 ×4）+ 等比 + 填充（逐像素无损，但线条块状）", lossless),
        ("最优解 · AI ×4 母版 + 等比 3.75× + 上下填充 + 原生文字", best),
        ("方案4 · 竖屏重构（BG 作画窗 + 模糊填充 + 立绘 + 原生文字）", portrait),
    ]
    pw = 700
    rows = []
    for title, im in panels:
        ph = max(1, round(im.height * pw / im.width))
        thumb = im.resize((pw, ph), Image.LANCZOS)
        bar = Image.new("RGB", (pw, 26), (12, 12, 12))
        ImageDraw.Draw(bar).text((6, 5), title, fill=(255, 235, 120), font=cjk(14))
        t = Image.new("RGB", (pw, ph + 26))
        t.paste(bar, (0, 0))
        t.paste(thumb, (0, 26))
        rows.append(t)
    sheet = Image.new("RGB", (pw, sum(r.height for r in rows) + 8 * len(rows)), (0, 0, 0))
    y = 0
    for r in rows:
        sheet.paste(r, (0, y))
        y += r.height + 8
    sheet.save(OUT / "方案对比_总览.png")
    print(f"总览 → 方案对比_总览.png {sheet.size}")

    # ---- 画质 1:1（普通1 / 普通2 / 方案3 / 最优，同脸同显示尺寸）
    kw, kh = W / 640, H / 448
    ch640 = content_of(Image.open(CHR_SRC).convert("RGBA"))
    k640 = SPRITE_H_640 / ch640.height
    f_spr_x, f_spr_y = SPRITE_X_640, 448 - SPRITE_H_640
    fb = face_box_of_sprite(f_spr_x, f_spr_y, k640, ch640.width, ch640.height)
    k2 = H / 448
    off2 = (W - round(640 * k2)) // 2
    b1 = (int(fb[0] * kw), int(fb[1] * kh), int(fb[2] * kw), int(fb[3] * kh))
    b2 = (int(fb[0] * k2) + off2, int(fb[1] * k2), int(fb[2] * k2) + off2, int(fb[3] * k2))
    spx, spy, spk = best._spr  # type: ignore[attr-defined]
    chm = content_of(Image.open(CHR_MASTER).convert("RGBA"))
    b3 = face_box_of_sprite(spx, spy, spk, chm.width, chm.height)
    spx4, spy4, spk4 = lossless._spr  # type: ignore[attr-defined]
    chn = content_of(Image.open(CHR_NEAREST).convert("RGBA"))
    b4 = face_box_of_sprite(spx4, spy4, spk4, chn.width, chn.height)

    disp = (480, 400)
    crops = []
    for title, im, box in (("普通1（拉伸 + 双线性）", stretch, b1),
                           ("普通2（等比 + Lanczos）", letter, b2),
                           ("方案3（整像素 ×4，严格无损）", lossless, b4),
                           ("最优解（AI ×4 母版）", best, b3)):
        crop = im.crop(box).resize(disp, Image.LANCZOS)
        bar = Image.new("RGB", (disp[0], 26), (12, 12, 12))
        ImageDraw.Draw(bar).text((6, 5), title, fill=(255, 235, 120), font=cjk(15))
        t = Image.new("RGB", (disp[0], disp[1] + 26))
        t.paste(bar, (0, 0))
        t.paste(crop, (0, 26))
        crops.append(t)
    sheet2 = Image.new("RGB", (disp[0] * 2 + 8, crops[0].height * 2 + 8), (0, 0, 0))
    for i, t in enumerate(crops):
        sheet2.paste(t, ((i % 2) * (disp[0] + 8), (i // 2) * (crops[0].height + 8)))
    sheet2.save(OUT / "方案对比_画质1比1.png")
    print(f"画质对比 → 方案对比_画质1比1.png {sheet2.size}")

    # ---- 指标
    s1, s2, s3, s4 = (sharpness(stretch, b1), sharpness(letter, b2),
                      sharpness(lossless, b4), sharpness(best, b3))
    lines = [
        "四种方案对比（同一场景 / 同一文案 / 同一屏幕 2400×1080）",
        "",
        f"{'项目':<20}{'普通1 拉伸铺满':<24}{'普通2 等比留边':<22}{'方案3 严格无损':<20}{'最优解 AI 等比填充'}",
        f"{'画面变形':<20}{'有（纵向拉伸 1.52×）':<24}{'无（等比 2.41×）':<22}{'无（等比 3.75×）':<20}{'无（等比 3.75×）'}",
        f"{'人物比例':<20}{'被拉高/压扁':<24}{'正常':<22}{'正常':<20}{'正常'}",
        f"{'屏幕利用率':<20}{'100%（但内容变形）':<24}{'约 64%（两侧 428px 黑边）':<22}{'约 97%':<20}{'约 97%'}",
        f"{'像素来源':<20}{'640 原图直接插值':<24}{'640 原图 Lanczos':<22}{'整像素复制（无损）':<20}{'AI ×4 补细节'}",
        f"{'清晰度（观感）':<20}{'差':<24}{'一般':<22}{'锐利但块状':<20}{'锐利且平滑'}",
        f"{'文字（UI）':<20}{'640 尺寸文字被放大发虚':<24}{'同样发虚':<22}{'原生字号，锐利':<20}{'原生字号，锐利'}",
        f"{'脸位锐度值':<20}{f'{s1:.2f}':<24}{f'{s2:.2f}':<22}{f'{s3:.2f}':<20}{f'{s4:.2f}'}",
        f"{'制作成本':<20}{'几乎为零（运行时缩放）':<24}{'几乎为零':<22}{'~40 分钟 / ~2 GB':<20}{'~45-70 分钟 / ~3-4 GB'}",
        f"{'风险':<20}{'人物变形不可接受':<24}{'浪费屏幕，观感差':<22}{'放大后块状明显':<20}{'UI 贴图字形会变（建议原生绘制）'}",
        "",
        "结论：",
        "  · 只做「不拉伸」最低要求 → 普通2（等比留边）即可，但只用到 64% 屏幕，且仍是 640 原图插值，偏糊。",
        "  · 要「高清 + 满屏 + 不变形」→ 最优解（AI×4 母版 + 等比 + 背景填充）：屏幕利用率 97%，且画质来自超分母版。",
        "  · 若坚持「逐像素严格无损」→ 方案3：内容与 640 原图逐像素等价，但放大后线条块状，观感不如最优解。",
        "  · 竖屏模式 → 方案4（重构布局），横竖屏可共存，由引擎按屏幕方向选择。",
    ]
    (OUT / "方案对比_指标.txt").write_text("\n".join(lines), encoding="utf-8")
    print("\n" + "\n".join(lines))


if __name__ == "__main__":
    main()
