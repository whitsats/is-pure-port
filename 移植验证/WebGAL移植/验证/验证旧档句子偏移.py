"""核对旧版对白锚点在当前场景中的位置。"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NEW = ROOT / '新游戏打盘高清版/public/game/scene/mac_000_0x00000c.txt'
OLD = ROOT / '数据/旧场景_mac_000_0x00000c.txt'
NEW_037 = ROOT / '新游戏打盘高清版/public/game/scene/mac_037_0x00000c.txt'
OLD_037 = ROOT / '数据/旧场景_mac_037_0x00000c.txt'
ANCHORS = [
    ('一贵「那是……」', 72, 77),
    ('一贵「什，什么啊？」', 77, 85),
    ('哪有他那样说话的呀', 94, 102),
    ('回头一看，发现背后站着一个女孩', 96, 107),
    ('那之后，你和那人之间怎么样了', 106, 117),
    ('……４年前', 110, 121),
]


def line_of(lines, needle):
    hits = [i + 1 for i, line in enumerate(lines) if needle in line]
    assert len(hits) == 1, (needle, hits)
    return hits[0]


old = OLD.read_text(encoding='utf-8').splitlines()
new = NEW.read_text(encoding='utf-8').splitlines()
for needle, old_line, new_line in ANCHORS:
    assert line_of(old, needle) == old_line, needle
    assert line_of(new, needle) == new_line, needle
    print(f'PASS {needle}: 旧 {old_line} -> 新 {new_line} (+{new_line - old_line})')

# 第 37 章包含环境音语句和神社的鉴赏解锁，按对白分别核对偏移。
ANCHORS_037 = [
    ('jumpLabel:mac_1e4 -when=mac_a035==0;', 1, 1),
    ('这种地方居然有神社', 205, 213),
    ('我一个人走进了神社', 223, 231),
    ('jumpLabel:mac_ca0 -when=mac_600e!=0;', 224, 233),
    ('changeScene:mac_037_0x0016b4.txt', 424, 437),
]
old_037 = OLD_037.read_text(encoding='utf-8').splitlines()
new_037 = NEW_037.read_text(encoding='utf-8').splitlines()
for needle, old_line, new_line in ANCHORS_037:
    assert line_of(old_037, needle) == old_line, needle
    assert line_of(new_037, needle) == new_line, needle
    print(f'PASS MAC_037 {needle}: 旧 {old_line} -> 新 {new_line} (+{new_line - old_line})')
unlock_line = line_of(new_037, 'unlockCg:EV_0088.png')
assert unlock_line == line_of(new_037, '我一个人走进了神社。') + 1
print('PASS 新版开篇和神社的旧档对白锚点')
