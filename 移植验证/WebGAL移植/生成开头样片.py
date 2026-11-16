"""用带状态/条件/画面指令转换出的两段真实片段生成开头样片。

第一段是 MAC_000 的开头（0x88 起，越过 msg_mode、graph_disp、file_read/file_wait、
SE 段、14 组 fade_start/fade_wait 与 0x730 的 time_wait，在 0x73C 的 ext_goto 跳到
MAC_001 0x0C，读到 0x58 的未实现 reg_calc 为止；time_wait 生成 wait:2000，ext_goto 只记跳转、
不生成跳转命令，SE 与淡入淡出只记账、不映射音频或画面）；
第二段是 MAC_013 的 0x6294 起片段（含两次 bit#26 条件）。两段在转换时都从状态全零开始，
不是连续剧情；背景为手工指定，画面指令只记录、没有 WebGAL 映射。
"""
from pathlib import Path
import re
import shutil

BASE = Path(__file__).resolve().parent
SOURCE = BASE / '历史样片/样片/public'
TARGET = BASE / '历史样片/开头样片_跨MAC001/public'
OPENING = BASE / '数据/开头程序转换_跨MAC001_至0x58_v74.txt'
BRANCH = BASE / '数据/状态分支片段_MAC013_v74.txt'
VOICE_DIRS = [BASE / '数据/开头语音', BASE / '数据/消息窗语音']

INTRO = ('转换器演示：MAC_000 开头 0x88 起 74 句（越过 file_read、SE、淡入淡出、'
         '0x730 的 time_wait 与 0x73C 的 ext_goto，进入 MAC_001 0x0C 至 0x58），后接 MAC_013 片段。;')
INTRO_NOTE = ('两段各自从状态全零开始，不是连续剧情，背景手工指定；time_wait 表达为 2 秒等待，'
              'ext_goto 与淡入淡出只记录、未生成跳转或画面。;')
SEPARATOR = '—— 另一段独立片段：MAC_013 0x6294 ——;'
SEPARATOR_NOTE = '该片段的两次条件都按 bit#26 = 0 判定。;'
OUTRO = '片段到此为止，后续指令尚未转换。;'
VOICE_PATTERN = re.compile(r'-(VOICE_\d{5}\.wav);')


def main():
    if TARGET.exists():
        raise FileExistsError(TARGET)
    for path in (OPENING, BRANCH):
        if not path.is_file():
            raise FileNotFoundError(f'缺少已转换片段: {path}')
    shutil.copytree(SOURCE, TARGET)
    game = TARGET / 'game'
    opening = OPENING.read_text(encoding='utf-8').strip('\n')
    branch = BRANCH.read_text(encoding='utf-8').strip('\n')
    scene = '\n'.join(['changeBg:is_sample.png -next;', INTRO, INTRO_NOTE, opening,
                       SEPARATOR, SEPARATOR_NOTE, branch, OUTRO]) + '\n'
    (game / 'scene/start.txt').write_text(scene, encoding='utf-8')
    voices = sorted({name for name in VOICE_PATTERN.findall(scene)})
    for name in voices:
        source = next((folder / name for folder in VOICE_DIRS if (folder / name).is_file()), None)
        if source is None:
            raise FileNotFoundError(f'找不到语音: {name}')
        shutil.copy2(source, game / 'vocal' / name)
    config = (game / 'config.txt').read_text(encoding='utf-8')
    config = config.replace('Game_name:I’s Pure 手工测试样片;', 'Game_name:I’s Pure 开头样片;')
    config = config.replace('Game_key:ISPtest01;', 'Game_key:ISPtest06;')
    (game / 'config.txt').write_text(config, encoding='utf-8')
    print('输出:', TARGET)
    print('台词行:', sum(1 for line in scene.splitlines() if line.endswith(';')) - 1,
          '（含提示与分隔，背景指令除外）')
    print(f'语音 {len(voices)} 个:', voices[0] if voices else '', '…', voices[-1] if voices else '')


if __name__ == '__main__':
    main()
