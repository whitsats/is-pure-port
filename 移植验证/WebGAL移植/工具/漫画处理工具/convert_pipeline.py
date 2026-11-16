"""Import the complete twelve-volume edition as offline WebP pages."""

import argparse
from concurrent.futures import ProcessPoolExecutor
from io import BytesIO
import json
from pathlib import Path
import re

import fitz
from PIL import Image


def page_image(document, page):
    images = page.get_images()
    if len(images) == 1 and images[0][1] == 0 and page.rotation == 0:
        xref = images[0][0]
        placements = page.get_image_rects(xref, transform=True)
        if len(placements) == 1:
            rect, transform = placements[0]
            fills_page = max(abs(a - b) for a, b in zip(rect, page.rect)) < 1
            upright = transform.a > 0 and transform.d > 0 and not (transform.b or transform.c)
            if fills_page and upright:
                embedded = document.extract_image(xref)
                return Image.open(BytesIO(embedded['image']))

    scale = 2200 / max(page.rect.width, page.rect.height)
    pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), colorspace=fitz.csRGB, alpha=False)
    return Image.frombytes('RGB', (pixmap.width, pixmap.height), pixmap.samples)


def convert_volume(volume, pdf, output, quality):
    directory = output / f'vol_{volume:02d}'
    directory.mkdir(parents=True, exist_ok=True)
    pages = []
    with fitz.open(pdf) as document:
        for page in document:
            with page_image(document, page) as image:
                width, height = image.size
                name = f'{page.number + 1:03d}.webp'
                target = directory / name
                temporary = target.with_suffix('.webp.tmp')
                image.save(temporary, format='WEBP', quality=quality, method=4)
                temporary.replace(target)
                pages.append({
                    'file': name,
                    'width': width,
                    'height': height,
                    'bytes': target.stat().st_size,
                })
    print(f'第 {volume:02d} 卷完成，{len(pages)} 页', flush=True)
    return {'id': volume, 'title': f'I’s 完全版 第{volume:02d}卷', 'pages': pages}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--quality', type=int, default=85, choices=range(1, 101), metavar='1..100')
    parser.add_argument('--workers', type=int, default=6)
    args = parser.parse_args()
    sources = {}
    for pdf in args.input.glob('*.pdf'):
        match = re.search(r'_(\d{2})$', pdf.stem)
        if not match:
            continue
        volume = int(match[1])
        if volume in sources:
            raise ValueError(f'第 {volume} 卷有多份源文件')
        sources[volume] = pdf
    if set(sources) != set(range(1, 13)):
        raise ValueError(f'需要第 01–12 卷，现有卷号 {sorted(sources)}')
    if args.workers < 1:
        parser.error('--workers 必须大于 0')

    args.output.mkdir(parents=True, exist_ok=True)
    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        jobs = [executor.submit(convert_volume, volume, sources[volume], args.output, args.quality)
                for volume in sorted(sources)]
        volumes = [job.result() for job in jobs]
    manifest = {'version': 1, 'volumes': volumes}
    temporary = args.output / 'manifest.json.tmp'
    temporary.write_text(json.dumps(manifest, ensure_ascii=False, separators=(',', ':')) + '\n', encoding='utf-8')
    temporary.replace(args.output / 'manifest.json')
    total = sum(len(volume['pages']) for volume in volumes)
    print(f'完成 {len(volumes)} 卷，共 {total} 页')


if __name__ == '__main__':
    main()
