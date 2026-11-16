"""Extract ETC_010's 15 indexed ADX streams; optionally decode using FFmpeg."""
import argparse
import json
import shutil
import struct
import subprocess
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "输出-保护边修复" / "ETC_bin" / "ETC_010.bin"
OUTPUT = ROOT / "输出-保护边修复" / "ETC_010_音频"


def parse(data):
    if len(data) < 4:
        raise ValueError("Truncated header")
    count = struct.unpack_from("<I", data)[0]
    if count != 15 or len(data) < 4 + 4 * count:
        raise ValueError("Unexpected entry count or truncated table")
    base = (4 + 4 * count + 15) & ~15
    offsets = struct.unpack_from(f"<{count}I", data, 4)
    if offsets[0] != 0 or any(b <= a for a, b in zip(offsets, offsets[1:])):
        raise ValueError("Invalid offsets")
    starts = [base + value * 16 for value in offsets] + [len(data)]
    results = []
    for i, (start, end) in enumerate(zip(starts, starts[1:])):
        if not (base <= start < end <= len(data)):
            raise ValueError(f"Out-of-range entry {i}")
        raw = data[start:end]
        if len(raw) < 40 or raw[:2] != b"\x80\x00" or raw[4:7] != b"\x03\x12\x04":
            raise ValueError(f"Unexpected ADX header at {i}")
        data_start = struct.unpack_from(">H", raw, 2)[0] + 4
        if data_start > len(raw) or b"(c)CRI" not in raw[:data_start]:
            raise ValueError(f"Invalid ADX metadata at {i}")
        rate, samples = struct.unpack_from(">II", raw, 8)
        channels = raw[7]
        if not (channels in (1, 2) and 8000 <= rate <= 192000 and samples > 0):
            raise ValueError(f"Invalid ADX parameters at {i}")
        results.append((raw, {"index": i, "offset": start, "bytes": end - start,
                              "sample_rate": rate, "channels": channels,
                              "header_samples": samples}))
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--adx-only", action="store_true")
    args = parser.parse_args()
    ffmpeg = shutil.which("ffmpeg")
    if not args.adx_only and not ffmpeg:
        raise RuntimeError("FFmpeg not found; use --adx-only to save original streams")
    items = parse(SOURCE.read_bytes())
    args.output.mkdir(parents=True, exist_ok=True)
    names = [args.output / f"ETC_010_{i:02d}.{ext}" for i in range(len(items))
             for ext in (("adx",) if args.adx_only else ("adx", "wav"))]
    if (args.output / "清单.json").exists() or any(p.exists() for p in names):
        raise FileExistsError("Output files already exist; use a new output directory")
    manifest = []
    for raw, info in items:
        stem = f"ETC_010_{info['index']:02d}"
        (args.output / (stem + ".adx")).write_bytes(raw)
        if not args.adx_only:
            target = args.output / (stem + ".wav")
            subprocess.run([ffmpeg, "-v", "error", "-f", "adx", "-i", "pipe:0", "-c:a",
                            "pcm_s16le", "-n", str(target)], input=raw, check=True)
            with wave.open(str(target), "rb") as wav:
                if (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) != (info["sample_rate"], info["channels"], 2):
                    raise ValueError(f"Decoded WAV parameters differ at {stem}")
                info["decoded_samples"] = wav.getnframes()
        manifest.append(info)
        print(stem, info)
    (args.output / "清单.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
