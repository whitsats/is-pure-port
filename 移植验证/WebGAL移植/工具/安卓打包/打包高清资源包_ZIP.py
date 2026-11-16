import argparse
import os
import time
import zipfile
from pathlib import Path

def main():
    project = Path(__file__).resolve().parents[4]
    parser = argparse.ArgumentParser(description="打包安卓的离线 game 资源目录")
    parser.add_argument('--source', type=Path,
                        default=project / '移植验证/WebGAL移植/新游戏打盘高清版/public/game')
    parser.add_argument('--output', type=Path, default=project / '成品/安卓移植/game.zip')
    args = parser.parse_args()
    source_dir = args.source.resolve()
    target_zip = args.output.resolve()
    if not (source_dir / 'config.txt').is_file():
        parser.error(f'找不到游戏配置：{source_dir / "config.txt"}')
    if target_zip.exists():
        parser.error(f'输出已存在，使用 --output 指定新文件：{target_zip}')
    target_zip.parent.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("开始打包《I's Pure》高清离线资源包 (ZIP_STORED 极速无损打包)")
    print(f"源目录: {source_dir}")
    print(f"输出文件: {target_zip}")
    print("=" * 60)

    start_time = time.time()
    file_list = []
    for root, dirs, files in os.walk(source_dir):
        for f in files:
            full = os.path.join(root, f)
            rel = os.path.relpath(full, os.path.dirname(source_dir))
            rel = rel.replace('\\', '/')
            file_list.append((full, rel))

    total_files = len(file_list)
    print(f"待打包文件总数: {total_files}")

    with zipfile.ZipFile(target_zip, 'x', compression=zipfile.ZIP_STORED, allowZip64=True) as zf:
        for idx, (full, rel) in enumerate(file_list, 1):
            zf.write(full, rel)
            if idx % 1000 == 0 or idx == total_files:
                elapsed = time.time() - start_time
                pct = idx / total_files * 100
                print(f"[{pct:5.1f}%] 已写入 {idx}/{total_files} 文件 (耗时: {elapsed:.1f}s)...", flush=True)

    elapsed = time.time() - start_time
    zip_size_gb = os.path.getsize(target_zip) / (1024 ** 3)
    print("=" * 60)
    print(f"打包成功！")
    print(f"产物路径: {target_zip}")
    print(f"产物大小: {zip_size_gb:.2f} GiB")
    print(f"总耗时: {elapsed:.1f} 秒")
    print("=" * 60)

if __name__ == "__main__":
    main()
