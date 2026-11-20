import os
import fitz  # PyMuPDF

pdf_dir = r"E:\BackUp\Books\漫画\IS\超清完全版全12卷"
files = sorted([f for f in os.listdir(pdf_dir) if f.endswith(".pdf")])

print(f"Found {len(files)} volumes in {pdf_dir}:\n")

total_pages = 0
total_bytes = 0

for idx, f in enumerate(files):
    path = os.path.join(pdf_dir, f)
    size_mb = os.path.getsize(path) / (1024 * 1024)
    total_bytes += os.path.getsize(path)
    
    doc = fitz.open(path)
    page_count = len(doc)
    total_pages += page_count
    
    sample_page = doc[0]
    rect = sample_page.rect
    img_list = sample_page.get_images()
    
    img_info = "No image"
    if img_list:
        xref = img_list[0][0]
        base_img = doc.extract_image(xref)
        img_info = f"{base_img['width']}x{base_img['height']}, {base_img['ext']}, {base_img['colorspace']}"
        
    print(f"[{idx+1:02d}] {f} | Size: {size_mb:.1f} MB | Pages: {page_count} | Page 1 Dim: {rect.width:.1f}x{rect.height:.1f} | Img: {img_info}")
    doc.close()

print(f"\nSummary:")
print(f"Total volumes: {len(files)}")
print(f"Total pages: {total_pages}")
print(f"Total size: {total_bytes / (1024*1024):.2f} MB ({total_bytes / (1024*1024*1024):.2f} GB)")
