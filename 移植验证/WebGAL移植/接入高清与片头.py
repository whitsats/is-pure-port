"""Copy the verified opening setup and replace gallery masters in the active build."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil

BASE = Path(__file__).resolve().parent
OPENING = BASE / '历史样片/开屏片头样片/public/game'
MASTER = BASE.parent / '输出-高清化-×4'
ACTIVE = BASE / '新游戏打盘版/public'


def clone_for_hd(destination):
    def copy_asset(source, target):
        # Audio is immutable in both builds and the chapter writer only adds missing names.
        if Path(source).parent.name == 'vocal':
            return os.link(source, target)
        return shutil.copy2(source, target)

    shutil.copytree(ACTIVE, destination, copy_function=copy_asset)
    config = destination / 'game/config.txt'
    config.write_text(re.sub(r'^Game_key:[^;]*;', 'Game_key:ISPv74DiscHD01;',
                             config.read_text(encoding='utf-8'), flags=re.M), encoding='utf-8')
CONFIG_KEYS = {'Opening_video', 'Opening_hold_time', 'Default_Language', 'Title_img', 'Title_bgm',
               'Enable_Appreciation', 'Appreciation_Preset'}


def integrate(public):
    game = public / 'game'
    gallery = json.loads((OPENING / 'appreciation.json').read_text(encoding='utf-8'))
    copies = {name: OPENING / name for name in ('video/MV_OP01_phone60.mp4', 'background/title_op.webp',
                                               'bgm/s_Title.mp3', 'template/UI/Title/title.scss')}
    for item in gallery['cg']:
        filename = item['file']
        copies[f'background/{filename}'] = MASTER / 'EV' / filename
        if 'thumb' in item:
            copies[f"background/{item['thumb']}"] = OPENING / 'background' / item['thumb']
    for item in gallery['bgm']:
        copies[f"bgm/{item['file']}"] = OPENING / 'bgm' / item['file']
    missing = [str(source) for source in copies.values() if not source.is_file()]
    if missing:
        raise ValueError(f'研究产物文件缺失: {missing}')

    updates = {}
    for line in (OPENING / 'config.txt').read_text(encoding='utf-8').splitlines():
        key, _, value = line.partition(':')
        if key in CONFIG_KEYS:
            updates[key] = value
    if set(updates) != CONFIG_KEYS:
        raise ValueError(f'片头配置缺失: {CONFIG_KEYS - updates.keys()}')
    config = game / 'config.txt'
    previous = config.read_text(encoding='utf-8').splitlines()
    settings = [line for line in previous if line.partition(':')[0] not in CONFIG_KEYS]
    settings.extend(f'{key}:{value}' for key, value in updates.items())
    for name, source in copies.items():
        target = game / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    (game / 'appreciation.json').write_text(json.dumps(gallery, ensure_ascii=False, indent=2) + '\n',
                                           encoding='utf-8')
    config.write_text('\n'.join(settings) + '\n', encoding='utf-8')
    return {'cg': len(gallery['cg']), 'music': len(gallery['bgm']), 'copied': len(copies)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--public', type=Path, default=ACTIVE)
    parser.add_argument('--clone', action='store_true', help='创建独立存档的高清样片')
    args = parser.parse_args()
    if args.clone:
        clone_for_hd(args.public)
    print(integrate(args.public))
