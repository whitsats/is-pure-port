"""为 WebGAL 鉴赏页生成 CG 缩略图，并把路径写回 appreciation.json。

原图是 640x448 的 PNG（69 张约 27 MB），而鉴赏格子实际只显示约 576x540，
所以统一出 576 宽的 WebP（quality 82），整本约 1.7 MB。缩略图只用于列表，
点开条目仍加载原图。

输入：WebGAL移植/开屏片头样片/public/game/background/EV_*.png
输出：
  WebGAL移植/开屏片头样片/public/game/background/thumb/EV_0000.webp ...
  WebGAL移植/开屏片头样片/public/game/appreciation.json 的 cg[].thumb

用法：
  python 生成CG缩略图.py
  python 生成CG缩略图.py --width 480 --quality 78
  python 生成CG缩略图.py --dry-run

依赖：Pillow
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image

GAME = Path(__file__).resolve().parent / "WebGAL移植" / "开屏片头样片" / "public" / "game"
BACKGROUND = GAME / "background"
THUMB = BACKGROUND / "thumb"
PRESET = GAME / "appreciation.json"
DEFAULT_WIDTH = 576
DEFAULT_QUALITY = 82


def build_thumbs(files: list[Path], width: int, quality: int, dry_run: bool) -> tuple[int, int]:
    """生成缩略图，返回（缩略图总字节, 原图总字节）。"""
    THUMB.mkdir(exist_ok=True)
    thumb_bytes = src_bytes = 0
    for path in files:
        out = THUMB / f"{path.stem}.webp"
        src_bytes += path.stat().st_size
        if not dry_run:
            with Image.open(path) as im:
                rgb = im.convert("RGB")
                height = round(rgb.height * width / rgb.width)
                rgb.resize((width, height), Image.Resampling.LANCZOS).save(
                    out, "WEBP", quality=quality, method=6
                )
        if out.exists():
            thumb_bytes += out.stat().st_size
    return thumb_bytes, src_bytes


def write_preset(files: list[Path], dry_run: bool) -> int:
    """把 thumb 字段写回 appreciation.json，返回更新条数。"""
    data = json.loads(PRESET.read_text(encoding="utf-8"))
    known = {path.stem for path in files}
    updated = 0
    for item in data.get("cg", []):
        stem = Path(item.get("file", "")).stem
        if stem not in known:
            print(f"  跳过（没有原图）：{item.get('file')}")
            continue
        item["thumb"] = f"thumb/{stem}.webp"
        updated += 1
    if not dry_run:
        PRESET.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
        )
    return updated


def main() -> None:
    parser = argparse.ArgumentParser(description="生成鉴赏页 CG 缩略图并写回 appreciation.json")
    parser.add_argument("--width", type=int, default=DEFAULT_WIDTH, help=f"缩略图宽度（默认 {DEFAULT_WIDTH}）")
    parser.add_argument("--quality", type=int, default=DEFAULT_QUALITY, help=f"WebP 质量（默认 {DEFAULT_QUALITY}）")
    parser.add_argument("--dry-run", action="store_true", help="只统计，不写文件")
    args = parser.parse_args()

    files = sorted(BACKGROUND.glob("EV_*.png"))
    if not files:
        raise SystemExit(f"没有找到原图：{BACKGROUND / 'EV_*.png'}")

    thumb_bytes, src_bytes = build_thumbs(files, args.width, args.quality, args.dry_run)
    updated = write_preset(files, args.dry_run)
    ratio = thumb_bytes / src_bytes * 100 if src_bytes else 0
    suffix = "（dry-run，未写入）" if args.dry_run else ""
    print(f"缩略图：{len(files)} 张，宽 {args.width}px，WebP q{args.quality}{suffix}")
    print(f"  原图 {src_bytes / 1048576:.1f} MB -> 缩略图 {thumb_bytes / 1048576:.2f} MB（{ratio:.1f}%）")
    print(f"  appreciation.json：更新 {updated} 条 thumb -> {PRESET}")


if __name__ == "__main__":
    main()
