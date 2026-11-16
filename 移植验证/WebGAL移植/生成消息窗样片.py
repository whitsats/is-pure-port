"""用带消息窗节拍的已转换片段生成独立 WebGAL 样片工程。

样片只证明“台词推进次数与消息窗节拍”这一项；背景是手工指定的，
前后的原版演出、立绘与分支均未还原。
"""
from pathlib import Path
import shutil

BASE = Path(__file__).resolve().parent
SOURCE = BASE / '历史样片/样片/public'
TARGET = BASE / '历史样片/消息窗样片/public'
SCENE = BASE / '数据/消息窗样片_MAC005_v74.txt'
VOICES = BASE / '数据/消息窗语音'
SCRIPT = 'MAC_005.bin'
START = '0x1BC4'
NOTICE = (f'以下为原剧本 {SCRIPT} {START} 起的消息窗节奏演示：'
          '背景与前后演出是手工指定的，未还原原版画面。;')


def main():
    if TARGET.exists():
        raise FileExistsError(TARGET)
    if not SCENE.is_file():
        raise FileNotFoundError(f'缺少已转换片段: {SCENE}')
    shutil.copytree(SOURCE, TARGET)
    game = TARGET / 'game'
    body = SCENE.read_text(encoding='utf-8')
    if not body.endswith('\n'):
        body += '\n'
    scene = 'changeBg:is_sample.png -next;\n' + NOTICE + '\n' + body + '片段到此为止，后续指令尚未转换。;\n'
    (game / 'scene/start.txt').write_text(scene, encoding='utf-8')
    copied = []
    for voice in ('VOICE_01124.wav', 'VOICE_01125.wav', 'VOICE_01126.wav', 'VOICE_01127.wav'):
        shutil.copy2(VOICES / voice, game / 'vocal' / voice)
        copied.append(voice)
    config = (game / 'config.txt').read_text(encoding='utf-8')
    config = config.replace('Game_name:I’s Pure 手工测试样片;', 'Game_name:I’s Pure 消息窗样片;')
    config = config.replace('Game_key:ISPtest01;', 'Game_key:ISPtest04;')
    (game / 'config.txt').write_text(config, encoding='utf-8')
    print('输出:', TARGET)
    print('台词:', body.count(';'), '句；语音:', ', '.join(copied))
    print('停止原因见 数据/消息窗样片_MAC005_v74.txt.json；背景为手工指定。')


if __name__ == '__main__':
    main()
