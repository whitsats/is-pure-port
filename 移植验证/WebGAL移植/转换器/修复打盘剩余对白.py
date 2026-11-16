"""Resolve the remaining archive dialogue slots and document each decision."""
import argparse
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path
import re

from mac_release import DISC_MAC, DIALOGUE_DATA
from 核查字码表缺口 import decode_slot, load_tables
import MAC_解析 as mac

TOKENS = re.compile(r'%(?:LC|FS|FE|[KkPpNnOo])')
KANA = re.compile(r'[ぁ-ヺｦ-ﾟ]')
PUNCTUATION = str.maketrans({';': '；', ':': '：', '|': '｜', '\\': '＼'})
BASE_GLYPHS = {0x8140: '　', 0x8145: '・', 0x9643: '—'}
# Equivalent Chinese characters inferred from the Japanese source in these slots.
# These are display substitutions for the port, not changes to the PS2 font table.
READINGS = {0x95F4: '乒', 0x95F5: '乓', 0x95F6: '官', 0x95F7: '蒡', 0x95F8: '壶',
            0x95F9: '熊', 0x95FA: '泰', 0x95FB: '迪', 0x95FC: '谊',
            0x9640: '珊', 0x9641: '瑚', 0x9642: '霞'}
SHORT = {
    'は？': '啊？', 'え？': '诶？', 'あっ！': '啊！', '……え？': '……诶？', '……ん？': '……嗯？',
    'はっ！': '啊！', 'フン……': '哼……', 'うっ……': '唔……', 'ん？': '嗯？', 'えっ？': '诶？',
    '夏？': '夏天？', 'はあ？': '哈？', 'へ？': '咦？', 'はっ！？': '啊！？', 'なに？': '什么？',
    'はぁ！？': '哈！？', 'えっ！？': '诶！？', 'あ……': '啊……', 'どうだ？': '怎么样？',
    'ええ！？': '诶诶！？', 'あれ？': '咦？', 'い？': '咦？', '違う！': '不是！',
    'へっ？': '咦？', 'あっ！？': '啊！？', 'あっ……': '啊……', 'どこ？': '在哪儿？',
    'えっ……': '诶……', 'あっ': '啊', '夢？': '是梦吗？', 'だ': '是', 'が': '可是', 'の': '的',
}
REVIEWED = {
    (31, 0x68): '唉，伊织肯定生气了吧。',
    (31, 0x74): '要是奈美没把我叫出来，真不知道会怎么样。',
    (31, 0x80): '不过，没想到泉竟然是湾田高的学生……',
    (31, 0x8C): '我有预感，这下要乱成一团了。',
    (31, 0xC8): '寺谷「一・贵」',
    (17, 0x78): '难怪昨天大家都有些心神不宁的，原来今天就是情人节啊。',
    (17, 0xD2C): '原来如此……今天是情人节啊！',
    (22, 0x1C8C): '奈美「明天开始就是黄金周了嘛。所以，要不要来我家集训？」',
    (23, 0x4A1C): '奈美「伊织把身体抬起来，濑户从下面把手环过去。就这样。」',
    (34, 0x750): '一贵「难道你想坐我旁边？真拿你没办法，过・来・吧！」',
    (38, 0xCEC): '知道我们交往的只有森崎、寺谷和越苗这三个人。这种秘密感正好。',
    (39, 0x249C): '森崎「准套房会是什么样的呢……今晚咱们好好玩个开心吧，濑・户・君。」',
    (40, 0x4D0): '一贵「寺・谷・君」',
}


def visible(text):
    text = re.sub(r'%[Nn](?=.+)', '　', text)
    return TOKENS.sub('', text).strip().translate(PUNCTUATION)


def build():
    archive = DISC_MAC.read_bytes()
    entries = mac.entries(archive)
    _, author = load_tables()
    author.update(BASE_GLYPHS)
    patched, rows = {}, []
    with (DIALOGUE_DATA / '未译对白清单.tsv').open(encoding='utf-8-sig', newline='') as file:
        for row in csv.DictReader(file, delimiter='\t'):
            script, offset = row['剧本'], int(row['指令偏移'], 16)
            chapter = int(script[4:7])
            if chapter not in patched:
                patched[chapter] = mac.script(archive, entries[chapter])
            data = patched[chapter]
            address = int(row['文本偏移'], 16)
            slot = data[address:data.index(b'\0', address)]
            original = row['日文原文']
            review = REVIEWED.get((chapter, offset))
            if review:
                text, provenance = review, '盘面对照补译或修正拼接'
            elif row['匹配状态'] == '原字节不变':
                if slot != original.encode('cp932'):
                    raise ValueError(f'{script}:{offset:#x} 原槽变化')
                text = visible(original)
                if text in SHORT:
                    text, provenance = SHORT[text], '原盘日文补译'
                elif all(c in '…　 ' for c in text):
                    provenance = '原盘标点或控制符'
                else:
                    raise ValueError(f'{script}:{offset:#x} 未核对的原盘文本 {text!r}')
            else:
                glyphs = [item for part in slot.split(b'\xff') for item in decode_slot(part, author)]
                inferred = sorted({code for char, code, _ in glyphs if char is None})
                raw = ''.join(char if char is not None else READINGS[code] for char, code, _ in glyphs)
                text = visible(raw)
                provenance = '盘内字码按日文核对补读' if inferred else '盘内解码并整理控制符'
            if '%' in text or KANA.search(text) or any(c in text for c in ';:|\\\r\n'):
                raise ValueError(f'{script}:{offset:#x} 残留控制符或日文假名: {text!r}')
            if not text and row['语音号'] != '-1':
                raise ValueError(f'{script}:{offset:#x} 控制行带语音')
            rows.append({**row, '中文': text, '译文来源': provenance, '打盘槽': slot.hex()})
    if len({(r['剧本'], r['指令偏移']) for r in rows}) != len(rows):
        raise ValueError('地址重复')
    return {'sha256': hashlib.sha256(archive).hexdigest(),
            'counts': dict(Counter(r['译文来源'] for r in rows)), 'rows': rows}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = build()
    with args.output.open('x', encoding='utf-8') as file:
        json.dump(report, file, ensure_ascii=False, indent=2)
        file.write('\n')
    print(report['counts'])
