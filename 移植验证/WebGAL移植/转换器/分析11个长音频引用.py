import json
import struct
import sys
from pathlib import Path

PORT_ROOT = Path(__file__).resolve().parents[1]
VERIFY_ROOT = PORT_ROOT.parent
sys.path.insert(0, str(VERIFY_ROOT))

import MAC_命令表提取 as cmd_table
import MAC_解析 as mac_parser

MAC_DIR = VERIFY_ROOT / '输出-保护边修复/MAC'
ELF_PATH = VERIFY_ROOT / '输出-保护边修复/SYSTEM/SLPM_665.70'

TARGET_SE = {86, 98, 134, 135, 137, 138, 139, 140, 141, 142, 144}

def main():
    table = cmd_table.load_table(ELF_PATH.read_bytes())
    mac_files = sorted(list(MAC_DIR.glob('MAC_*.bin')))
    print(f"Scanning {len(mac_files)} MAC files from {MAC_DIR}...")

    results = {se: [] for se in TARGET_SE}

    for mf in mac_files:
        data = mf.read_bytes()
        script_name = mf.stem
        # 扫描 data 中的指令序列
        # MAC 文件头部 0x0C 为第零入口偏移
        if len(data) < 16:
            continue
        entry0 = struct.unpack_from('<I', data, 0x08)[0] if len(data) > 8 else 0x0C
        # 遍历字节流
        staged_code = None
        staged_vol = None
        staged_speed = None

        # 线性扫描指令
        offset = 0x0C
        # 为了捕获所有入口，可以遍历整个文件或线性反汇编
        # 直接使用滑窗模式匹配 0x0F (file_read) 和 0x3A (se_set)
        for i in range(0, len(data) - 4, 4):
            op = data[i]
            if op == 0x0F: # file_read
                code = data[i+2] | (data[i+3] << 8)
                if (code >> 12) == 5: # AFS 5 = SE
                    staged_code = code & 0xFFF
            elif op == 0x3F: # se_vol
                staged_vol = data[i+2]
            elif op == 0x3A: # se_set
                channel = data[i+1]
                idx = staged_code
                if idx in TARGET_SE:
                    results[idx].append({
                        'script': script_name,
                        'offset': hex(i),
                        'channel': channel,
                        'volume': staged_vol,
                        'file_read_code': hex(staged_code) if staged_code else None
                    })

    print("\n=== 11 个未映射长音频在原盘中的引用结果 ===")
    for se in sorted(TARGET_SE):
        refs = results[se]
        print(f"SE_{se:05d}: 共 {len(refs)} 处引用")
        for r in refs[:5]:
            print(f"    {r['script']} @ {r['offset']} (通道 {r['channel']}, 音量 {r['volume']})")

    out_file = PORT_ROOT / '数据/长音频11条目原盘引用全量表.json'
    out_file.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding='utf-8')
    print(f"\n完整报告已保存至: {out_file}")

if __name__ == '__main__':
    main()
