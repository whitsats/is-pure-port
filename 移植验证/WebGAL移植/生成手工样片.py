"""在独立 public 目录生成 WebGAL 手工样片，不改原版文件或引擎内置示例。"""
from pathlib import Path
import shutil

BASE = Path(__file__).resolve().parent
ROOT = BASE.parent
SOURCE_PUBLIC = BASE / 'engine/packages/webgal/public'
PUBLIC = BASE / '历史样片/样片/public'
GAME = PUBLIC / 'game'


def main():
    if PUBLIC.exists():
        raise FileExistsError(f'拒绝覆盖现有样片：{PUBLIC}')
    shutil.copytree(SOURCE_PUBLIC, PUBLIC)
    shutil.copy2(ROOT / '输出-保护边修复/EV/EV_0000.png', GAME / 'background/is_sample.png')
    shutil.copy2(ROOT / '输出-保护边修复/VOICE/wav/VOICE_00000.wav', GAME / 'vocal/is_voice_00000.wav')
    scene = '''changeBg:is_sample.png -next;
伊织是高中话剧团的成员。;
平时文静内敛的她，站上舞台之后不知道会变成什么模样呢。;
伊织:能借着演戏去体验各种不同的人生，我觉得很开心 -is_voice_00000.wav;
穿着泳衣的伊织这样说道。;
; 以下是功能测试选项，不代表原版这里有选项。
choose:测试选项一:sample_a|测试选项二:sample_b;
label:sample_a;
setVar:sample_choice=1;
这是一条测试分支。;
jumpLabel:sample_end;
label:sample_b;
setVar:sample_choice=2;
这是另一条测试分支。;
label:sample_end;
样片到此结束。;
'''
    (GAME / 'scene/start.txt').write_text(scene, encoding='utf-8')
    config = (GAME / 'config.txt').read_text(encoding='utf-8')
    config = config.replace('Game_name:欢迎使用WebGAL！;', 'Game_name:I’s Pure 手工测试样片;')
    config = config.replace('Game_key:0f87dstRg;', 'Game_key:ISPtest01;')
    (GAME / 'config.txt').write_text(config, encoding='utf-8')
    print('生成:', PUBLIC)
    print('画面参考用户提供的原版截图；语音对应关系仍待听核，选择仅用于测试。')


if __name__ == '__main__':
    main()
