"""Paths for the disc build selected for the WebGAL port."""
from pathlib import Path
from functools import cache
import json
import shutil
from tempfile import NamedTemporaryFile

from mac_reader import ROOT
from 本地路径 import V74_RELEASE

RELEASE = V74_RELEASE
PATCH_TEXT = RELEASE / '补丁'
DISC_MAC = RELEASE / '打盘/mac-v6.afs'
DIALOGUE_DATA = Path(__file__).resolve().parents[1] / '数据'
DISC_DIALOGUE = DIALOGUE_DATA / 'v74打盘优先对白.tsv'
ENGINEERING_DIALOGUE = DIALOGUE_DATA / '台词v74原始工程核查_批量拆分修复.tsv'
DISC_OPTIONS = DIALOGUE_DATA / '主线选项打盘优先.tsv'
DISC_WIRING = DIALOGUE_DATA / '全盘主线接线_打盘版.json'
DISC_DIALOGUE_REPAIRS = DIALOGUE_DATA / 'v74打盘剩余对白修复.json'
ENDING_VIDEO = ROOT / '输出-保护边修复/MV/MV_END01.mp4'
ENDING_VIDEO_HD = ROOT / '输出-视频-60fps/MV_END01_手机版_2400x1080_60fps.mp4'


def ending_video_filename(*, hd):
    return 'MV_END01_phone60.mp4' if hd else ENDING_VIDEO.name


def deploy_ending_video(public, *, hd):
    source = ENDING_VIDEO_HD if hd else ENDING_VIDEO
    size = source.stat().st_size
    target = public / 'game/video' / ending_video_filename(hd=hd)
    if not target.is_file() or target.stat().st_size != size:
        target.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(dir=target.parent, delete=False) as file:
            temporary = Path(file.name)
        try:
            shutil.copy2(source, temporary)
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)


@cache
def _dialogue_repairs():
    report = json.loads(DISC_DIALOGUE_REPAIRS.read_text(encoding='utf-8'))
    return {(row['剧本'], int(row['指令偏移'], 16)): row for row in report['rows']}


def restore_disc_dialogue(row, mapping):
    if mapping.resolve() != DISC_DIALOGUE.resolve() or row.get('中文（原对照表）'):
        return row
    repair = _dialogue_repairs().get((row['剧本'], int(row['指令偏移'], 16)))
    if repair is None:
        return row
    for field in ('日文原文', '语音号'):
        if row[field] != repair[field]:
            raise ValueError(f"对白修复的 {field} 已变化: {row['剧本']}:{row['指令偏移']}")
    text = repair['中文']
    return {**row, '中文（原对照表）': text, '匹配状态': '唯一匹配',
            '译文来源': repair['译文来源'], '仅控制行': not text}
