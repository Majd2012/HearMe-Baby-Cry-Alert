from __future__ import annotations

import argparse
import json
import math
import random
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

from detector_core import seconds_to_timestamp


def main():
    parser = argparse.ArgumentParser(description="Build reproducible synthetic long-night audio.")
    parser.add_argument("--background", required=True, type=Path)
    parser.add_argument("--cry-dir", required=True, type=Path)
    parser.add_argument("--duration-hours", type=float)
    parser.add_argument("--duration-minutes", type=float)
    parser.add_argument("--number-of-events", type=int, default=8)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--min-cry-duration", type=float, default=6.0)
    parser.add_argument("--max-cry-duration", type=float, default=25.0)
    parser.add_argument("--min-distance-between-events", type=float, default=60.0)
    parser.add_argument("--snr-min-db", type=float, default=-5.0)
    parser.add_argument("--snr-max-db", type=float, default=10.0)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    sample_rate = 16_000
    duration = duration_seconds(args)
    rng = random.Random(args.seed)
    np_rng = np.random.default_rng(args.seed)

    background = load_audio(args.background, sample_rate)
    total_samples = int(round(duration * sample_rate))
    night = tile_to_length(background, total_samples)

    cry_files = sorted(
        file for file in args.cry_dir.iterdir()
        if file.suffix.lower() in {".wav", ".flac", ".ogg", ".aiff", ".aif"}
    )
    if not cry_files:
        raise ValueError("No usable cry files found. Provide legal user-supplied cry audio.")

    events = choose_event_times(
        rng,
        duration,
        args.number_of_events,
        args.min_cry_duration,
        args.max_cry_duration,
        args.min_distance_between_events,
    )
    manifest_events = []
    for event_id, (start_sec, event_duration) in enumerate(events, start=1):
        source = rng.choice(cry_files)
        cry = load_audio(source, sample_rate)
        cry = tile_to_length(cry, int(round(event_duration * sample_rate)))
        snr_db = rng.uniform(args.snr_min_db, args.snr_max_db)
        cry = scale_to_snr(cry, night, int(start_sec * sample_rate), snr_db)
        cry = apply_fades(cry, sample_rate)
        start = int(round(start_sec * sample_rate))
        end = min(total_samples, start + len(cry))
        night[start:end] += cry[: end - start]
        manifest_events.append(
            {
                "event_id": event_id,
                "source_file": str(source),
                "start_sec": start_sec,
                "start_hms": seconds_to_timestamp(start_sec),
                "end_sec": start_sec + (end - start) / sample_rate,
                "end_hms": seconds_to_timestamp(start_sec + (end - start) / sample_rate),
                "duration_sec": (end - start) / sample_rate,
                "snr_db": snr_db,
            }
        )

    peak = float(np.max(np.abs(night))) if len(night) else 0.0
    if peak > 0.99:
        night = night * (0.99 / peak)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    sf.write(args.output, night.astype(np.float32), sample_rate)
    gt_path = args.output.with_name(args.output.stem + "_ground_truth.csv")
    manifest_path = args.output.with_name(args.output.stem + "_manifest.json")
    write_ground_truth(gt_path, manifest_events)
    manifest_path.write_text(
        json.dumps(
            {
                "seed": args.seed,
                "sample_rate": sample_rate,
                "duration_seconds": duration,
                "background": str(args.background),
                "number_of_events": len(manifest_events),
                "events": manifest_events,
                "note": "Uses only user-supplied audio; no audio was downloaded.",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"Wrote {args.output}")
    print(f"Wrote {gt_path}")
    print(f"Wrote {manifest_path}")


def duration_seconds(args) -> float:
    if args.duration_hours is None and args.duration_minutes is None:
        raise ValueError("Provide --duration-hours or --duration-minutes")
    return float(args.duration_hours or 0) * 3600 + float(args.duration_minutes or 0) * 60


def load_audio(path: Path, sample_rate: int) -> np.ndarray:
    data, rate = sf.read(str(path), dtype="float32", always_2d=True)
    mono = np.mean(data, axis=1)
    if rate != sample_rate:
        gcd = math.gcd(rate, sample_rate)
        mono = resample_poly(mono, sample_rate // gcd, rate // gcd).astype(np.float32)
    return np.clip(mono, -1.0, 1.0)


def tile_to_length(audio: np.ndarray, samples: int) -> np.ndarray:
    if len(audio) == 0:
        return np.zeros(samples, dtype=np.float32)
    repeats = int(math.ceil(samples / len(audio)))
    return np.tile(audio, repeats)[:samples].astype(np.float32)


def choose_event_times(rng, duration, count, min_len, max_len, min_gap):
    events = []
    attempts = 0
    while len(events) < count and attempts < count * 1000:
        attempts += 1
        event_duration = rng.uniform(min_len, max_len)
        start = rng.uniform(5.0, max(5.0, duration - event_duration - 5.0))
        candidate = (start, event_duration)
        if all(
            abs(start - other_start) >= min_gap + max(event_duration, other_duration)
            for other_start, other_duration in events
        ):
            events.append(candidate)
    if len(events) < count:
        raise ValueError("Could not place all cry events; reduce count or minimum gap.")
    return sorted(events)


def scale_to_snr(cry, background, start_sample, snr_db):
    segment = background[start_sample : start_sample + len(cry)]
    if len(segment) < len(cry):
        segment = tile_to_length(segment, len(cry))
    bg_rms = rms(segment)
    cry_rms = rms(cry)
    if cry_rms == 0:
        return cry
    target_cry_rms = bg_rms * (10 ** (snr_db / 20.0))
    return cry * (target_cry_rms / cry_rms)


def rms(values):
    return float(np.sqrt(np.mean(np.square(values)))) if len(values) else 0.0


def apply_fades(audio, sample_rate):
    fade_samples = min(len(audio) // 4, int(sample_rate * 0.05))
    if fade_samples <= 1:
        return audio
    fade_in = np.linspace(0, 1, fade_samples)
    fade_out = np.linspace(1, 0, fade_samples)
    audio = audio.copy()
    audio[:fade_samples] *= fade_in
    audio[-fade_samples:] *= fade_out
    return audio


def write_ground_truth(path, events):
    lines = ["event_id,start_sec,end_sec,label"]
    for event in events:
        lines.append(f"{event['event_id']},{event['start_sec']:.3f},{event['end_sec']:.3f},Cry")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
