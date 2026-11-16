"""提取原版/v7.4 INIT 的 57 条章节标题，生成可复核 JSON。"""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mac_title_table import (DEFAULT_ORIGINAL_INIT, DEFAULT_V74_INIT, load_title_table,
                             write_title_manifest)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--v74-init', type=Path, default=DEFAULT_V74_INIT)
    parser.add_argument('--original-init', type=Path, default=DEFAULT_ORIGINAL_INIT)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    table = load_title_table(args.v74_init, args.original_init)
    write_title_manifest(args.output, table)
    print(f"输出 {args.output}: {table['record_count']} 条；"
          f"第 0 条={table['records'][0]['title']}；第 1 条={table['records'][1]['title']}")


if __name__ == '__main__':
    main()
