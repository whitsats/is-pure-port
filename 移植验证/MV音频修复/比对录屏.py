"""Compare a PCSX2 recording against decoded WAV using normalized correlation.

The recording may start before the movie. First search its whole soundtrack for
one distinctive movie segment, then check other segments near that offset.
Correlation is evidence of matching content, not a substitute for a listening
and visual lip-sync review. The input recording is read-only.
"""
import argparse
import json
import subprocess
import wave
from pathlib import Path

import numpy as np
from scipy.signal import fftconvolve

RATE = 48000
ROOT = Path(__file__).resolve().parent


def read_reference(path):
    with wave.open(str(path), "rb") as w:
        if (w.getnchannels(), w.getsampwidth(), w.getframerate()) != (2, 2, RATE):
            raise ValueError("Expected 48 kHz, 16-bit stereo WAV")
        a = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").reshape(-1, 2)
        return a.astype(np.float32).mean(axis=1) / 32768


def read_recording(path):
    command = ["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:a:0",
               "-ac", "1", "-ar", str(RATE), "-f", "f32le", "pipe:1"]
    data = subprocess.run(command, check=True, stdout=subprocess.PIPE).stdout
    return np.frombuffer(data, dtype="<f4")


def match(capture, template, search_start=0, search_end=None):
    template = np.asarray(template, dtype=np.float32)
    template = template - template.mean()
    tnorm = float(np.linalg.norm(template))
    if tnorm < 0.01:
        raise ValueError("Reference segment is silent")
    search_end = len(capture) if search_end is None else min(len(capture), search_end)
    window = np.asarray(capture[search_start:search_end], dtype=np.float32)
    if len(window) < len(template):
        raise ValueError("Recording is shorter than the search region")
    products = fftconvolve(window, template[::-1], mode="valid")
    square_sum = np.empty(len(window) + 1, dtype=np.float64)
    square_sum[0] = 0
    np.cumsum(window.astype(np.float64) ** 2, out=square_sum[1:])
    energy = square_sum[len(template):] - square_sum[:-len(template)]
    scores = np.divide(products, np.sqrt(np.maximum(energy, 1e-20)) * tnorm,
                       out=np.zeros_like(products), where=energy > 1e-10)
    index = int(np.argmax(np.abs(scores)))
    return {"recording_second": (search_start + index) / RATE, "correlation": float(scores[index])}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("recording", type=Path)
    parser.add_argument("--stem", choices=("MV_LG01", "MV_OP01", "MV_END01"), default="MV_OP01")
    parser.add_argument("--reference", type=Path, help="提取脚本输出的 48 kHz 立体声 WAV")
    args = parser.parse_args()
    capture = read_recording(args.recording)
    reference = args.reference or ROOT.parent / "输出-保护边修复" / "MV" / f"{args.stem}.wav"
    ref = read_reference(reference)
    anchor_second = 1.0 if args.stem == "MV_LG01" else 8.0
    length = int(0.75 * RATE)
    start = int(anchor_second * RATE)
    anchor = match(capture, ref[start:start + length])
    offset = anchor["recording_second"] - anchor_second
    moments = [0.2, 1.0, 2.0] if args.stem == "MV_LG01" else [2.0, 8.0, 30.0, 60.0, 80.0]
    checks = []
    for t in moments:
        begin = int(t * RATE)
        estimate = int((offset + t) * RATE)
        search_start = max(0, estimate - RATE // 2)
        search_end = min(len(capture), estimate + RATE // 2 + length)
        try:
            found = match(capture, ref[begin:begin + length], search_start, search_end)
            checks.append({"movie_second": t, **found,
                           "offset_error_seconds": found["recording_second"] - t - offset})
        except ValueError as exc:
            checks.append({"movie_second": t, "error": str(exc)})
    print(json.dumps({"movie": args.stem, "recording": str(args.recording),
                      "recording_duration": len(capture) / RATE,
                      "anchor_movie_second": anchor_second, "anchor": anchor,
                      "recording_movie_offset_seconds": offset, "checks": checks},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
