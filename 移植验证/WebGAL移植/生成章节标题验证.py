"""用静态 INIT 标题表的第 0 条与原开头对白演示 WebGAL 章节演出。"""
import json
from pathlib import Path
import shutil

BASE = Path(__file__).resolve().parent
SOURCE = BASE / '历史样片/开头样片_跨MAC001/public'
TARGET = BASE / '历史样片/章节标题验证/public'
TITLE_TABLE = BASE / '数据/章节标题静态表.json'
TITLE = json.loads(TITLE_TABLE.read_text(encoding='utf-8'))['records'][0]['title']


def main():
    if TARGET.exists():
        raise FileExistsError(TARGET)
    source_scene = (SOURCE / 'game/scene/start.txt').read_text(encoding='utf-8')
    marker = '伊织是高中话剧团的成员。;'
    if source_scene.count(marker) != 1:
        raise ValueError('开头台词不是唯一位置')
    scene = source_scene.replace(marker, f'intro:{TITLE} -delayTime=1800;\n' + marker, 1)
    shutil.copytree(SOURCE, TARGET)
    (TARGET / 'game/scene/start.txt').write_text(scene, encoding='utf-8', newline='\n')
    config = (TARGET / 'game/config.txt').read_text(encoding='utf-8')
    if 'Game_key:ISPtest06;' not in config:
        raise ValueError('样片游戏键不符合预期')
    config = config.replace('Game_key:ISPtest06;', 'Game_key:ISPchapter01;')
    config = config.replace('Game_name:I’s Pure 开头样片;', 'Game_name:I’s Pure 章节标题演示;')
    (TARGET / 'game/config.txt').write_text(config, encoding='utf-8')
    print('Output:', TARGET)


if __name__ == '__main__':
    main()
