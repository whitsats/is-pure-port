import os
import fitz

pdf_dir = r"E:\BackUp\Books\漫画\IS\超清完全版全12卷"
files = sorted([f for f in os.listdir(pdf_dir) if f.endswith(".pdf")])

print("=== 超清完全版全12卷 页面版式统计 ===")
total_all = 0
portrait_all = 0
landscape_all = 0

for f in files:
    path = os.path.join(pdf_dir, f)
    doc = fitz.open(path)
    portrait = 0
    landscape = 0
    for p in doc:
        if p.rect.width < p.rect.height:
            portrait += 1
        else:
            landscape += 1
    total_all += len(doc)
    portrait_all += portrait
    landscape_all += landscape
    print(f"{f}: 共 {len(doc)} 页 | 单页竖版(单列): {portrait} | 跨页横版: {landscape}")
    doc.close()

print(f"\n全部卷总计: {total_all} 页 | 单页竖版: {portrait_all} 页 ({(portrait_all/total_all)*100:.1f}%) | 跨页横版: {landscape_all} 页")

# 检查旁边的 高清双页版全15卷 目录作为对比
other_dir = r"E:\BackUp\Books\漫画\IS\高清双页版全15卷"
if os.path.exists(other_dir):
    print("\n=== 对比：高清双页版全15卷 目录 ===")
    other_files = sorted([f for f in os.listdir(other_dir) if f.endswith(".pdf")])
    for f in other_files[:3]:
        doc = fitz.open(os.path.join(other_dir, f))
        p0 = doc[0]
        ratio = p0.rect.width / p0.rect.height
        print(f"{f}: 页数 {len(doc)} | 第1页尺寸: {p0.rect.width:.1f}x{p0.rect.height:.1f} (宽高比: {ratio:.2f} -> {'双页横版' if ratio > 1 else '单页竖版'})")
        doc.close()
