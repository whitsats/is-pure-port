import os
import time
import fitz
from PIL import Image
import io
import json

pdf_path = r"E:\BackUp\Books\漫画\IS\超清完全版全12卷\I''s-完全版_01.pdf"
out_dir = r"E:\Entertainment\IS\is-pure-port\_archive\移植研究\研究-WebGAL漫画嵌入\sample_manga_vol01"
os.makedirs(out_dir, exist_ok=True)

doc = fitz.open(pdf_path)
total_pages = len(doc)
print(f"Total pages in Vol 01: {total_pages}")

# Extract first 15 pages for prototype test
test_page_count = 15
page_meta = []

start_time = time.time()
for i in range(test_page_count):
    page = doc[i]
    images = page.get_images()
    if not images:
        continue
    xref = images[0][0]
    base_img = doc.extract_image(xref)
    orig_bytes = base_img["image"]
    
    img = Image.open(io.BytesIO(orig_bytes))
    w, h = img.size
    
    # Save as WebP
    webp_name = f"{i+1:03d}.webp"
    webp_path = os.path.join(out_dir, webp_name)
    img.save(webp_path, format="WEBP", quality=85, method=4)
    size_kb = os.path.getsize(webp_path) / 1024
    
    page_meta.append({
        "page": i + 1,
        "width": w,
        "height": h,
        "file": webp_name,
        "size_kb": round(size_kb, 1),
        "is_spread": w > h  # detected cross-page / double spread
    })

elapsed = time.time() - start_time
print(f"Extracted and converted {test_page_count} pages in {elapsed:.2f}s ({elapsed/test_page_count*1000:.1f}ms/page)")

manifest = {
    "title": "I''s 完全版 第01卷",
    "volume": 1,
    "total_pages": total_pages,
    "sampled_pages": test_page_count,
    "pages": page_meta
}

with open(os.path.join(out_dir, "manifest.json"), "w", encoding="utf-8") as f:
    json.dump(manifest, f, indent=2, ensure_ascii=False)

print("Saved manifest.json successfully.")
doc.close()
