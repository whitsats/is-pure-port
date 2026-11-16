"""核对样本语音 AFS 条目、ADX 副本及 WAV 的 PCM；不验证台词语义。"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import wave

from mac_reader import ROOT
import 输出剩余素材 as source


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--ids-file', type=Path, help='空白分隔的编号文件；批量核验时避免命令行过长')
    p.add_argument('ids', type=int, nargs='*')
    args = p.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    if args.ids_file is not None:
        args.ids = [int(item) for item in args.ids_file.read_text(encoding='utf-8').split()]
    if not args.ids:
        p.error('至少需要一个语音编号（或 --ids-file）')
    if len(set(args.ids)) != len(args.ids):
        p.error('语音编号有重复')
    entries = []
    with source.ISO.open('rb') as iso:
        count = source.entry_count(iso, source.BASES['VOICE'])
        for i in args.ids:
            if not 0 <= i < count:
                raise ValueError(f'语音编号越界: {i}')
            raw = source.read_entry(iso, source.BASES['VOICE'], i)
            adx = ROOT / f'输出-保护边修复/VOICE/adx/VOICE_{i:05}.adx'
            wav = ROOT / f'输出-保护边修复/VOICE/wav/VOICE_{i:05}.wav'
            if raw is None or adx.read_bytes() != raw:
                raise ValueError(f'ADX 与原盘条目不符: {i}')
            pcm = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(adx), '-f', 's16le',
                                  '-acodec', 'pcm_s16le', '-'], capture_output=True, check=True).stdout
            with wave.open(str(wav), 'rb') as w:
                fmt = (w.getnchannels(), w.getframerate(), w.getsampwidth())
                decoded = w.readframes(w.getnframes())
            if fmt != (1, 48000, 2) or decoded != pcm:
                raise ValueError(f'WAV 与重新解码结果不符: {i}')
            entries.append({'id': i, 'source_equal': True, 'pcm_equal': True,
                            'adx_sha256': hashlib.sha256(raw).hexdigest(),
                            'wav_sha256': hashlib.sha256(wav.read_bytes()).hexdigest()})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as f:
        json.dump({'scope': '文件提取链，不验证语音与画面及台词时机', 'entries': entries}, f,
                  ensure_ascii=False, indent=2)
        f.write('\n')
    print('语音文件校验通过:', [e['id'] for e in entries])


if __name__ == '__main__':
    main()
