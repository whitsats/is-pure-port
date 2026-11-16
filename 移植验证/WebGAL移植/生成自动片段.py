"""生成两个已提取对白片段的技术演示；两组之间不代表完整原版演出。"""
from pathlib import Path
import shutil

BASE = Path(__file__).resolve().parent
source = BASE / '历史样片/样片/public'
target = BASE / '历史样片/自动片段/public'


def main():
    if target.exists():
        raise FileExistsError(target)
    shutil.copytree(source, target)
    game = target / 'game'
    first = (BASE / '数据/开头自动转换.txt').read_text(encoding='utf-8')
    second = (BASE / '数据/开头自动转换_带语音.txt').read_text(encoding='utf-8')
    scene = 'changeBg:is_sample.png -next;\n' + first + second + '自动提取的测试片段结束。;\n'
    (game / 'scene/start.txt').write_text(scene, encoding='utf-8')
    for filename in ('VOICE_00000.wav', 'VOICE_00001.wav'):
        shutil.copy2(BASE / '数据/语音片段' / filename, game / 'vocal' / filename)
    config = (game / 'config.txt').read_text(encoding='utf-8')
    config = config.replace('Game_name:I’s Pure 手工测试样片;', 'Game_name:I’s Pure 自动片段测试;')
    config = config.replace('Game_key:ISPtest01;', 'Game_key:ISPtest02;')
    (game / 'config.txt').write_text(config, encoding='utf-8')
    print('输出:', target)
    print('两组对白由原剧本提取；组间演出未实现，背景手工指定，不能视为完整移植。')


if __name__ == '__main__':
    main()
