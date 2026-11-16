from pathlib import Path
import argparse
import shutil

BASE = Path(__file__).resolve().parent
source = BASE / '历史样片/自动片段/public'
def main():
    p = argparse.ArgumentParser()
    p.add_argument('--chinese', action='store_true')
    args = p.parse_args()
    target = BASE / ('历史样片/选项中文核查/public' if args.chinese else '历史样片/选项核查/public')
    if target.exists():
        raise FileExistsError(target)
    shutil.copytree(source, target)
    game = target / 'game'
    scene = (BASE / ('数据/原选项v74核查.txt' if args.chinese else '数据/原选项静态核查.txt')).read_text(encoding='utf-8')
    (game / 'scene/start.txt').write_text(scene, encoding='utf-8')
    config = (game / 'config.txt').read_text(encoding='utf-8')
    config = config.replace('Game_name:I’s Pure 自动片段测试;', 'Game_name:I’s Pure 原选项静态核查;')
    config = config.replace('Game_key:ISPtest02;', 'Game_key:ISPtest04;' if args.chinese else 'Game_key:ISPtest03;')
    (game / 'config.txt').write_text(config, encoding='utf-8')
    print('输出:', target)


if __name__ == '__main__':
    main()
