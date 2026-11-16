"""把零初值新游戏转换结果装成 WebGAL 样片。

样片从 MAC_000.bin:0x0C 开始，先经过 0x17 0、quick_save、title_disp 0，
再跨到 MAC_001.bin:0x0C，执行 0x17 1、title_disp 1、vib_set，最后到
0x2344 的首句后续对白。转换报告见 数据/真实新游戏_0x0C至0x2344.txt.json。
"""
from pathlib import Path
import shutil

BASE = Path(__file__).resolve().parent
SOURCE = BASE / '历史样片/开头样片_跨MAC001/public'
TARGET = BASE / '历史样片/真实新游戏样片/public'
SCENES = BASE / '数据/真实新游戏场景'
VOICES = BASE / '数据/真实新游戏语音'
START = 'mac_000_0x00000c.txt'
NEXT = 'mac_001_0x00000c.txt'


def main():
    if TARGET.exists():
        raise FileExistsError(TARGET)
    for name in (START, NEXT):
        if not (SCENES / name).is_file():
            raise FileNotFoundError(SCENES / name)
    shutil.copytree(SOURCE, TARGET)
    game = TARGET / 'game'
    start = (SCENES / START).read_text(encoding='utf-8')
    # 背景是样片观感资产，不参与新游戏状态或指令流。
    start = 'changeBg:is_sample.png -next;\n' + start
    (game / 'scene/start.txt').write_text(start, encoding='utf-8', newline='\n')
    shutil.copy2(SCENES / NEXT, game / 'scene' / NEXT)
    (game / 'vocal').mkdir(exist_ok=True)
    for source in sorted(VOICES.glob('VOICE_*.wav')):
        shutil.copy2(source, game / 'vocal' / source.name)
    config_path = game / 'config.txt'
    config = config_path.read_text(encoding='utf-8')
    config = config.replace('Game_name:I’s Pure 开头样片;',
                            'Game_name:I’s Pure 真实新游戏样片;')
    config = config.replace('Game_key:ISPtest06;', 'Game_key:ISPnewgame01;')
    config = config.replace('Enable_Continue:true;', 'Enable_Continue:false;')
    config_path.write_text(config, encoding='utf-8')
    print('Output:', TARGET)
    print('start:', START, 'next:', NEXT)
    print('voices:', len(list((game / 'vocal').glob('VOICE_*.wav'))))


if __name__ == '__main__':
    main()
