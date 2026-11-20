import os
import time
import fitz
from PIL import Image
import io

pdf_path = r"E:\BackUp\Books\漫画\IS\超清完全版全12卷\I''s-完全版_01.pdf"
out_dir = r"E:\Entertainment\IS\is-pure-port\_archive\移植研究\研究-WebGAL漫画嵌入\test_samples"
os.makedirs(out_dir, exist_ok=True)

doc = fitz.open(pdf_path)
print(f"Testing extraction and compression from {os.path.basename(pdf_path)}")

# Test first 10 pages
test_pages = [0, 1, 2, 3, 4, 10, 20]

print(f"{'Page':<6} | {'Orig Dim':<12} | {'Orig Ext':<8} | {'Orig Size(KB)':<14} | {'WebP Q85(KB)':<14} | {'WebP Q90(KB)':<14} | {'Ratio':<8}")
print("-" * 85)

for page_idx in test_pages:
    page = doc[page_idx]
    images = page.get_images()
    if not images:
        continue
    xref = images[0][0]
    base_img = doc.extract_image(xref)
    orig_bytes = base_img["image"]
    orig_ext = base_img["ext"]
    orig_size_kb = len(orig_bytes) / 1024
    
    img = Image.open(io.BytesIO(orig_bytes))
    w, h = img.size
    
    # Save original
    orig_file = os.path.join(out_dir, f"page_{page_idx:03d}_orig.{orig_ext}")
    with open(orig_file, "wb") as f:
        f.write(orig_bytes)
        
    # Save WebP Q85
    webp85_buf = io.BytesIO()
    img.save(webp85_buf, format="WEBP", quality=85, method=4)
    webp85_bytes = webp85_buf.getvalue()
    webp85_size_kb = len(webp85_bytes) / 1024
    webp85_file = os.path.join(out_dir, f"page_{page_idx:03d}_q85.webp")
    with open(webp85_file, "wb") as f:
        f.write(webp85_bytes)
        
    # Save WebP Q90
    webp90_buf = io.BytesIO()
    img.save(webp90_buf, format="WEBP", quality=90, method=4)
    webp90_bytes = webp90_buf.getvalue()
    webp90_size_kb = len(webp90_bytes) / 1024
    webp90_file = os.path.join(out_dir, f"page_{page_idx:03d}_q90.webp")
    with open(webp90_file, "wb") as f:
        f.write(webp90_bytes)
        
    ratio = (webp85_size_kb / orig_size_kb) * 100
    print(f"{page_idx:<6} | {w}x{h:<7} | {orig_ext:<8} | {orig_size_kb:<14.1f} | {webp85_size_kb:<14.1f} | {webp90_size_kb:<14.1f} | {ratio:<6.1f}%")

doc.close()
