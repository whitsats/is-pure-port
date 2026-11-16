"""Bind original graph_disp records to equal-aspect HD stage assets."""
import csv
import json
from pathlib import Path
import shutil
import struct
import subprocess

from mac_display import parse_graph_disp, resolve_graph_records
from mac_release import ROOT

MASTER = ROOT / '输出-高清化-×4'
NATIVE_SCALE = 1440 / 448  # current WebGAL stage height / PS2 logical canvas height
# 0x11C368 保存 graph_disp 的标志字节。BG/EV 回调在该值为 0 时调用
# 0x12B9F0 释放原盘的槽位 1～17（0x11B9F4～0x11BAA0）。
# WebGAL 接入了其中 1～4 层，第 4 层显示为消息窗头像。
DISC_FIGURE_LAYERS = (1, 2, 3, 4)
EV_FIGURE_CLEAR_COMMANDS = (1, 2, 3)

# 原盘没有 bgm_* 指令：长音乐是从 SE 通道播放的 SE.AFS 条目。只有这 8 条
# 时长超过 90 秒、谱平坦度低，已由 `BGM_music/清单.txt` 判读为音乐并转成 mp3。
# 键是 `file_read` 的 0x50xx 低 12 位；文件名来自工程里已有的转码产物。
BGM_BY_SE_INDEX = {
    136: 'IS_Pure_BGM_SE_00136.mp3',
    143: 'IS_Pure_BGM_SE_00143.mp3',
    145: 'IS_Pure_BGM_SE_00145.mp3',
    146: 'IS_Pure_BGM_SE_00146.mp3',
    148: 'IS_Pure_BGM_SE_00148.mp3',
    149: 'IS_Pure_BGM_SE_00149.mp3',
    151: 'IS_Pure_BGM_SE_00151.mp3',
    152: 'IS_Pure_BGM_SE_00152.mp3',
}

# 原盘没有曲名表（INIT 只有 BGM01…BGM20 这类槽位名，社区 gamerip 也只有 Track N），
# 鉴赏界面显示「曲目NN」，原始 SE 编号保留在文件名中。
BGM_PORT_LABELS = {136: '曲目01', 143: '曲目02', 145: '曲目03', 146: '曲目04',
                   148: '曲目05', 149: '曲目06', 151: '曲目07', 152: '曲目08'}

# These channel-2 tracks have whole-file loop markers in the extracted ADX.
AMBIENCE_INDICES = frozenset({134, 135, 137, 138, 139, 140, 141, 142, 144, 147, 150})
AMBIENCE_CHANNEL = 2
STOP_AMBIENCE = f'playEffect:none -id=disc-se-{AMBIENCE_CHANNEL} -next;'


def track_name(index):
    return BGM_PORT_LABELS.get(index, f'曲目{index}')


def source_sizes():
    with (MASTER / '母版清单.csv').open(encoding='utf-8-sig', newline='') as file:
        return {f"{r['类别']}/{r['文件']}": r['源尺寸'] for r in csv.DictReader(file)}


def deploy_asset(asset, target):
    if asset.startswith('BGM_music/'):
        if target.exists():
            return False
        source = ROOT / '输出-保护边修复' / asset
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix('.tmp')
        subprocess.run(['ffmpeg', '-nostdin', '-loglevel', 'error', '-y', '-i', str(source),
                        '-c:a', 'libopus', '-b:a', '96k', '-f', 'ogg', str(temporary)], check=True)
        temporary.replace(target)
        return True
    source = MASTER / asset
    if source.parent.name == 'BG':
        from PIL import Image

        try:
            with Image.open(source) as image:
                background = crop_wide_background(image)
        except (OSError, SyntaxError):
            if source.name != 'BG_0152.png':
                raise
            # This master has a damaged IDAT stream. Recover from the extracted native asset.
            with Image.open(ROOT / '输出-保护边修复' / asset) as image:
                cropped = crop_wide_background(image)
                if cropped is None:
                    raise ValueError(f'无法恢复背景 {asset}')
                background = cropped.resize((cropped.width * 4, cropped.height * 4), Image.Resampling.LANCZOS)
        if background is not None:
            if target.exists():
                with Image.open(target) as existing:
                    if existing.size == background.size:
                        return False
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_suffix('.png.tmp')
            background.save(temporary, format='PNG', compress_level=3)
            temporary.replace(target)
            return True
    if target.exists():
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return True


def crop_wide_background(image):
    bounds = image.getchannel('A').getbbox()
    # Confine trimming to full-width backgrounds with a short opaque band.
    if bounds and bounds[0] == 0 and bounds[2] == image.width and (bounds[3] - bounds[1]) / image.width <= 0.46:
        return image.crop(bounds)
    return None


def commands_for(script, commands, sizes):
    data = (ROOT / '输出-保护边修复/MAC' / script).read_bytes()
    emitted, assets = {}, set()
    staged_code = None
    volumes = {}
    for command in commands:
        name = command['name']
        raw = bytes.fromhex(command['raw_hex'])
        if name == 'file_read':
            staged_code = raw[2] | (raw[3] << 8)
            continue
        if name == 'se_vol':
            volumes[raw[1]] = raw[2]
            continue
        if name == 'se_set':
            channel = raw[1]
            if channel != AMBIENCE_CHANNEL or staged_code is None or staged_code >> 12 != 5:
                continue
            index = staged_code & 0xFFF
            track = BGM_BY_SE_INDEX.get(index)
            if track:
                emitted[command['offset']] = [
                    STOP_AMBIENCE,
                    f'bgm:{track} -volume=80 -unlockname={track_name(index)} -next;']
            elif index in AMBIENCE_INDICES:
                path = f'disc-se/SE_{index:05d}.opus'
                volume = round(volumes.get(channel, 128) * 100 / 255)
                emitted[command['offset']] = [
                    'bgm:none -next;',
                    f'playEffect:{path} -id=disc-se-{channel} -volume={volume} -next;',
                ]
                assets.add((f'BGM_music/BGM_se{index:05d}.wav', f'vocal/{path}'))
            else:
                emitted[command['offset']] = [STOP_AMBIENCE, 'bgm:none -next;']
            continue
        if name == 'se_del':
            if raw[1] == AMBIENCE_CHANNEL:
                emitted[command['offset']] = [STOP_AMBIENCE, 'bgm:none -next;']
            continue
        if name != 'graph_disp':
            continue
        parsed = parse_graph_disp(bytes.fromhex(command['raw_hex']))
        records = resolve_graph_records(data, parsed['blob_offset'], parsed['count'])
        lines = []
        for record in records:
            group = record['group_name']
            frame = bytes.fromhex(record['raw_hex'])
            layer = frame[0]
            asset = record['candidate']
            if asset and (asset not in sizes or not (MASTER / asset).is_file()):
                raise ValueError(f'{script}:{command["offset"]:#x} 缺高清资源: {asset}')
            if group in ('BG', 'EV') and asset:
                path = f'disc-hd/{Path(asset).name}'
                unlock = f' -unlockname={Path(asset).stem}' if group == 'EV' else ''
                clear = ''
                ev_layers = ()
                if parsed['flag'] == 0:
                    # Retain the existing EV clear commands and their sentence positions.
                    ev_layers = EV_FIGURE_CLEAR_COMMANDS if group == 'EV' else ()
                    figure_ids = ','.join(f'ps2Layer{n}' for n in DISC_FIGURE_LAYERS if n not in ev_layers)
                    clear = f' -clearFigureIds={figure_ids}'
                lines.append(f'changeBg:{path}{unlock}{clear} -duration=0 -next;')
                for layer_number in ev_layers:
                    lines.append(f'changeFigure:none -id=ps2Layer{layer_number} -clear -duration=0 -next;')
                assets.add((asset, f'background/{path}'))
            elif group == 'CHR':
                key = f'ps2Layer{layer}'
                if asset is None:
                    lines.append(f'changeFigure:none -id={key} -clear -duration=0 -next;')
                    continue
                path = f'disc-hd/{Path(asset).name}'
                x, y = struct.unpack_from('<hh', frame, 8)
                portrait = sizes[asset] == '140x130'
                factor = round(130 / 448, 6) if portrait else 1
                offset_y = -y - 224 if portrait else -y
                transform = json.dumps({'position': {'x': round((x - 320) * NATIVE_SCALE),
                                                       'y': round(offset_y * NATIVE_SCALE)},
                                        'scale': {'x': factor, 'y': factor}}, separators=(',', ':'))
                lines.append(f'changeFigure:{path} -id={key} -transform={transform} -duration=0 -next;')
                assets.add((asset, f'figure/{path}'))
        if lines:
            emitted[command['offset']] = lines
    return emitted, assets
