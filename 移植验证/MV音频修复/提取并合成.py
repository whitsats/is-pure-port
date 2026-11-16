"""Extract PS2 PSS SShd PCM and optionally mux it with the existing video.

Inputs are read-only. Outputs are written to a separate directory and existing
files are never overwritten.  The supported codec and private stream header
are checked strictly against the three I's Pure movie files.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import struct
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
DEFAULT_INPUT = ROOT.parent / "输出-保护边修复" / "MV"
DEFAULT_OUTPUT = ROOT / "输出"
NAMES = ("MV_LG01", "MV_OP01", "MV_END01")


def ps_packets(data: bytes):
    """Walk top-level MPEG-PS packets; never search inside a PES payload."""
    pos = 0
    while pos < len(data):
        if data[pos:pos + 3] != b"\x00\x00\x01" or pos + 4 > len(data):
            raise ValueError(f"Invalid MPEG-PS start code at {pos:#x}")
        stream_id = data[pos + 3]
        if stream_id == 0xBA:
            if pos + 14 > len(data) or data[pos + 4] & 0xC0 != 0x40:
                raise ValueError(f"Unsupported MPEG pack header at {pos:#x}")
            end = pos + 14 + (data[pos + 13] & 7)
            start = pos + 4
        elif stream_id == 0xB9:
            end, start = pos + 4, pos + 4
        elif stream_id == 0xBB or 0xBC <= stream_id <= 0xFF:
            if pos + 6 > len(data):
                raise ValueError(f"Truncated packet header at {pos:#x}")
            size = struct.unpack_from(">H", data, pos + 4)[0]
            if size == 0:
                raise ValueError(f"Unsupported zero-length packet at {pos:#x}")
            start, end = pos + 6, pos + 6 + size
        else:
            raise ValueError(f"Unexpected top-level stream {stream_id:#x} at {pos:#x}")
        if end > len(data):
            raise ValueError(f"Packet at {pos:#x} extends past end of file")
        yield stream_id, pos, data[start:end]
        pos = end
        if stream_id == 0xB9 and pos != len(data):
            raise ValueError("Unexpected data after MPEG program end")


def pes_header(payload: bytes):
    if len(payload) < 3 or payload[0] & 0xC0 != 0x80:
        raise ValueError("Invalid MPEG-2 PES header")
    end = 3 + payload[2]
    if end > len(payload):
        raise ValueError("Truncated PES optional header")
    flags = (payload[1] >> 6) & 3
    pts = None
    if flags in (2, 3):
        if payload[2] < 5:
            raise ValueError("Truncated PTS")
        a, b, c, d, e = payload[3:8]
        if not (a & c & e & 1):
            raise ValueError("Invalid PTS marker bits")
        pts = ((a >> 1 & 7) << 30) | (b << 22) | ((c >> 1) << 15) | (d << 7) | (e >> 1)
    return end, pts


def decode_pss(data: bytes):
    pieces, timestamps = [], []
    video_pts = None
    for stream_id, offset, payload in ps_packets(data):
        if stream_id == 0xE0 and video_pts is None:
            _, video_pts = pes_header(payload)
        if stream_id != 0xBD:
            continue
        start, pts = pes_header(payload)
        if payload[start:start + 4] != b"\xff\xa0\x00\x00":
            raise ValueError(f"Unsupported PSS private stream at {offset:#x}")
        if pts is None:
            raise ValueError(f"Audio packet has no PTS at {offset:#x}")
        timestamps.append(pts)
        pieces.append(payload[start + 4:])
    if not pieces:
        raise ValueError("No supported audio packets")
    encoded = b"".join(pieces)
    if encoded[:4] != b"SShd" or len(encoded) < 40:
        raise ValueError("Missing SShd audio header")
    head_size, codec, rate, channels, interleave = struct.unpack_from("<IIIII", encoded, 4)
    body_header = 8 + head_size
    if head_size != 24 or encoded[body_header:body_header + 4] != b"SSbd":
        raise ValueError("Unsupported SShd/SSbd layout")
    if (codec, rate, channels, interleave) != (1, 48000, 2, 512):
        raise ValueError(f"Unsupported audio format {(codec, rate, channels, interleave)}")
    body_size = struct.unpack_from("<I", encoded, body_header + 4)[0]
    body = encoded[body_header + 8:]
    if len(body) != body_size or body_size % (interleave * channels):
        raise ValueError(f"Audio data length mismatch: expected {body_size}, found {len(body)}")

    # A complete L block precedes each R block.  Packet boundaries do not
    # necessarily coincide with either samples or channel blocks.
    blocks = np.frombuffer(body, dtype="<i2").reshape(-1, 2, interleave // 2)
    pcm = blocks.transpose(0, 2, 1).copy()
    if pcm.transpose(0, 2, 1).copy().tobytes() != body:
        raise ValueError("Channel deinterleave round-trip failed")

    # This stream's packet PTS advances at the byte rate of the complete
    # payload, including the initial 40-byte SShd/SSbd header.
    byte_rate = rate * channels * 2
    elapsed = 0
    residuals = []
    for pts, piece in zip(timestamps, pieces):
        actual = (pts - timestamps[0]) % (1 << 33)
        expected = elapsed * 90000 / byte_rate
        residuals.append(actual - expected)
        elapsed += len(piece)
    max_drift = max(abs(x) for x in residuals)
    if max_drift > 2:
        raise ValueError(f"Audio packet PTS drift exceeds 2 ticks: {max_drift:.3f}")
    if video_pts is None or timestamps[0] != video_pts:
        raise ValueError(f"First audio/video PTS do not match: {timestamps[0]} / {video_pts}")
    return pcm, {
        "audio_packets": len(pieces), "codec": "PCM16LE", "sample_rate": rate,
        "channels": channels, "channel_block_bytes": interleave, "ssbd_bytes": body_size,
        "sample_frames": int(pcm.size // 2), "duration_seconds": float(pcm.size // 2 / rate),
        "first_audio_pts_90khz": timestamps[0], "first_video_pts_90khz": video_pts,
        "max_packet_pts_drift_ticks": max_drift,
        "pss_sha256": hashlib.sha256(data).hexdigest(),
    }


def write_wav(path: Path, pcm: np.ndarray, rate: int):
    with path.open("xb") as output:
        with wave.open(output, "wb") as wav:
            wav.setnchannels(2)
            wav.setsampwidth(2)
            wav.setframerate(rate)
            wav.writeframes(pcm.tobytes())


def main():
    parser = argparse.ArgumentParser(description="从 I's Pure 的 PSS 提取 PCM，并可合成视频")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--stem", choices=NAMES, action="append")
    parser.add_argument("--mux", action="store_true", help="用 ffmpeg 将音频合成到现有 MP4")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    ffmpeg = shutil.which("ffmpeg") if args.mux else None
    if args.mux and not ffmpeg:
        raise RuntimeError("找不到 ffmpeg，无法合成 MP4")
    for stem in args.stem or NAMES:
        src = args.input / f"{stem}.PSS"
        wav = args.output / f"{stem}_音频候选.wav"
        report = args.output / f"{stem}_校验.json"
        mp4 = args.output / f"{stem}_音画候选.mp4"
        destinations = [wav, report] + ([mp4] if args.mux else [])
        if any(p.exists() for p in destinations):
            raise FileExistsError(f"输出文件已存在，未覆盖：{stem}")
        video = args.input / f"{stem}.mp4"
        if args.mux and not video.is_file():
            raise FileNotFoundError(f"找不到已有的视频：{video}")
        pcm, info = decode_pss(src.read_bytes())
        write_wav(wav, pcm, info["sample_rate"])
        report.write_text(json.dumps(info, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if args.mux:
            subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-n", "-i", str(video),
                "-i", str(wav), "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy",
                "-c:a", "aac", "-b:a", "256k", "-shortest", str(mp4)], check=True)
        print(f"{stem}: {info['audio_packets']} 音频包，{info['duration_seconds']:.3f} 秒，"
              f"PTS 最大误差 {info['max_packet_pts_drift_ticks']:.3f}/90000 秒；{wav}")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        print(f"处理失败：{exc}", file=sys.stderr)
        sys.exit(1)
