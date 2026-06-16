from __future__ import annotations

import csv
import json
import math
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from statistics import mean, median
from typing import Iterable

import numpy as np
import pandas as pd


FRAME_COLUMNS = [
    "frame_index",
    "frame_start_seconds",
    "frame_center_seconds",
    "frame_end_seconds",
    "raw_baby_cry_score",
    "smoothed_baby_cry_score",
    "trigger_state",
    "alert_generated",
]


def seconds_to_timestamp(seconds: float) -> str:
    sign = "-" if seconds < 0 else ""
    seconds = abs(seconds)
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    whole = int(seconds % 60)
    millis = int(round((seconds - math.floor(seconds)) * 1000))
    if millis == 1000:
        whole += 1
        millis = 0
    return f"{sign}{hours:02d}:{minutes:02d}:{whole:02d}.{millis:03d}"


def timestamp_to_seconds(value) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        raise ValueError("empty timestamp")
    try:
        return float(text)
    except ValueError:
        parts = text.split(":")
        if len(parts) != 3:
            raise ValueError(f"invalid timestamp: {value}")
        hours = int(parts[0])
        minutes = int(parts[1])
        seconds = float(parts[2])
        return hours * 3600 + minutes * 60 + seconds


@dataclass(frozen=True)
class GroundTruthEvent:
    event_id: str
    start_sec: float
    end_sec: float
    label: str = "Cry"


@dataclass(frozen=True)
class PolicyConfig:
    aggregation: str = "max"
    decision_window_frames: int = 3
    trigger_threshold: float = 0.30
    clear_threshold: float = 0.20
    persistence_frames: int = 3
    smoothing: str = "rolling_mean"
    smoothing_window_frames: int = 3
    ema_alpha: float = 0.35
    gap_merge_seconds: float = 1.0
    cooldown_seconds: float = 120.0
    rearming_seconds: float = 5.0

    def normalized(self) -> "PolicyConfig":
        clear = min(max(self.clear_threshold, 0.0), self.trigger_threshold)
        return PolicyConfig(
            aggregation=self.aggregation,
            decision_window_frames=max(1, int(self.decision_window_frames)),
            trigger_threshold=min(max(self.trigger_threshold, 0.0), 1.0),
            clear_threshold=clear,
            persistence_frames=max(1, int(self.persistence_frames)),
            smoothing=self.smoothing,
            smoothing_window_frames=max(1, int(self.smoothing_window_frames)),
            ema_alpha=min(max(self.ema_alpha, 0.001), 1.0),
            gap_merge_seconds=max(0.0, self.gap_merge_seconds),
            cooldown_seconds=max(0.0, self.cooldown_seconds),
            rearming_seconds=max(0.0, self.rearming_seconds),
        )


class AlertStateMachine:
    IDLE = "IDLE"
    POSSIBLE_CRY = "POSSIBLE_CRY"
    CONFIRMED_CRY = "CONFIRMED_CRY"
    ALERTED = "ALERTED"
    COOLDOWN = "COOLDOWN"
    REARMING = "REARMING"

    def __init__(self, config: PolicyConfig):
        self.config = config.normalized()
        self.state = self.IDLE
        self.positive_count = 0
        self.last_alert_time = None
        self.low_since = None
        self.transitions: list[dict] = []

    def update(self, timestamp: float, score: float) -> tuple[str, bool]:
        previous = self.state
        alert = False
        is_positive = score >= self.config.trigger_threshold
        is_clear = score <= self.config.clear_threshold

        if is_positive:
            self.positive_count += 1
        else:
            self.positive_count = 0

        self.low_since = self.low_since if is_clear and self.low_since is not None else (
            timestamp if is_clear else None
        )

        if self.state == self.IDLE:
            if is_positive:
                self.state = self.POSSIBLE_CRY
        elif self.state == self.POSSIBLE_CRY:
            if is_clear:
                self.state = self.IDLE
                self.positive_count = 0
            elif self.positive_count >= self.config.persistence_frames:
                self.state = self.CONFIRMED_CRY
        elif self.state == self.CONFIRMED_CRY:
            if self._cooldown_complete(timestamp):
                alert = True
                self.last_alert_time = timestamp
                self.state = self.ALERTED
            else:
                self.state = self.COOLDOWN
        elif self.state == self.ALERTED:
            if is_clear:
                self.state = self.COOLDOWN
        elif self.state == self.COOLDOWN:
            if self._cooldown_complete(timestamp) and self._low_long_enough(timestamp):
                self.state = self.REARMING
        elif self.state == self.REARMING:
            if not is_clear:
                self.state = self.POSSIBLE_CRY if is_positive else self.IDLE
            elif self._low_long_enough(timestamp):
                self.state = self.IDLE
                self.positive_count = 0

        if previous == self.POSSIBLE_CRY and self.state == self.CONFIRMED_CRY:
            if self._cooldown_complete(timestamp):
                alert = True
                self.last_alert_time = timestamp
                self.state = self.ALERTED
            else:
                self.state = self.COOLDOWN

        if previous != self.state:
            self.transitions.append(
                {
                    "timestamp": timestamp,
                    "timestamp_hms": seconds_to_timestamp(timestamp),
                    "from_state": previous,
                    "to_state": self.state,
                    "score": score,
                    "alert_generated": alert,
                }
            )
        return self.state, alert

    def _cooldown_complete(self, timestamp: float) -> bool:
        return self.last_alert_time is None or (
            timestamp - self.last_alert_time >= self.config.cooldown_seconds
        )

    def _low_long_enough(self, timestamp: float) -> bool:
        return self.low_since is not None and (
            timestamp - self.low_since >= self.config.rearming_seconds
        )


def load_config(path: Path | None) -> dict:
    default_path = Path(__file__).with_name("config.default.json")
    config = json.loads(default_path.read_text(encoding="utf-8"))
    if path:
        override = json.loads(Path(path).read_text(encoding="utf-8"))
        config = deep_update(config, override)
    return config


def deep_update(base: dict, override: dict) -> dict:
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_update(result[key], value)
        else:
            result[key] = value
    return result


def read_ground_truth(path: Path | None, audio_duration: float | None = None) -> list[GroundTruthEvent]:
    if not path:
        return []
    rows = []
    with Path(path).open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        required = {"event_id", "start_sec", "end_sec", "label"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"ground-truth CSV missing columns: {sorted(missing)}")
        for row in reader:
            if row["label"].strip().lower() != "cry":
                continue
            start = timestamp_to_seconds(row["start_sec"])
            end = timestamp_to_seconds(row["end_sec"])
            if start >= end:
                raise ValueError(f"event {row['event_id']} start must be smaller than end")
            if audio_duration is not None and end > audio_duration + 1e-6:
                raise ValueError(f"event {row['event_id']} exceeds audio duration")
            rows.append(GroundTruthEvent(row["event_id"], start, end, row["label"]))
    rows.sort(key=lambda item: item.start_sec)
    return rows


def normalize_ground_truth(events: list[GroundTruthEvent]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "event_id": event.event_id,
                "start_sec": event.start_sec,
                "start_hms": seconds_to_timestamp(event.start_sec),
                "end_sec": event.end_sec,
                "end_hms": seconds_to_timestamp(event.end_sec),
                "label": event.label,
            }
            for event in events
        ]
    )


def aggregate_scores(scores: Iterable[float], method: str) -> float:
    values = np.array(list(scores), dtype=np.float32)
    if len(values) == 0:
        return 0.0
    if method == "max":
        return float(np.max(values))
    if method == "mean":
        return float(np.mean(values))
    if method == "median":
        return float(np.median(values))
    if method == "p90":
        return float(np.percentile(values, 90))
    if method == "topk_mean":
        k = min(3, len(values))
        return float(np.mean(np.sort(values)[-k:]))
    raise ValueError(f"unknown aggregation method: {method}")


def apply_policy(raw_frames: pd.DataFrame, config: PolicyConfig) -> tuple[pd.DataFrame, pd.DataFrame]:
    config = config.normalized()
    scores = raw_frames["raw_baby_cry_score"].astype(float).to_numpy()
    smoothed = smooth_scores(scores, config)
    state_machine = AlertStateMachine(config)
    states = []
    alerts = []
    windowed_scores = []

    for index, row in raw_frames.iterrows():
        start = max(0, index - config.decision_window_frames + 1)
        aggregated = aggregate_scores(smoothed[start : index + 1], config.aggregation)
        state, alert = state_machine.update(float(row["frame_center_seconds"]), aggregated)
        states.append(state)
        alerts.append(alert)
        windowed_scores.append(aggregated)

    frames = raw_frames.copy()
    frames["smoothed_baby_cry_score"] = windowed_scores
    frames["trigger_state"] = states
    frames["alert_generated"] = alerts
    return frames, pd.DataFrame(state_machine.transitions)


def smooth_scores(scores: np.ndarray, config: PolicyConfig) -> np.ndarray:
    method = config.smoothing
    if method == "none":
        return scores.astype(float)
    if method == "rolling_mean":
        return pd.Series(scores).rolling(config.smoothing_window_frames, min_periods=1).mean().to_numpy()
    if method == "rolling_median":
        return pd.Series(scores).rolling(config.smoothing_window_frames, min_periods=1).median().to_numpy()
    if method == "ema":
        values = []
        previous = None
        for score in scores:
            previous = float(score) if previous is None else (
                config.ema_alpha * float(score) + (1.0 - config.ema_alpha) * previous
            )
            values.append(previous)
        return np.array(values)
    raise ValueError(f"unknown smoothing method: {method}")


def evaluate_events(
    frames: pd.DataFrame,
    ground_truth: list[GroundTruthEvent],
    audio_duration: float,
    tolerance_seconds: float,
    late_alert_seconds: float,
    config_name: str,
) -> tuple[pd.DataFrame, dict]:
    alerts = frames[frames["alert_generated"] == True]  # noqa: E712
    matched_alert_indices: set[int] = set()
    detected_rows = []
    true_positive = 0
    false_negative = 0
    early_alerts = 0
    redundant_alerts = 0
    latencies = []

    for event in ground_truth:
        event_frames = frames[
            (frames["frame_center_seconds"] >= event.start_sec)
            & (frames["frame_center_seconds"] <= event.end_sec)
        ]
        crossing = event_frames[
            event_frames["smoothed_baby_cry_score"] >= frames.attrs.get("trigger_threshold", 0.30)
        ]
        valid_alerts = alerts[
            (alerts["frame_center_seconds"] >= event.start_sec - tolerance_seconds)
            & (alerts["frame_center_seconds"] <= event.end_sec)
        ]
        result = "missed"
        first_alert = None
        if not valid_alerts.empty:
            first_alert = valid_alerts.iloc[0]
            matched_alert_indices.add(int(first_alert.name))
            duplicate_count = max(0, len(valid_alerts) - 1)
            redundant_alerts += duplicate_count
            true_positive += 1
            latency = float(first_alert["frame_center_seconds"]) - event.start_sec
            latencies.append(latency)
            if latency < 0:
                early_alerts += 1
                result = "early"
            elif latency > late_alert_seconds:
                result = "late"
            else:
                result = "correct"
        else:
            false_negative += 1
            latency = math.nan

        detected_rows.append(
            {
                "event_id": event.event_id,
                "ground_truth_start": event.start_sec,
                "ground_truth_start_hms": seconds_to_timestamp(event.start_sec),
                "ground_truth_end": event.end_sec,
                "ground_truth_end_hms": seconds_to_timestamp(event.end_sec),
                "detected_start": float(crossing.iloc[0]["frame_center_seconds"]) if not crossing.empty else math.nan,
                "first_score_crossing_hms": seconds_to_timestamp(float(crossing.iloc[0]["frame_center_seconds"])) if not crossing.empty else "",
                "alert_timestamp": float(first_alert["frame_center_seconds"]) if first_alert is not None else math.nan,
                "alert_timestamp_hms": seconds_to_timestamp(float(first_alert["frame_center_seconds"])) if first_alert is not None else "",
                "detected_end": estimate_detected_end(frames, event.end_sec),
                "peak_score": float(event_frames["smoothed_baby_cry_score"].max()) if not event_frames.empty else math.nan,
                "mean_score": float(event_frames["smoothed_baby_cry_score"].mean()) if not event_frames.empty else math.nan,
                "latency": latency,
                "result_type": result,
                "selected_parameter_configuration": config_name,
            }
        )

    false_positive = 0
    for index, alert in alerts.iterrows():
        if int(index) in matched_alert_indices:
            continue
        ts = float(alert["frame_center_seconds"])
        inside_any = any(event.start_sec - tolerance_seconds <= ts <= event.end_sec for event in ground_truth)
        if not inside_any:
            false_positive += 1

    precision = true_positive / (true_positive + false_positive) if true_positive + false_positive else 0.0
    recall = true_positive / len(ground_truth) if ground_truth else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if precision + recall else 0.0
    duration_hours = audio_duration / 3600 if audio_duration else 0.0
    latencies_clean = [value for value in latencies if not math.isnan(value)]
    metrics = {
        "event_precision": precision,
        "event_recall": recall,
        "event_f1": f1,
        "true_positive_events": true_positive,
        "false_positive_alerts": false_positive,
        "missed_crying_events": false_negative,
        "false_alerts_per_hour": false_positive / duration_hours if duration_hours else 0.0,
        "redundant_alerts_per_crying_event": redundant_alerts / len(ground_truth) if ground_truth else 0.0,
        "mean_detection_latency": mean(latencies_clean) if latencies_clean else math.nan,
        "median_detection_latency": median(latencies_clean) if latencies_clean else math.nan,
        "p95_detection_latency": float(np.percentile(latencies_clean, 95)) if latencies_clean else math.nan,
        "min_latency": min(latencies_clean) if latencies_clean else math.nan,
        "max_latency": max(latencies_clean) if latencies_clean else math.nan,
        "early_alerts": early_alerts,
        "average_early_alert_lead_time": abs(mean([x for x in latencies_clean if x < 0])) if any(x < 0 for x in latencies_clean) else 0.0,
        "alerts_within_1s_percent": within_percent(latencies_clean, 1),
        "alerts_within_2s_percent": within_percent(latencies_clean, 2),
        "alerts_within_3s_percent": within_percent(latencies_clean, 3),
        "alerts_within_5s_percent": within_percent(latencies_clean, 5),
        "total_analyzed_audio_duration": audio_duration,
    }
    return pd.DataFrame(detected_rows), metrics


def estimate_detected_end(frames: pd.DataFrame, event_end: float) -> float:
    after = frames[frames["frame_center_seconds"] >= event_end]
    below = after[after["trigger_state"].isin([AlertStateMachine.IDLE, AlertStateMachine.REARMING])]
    return float(below.iloc[0]["frame_center_seconds"]) if not below.empty else math.nan


def within_percent(latencies: list[float], seconds: float) -> float:
    if not latencies:
        return 0.0
    return 100.0 * sum(0 <= item <= seconds for item in latencies) / len(latencies)


def frame_level_metrics(frames: pd.DataFrame, ground_truth: list[GroundTruthEvent]) -> dict:
    if frames.empty:
        return {}
    labels = []
    for ts in frames["frame_center_seconds"].astype(float):
        labels.append(any(event.start_sec <= ts <= event.end_sec for event in ground_truth))
    preds = frames["smoothed_baby_cry_score"].astype(float) >= frames.attrs.get("trigger_threshold", 0.30)
    tp = int(sum(bool(p) and bool(y) for p, y in zip(preds, labels)))
    tn = int(sum((not bool(p)) and (not bool(y)) for p, y in zip(preds, labels)))
    fp = int(sum(bool(p) and (not bool(y)) for p, y in zip(preds, labels)))
    fn = int(sum((not bool(p)) and bool(y) for p, y in zip(preds, labels)))
    return {
        "frame_tp": tp,
        "frame_tn": tn,
        "frame_fp": fp,
        "frame_fn": fn,
        "frame_precision": tp / (tp + fp) if tp + fp else 0.0,
        "frame_recall": tp / (tp + fn) if tp + fn else 0.0,
        "frame_accuracy": (tp + tn) / max(1, tp + tn + fp + fn),
    }


class YamNetScorer:
    def __init__(self, model_path: Path, class_map_path: Path):
        self.model_path = Path(model_path)
        self.class_index = find_baby_cry_index(class_map_path)
        self.interpreter = self._load_interpreter()
        self.input_details = self.interpreter.get_input_details()
        self.output_details = self.interpreter.get_output_details()

    def _load_interpreter(self):
        try:
            import tensorflow as tf

            interpreter = tf.lite.Interpreter(model_path=str(self.model_path))
        except Exception:
            try:
                from tflite_runtime.interpreter import Interpreter

                interpreter = Interpreter(model_path=str(self.model_path))
            except Exception as exc:
                raise RuntimeError(
                    "Install tensorflow or tflite-runtime to run real YAMNet inference."
                ) from exc
        interpreter.allocate_tensors()
        return interpreter

    def score_frame(self, frame: np.ndarray) -> float:
        waveform = frame.astype(np.float32)
        self.interpreter.set_tensor(self.input_details[0]["index"], waveform)
        self.interpreter.invoke()
        output = self.interpreter.get_tensor(self.output_details[0]["index"])
        values = np.asarray(output).reshape(-1)
        if self.class_index >= len(values):
            raise IndexError(f"class index {self.class_index} outside model output of {len(values)}")
        return float(values[self.class_index])


def find_baby_cry_index(class_map_path: Path) -> int:
    with Path(class_map_path).open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        index_key = "index" if "index" in (reader.fieldnames or []) else "class_index"
        for row in reader:
            label = (row.get("display_name") or row.get("label") or "").lower()
            if "baby cry" in label or "infant cry" in label:
                return int(row[index_key])
    raise ValueError(f"Baby Cry / Infant Cry class not found in {class_map_path}")


def build_frames_from_audio(audio_path: Path, config: dict, progress=True) -> tuple[pd.DataFrame, float, float]:
    import soundfile as sf
    from scipy.signal import resample_poly
    from tqdm import tqdm

    sample_rate = int(config["sample_rate"])
    frame_samples = int(config["yamnet_frame_samples"])
    hop_samples = int(config["yamnet_hop_samples"])
    model_path = (Path(__file__).parent / config["model_path"]).resolve()
    class_map_path = (Path(__file__).parent / config["class_map_path"]).resolve()
    scorer = YamNetScorer(model_path, class_map_path)

    rows = []
    start_time = time.perf_counter()
    frame_index = 0
    sample_cursor = 0
    carry = np.array([], dtype=np.float32)
    info = sf.info(str(audio_path))
    total_input_frames = info.frames
    audio_duration = total_input_frames / info.samplerate
    block_size = max(info.samplerate * 30, frame_samples)

    with sf.SoundFile(str(audio_path)) as handle:
        total_blocks = max(1, math.ceil(total_input_frames / block_size))
        progress_bar = tqdm(total=total_blocks, desc="YAMNet frames") if progress else None
        while True:
            block = handle.read(block_size, dtype="float32", always_2d=True)
            if block.size == 0:
                break
            mono = np.mean(block, axis=1)
            if handle.samplerate != sample_rate:
                gcd = math.gcd(handle.samplerate, sample_rate)
                mono = resample_poly(mono, sample_rate // gcd, handle.samplerate // gcd).astype(np.float32)
            data = np.concatenate([carry, mono])
            local_offset = sample_cursor - len(carry)
            frame_start = 0
            while frame_start + frame_samples <= len(data):
                frame = data[frame_start : frame_start + frame_samples]
                absolute_start_sample = local_offset + frame_start
                score = scorer.score_frame(np.clip(frame, -1.0, 1.0))
                start_sec = absolute_start_sample / sample_rate
                end_sec = (absolute_start_sample + frame_samples) / sample_rate
                rows.append(
                    {
                        "frame_index": frame_index,
                        "frame_start_seconds": start_sec,
                        "frame_center_seconds": (start_sec + end_sec) / 2.0,
                        "frame_end_seconds": end_sec,
                        "raw_baby_cry_score": score,
                    }
                )
                frame_index += 1
                frame_start += hop_samples
            carry = data[max(0, frame_start) :]
            sample_cursor += len(mono)
            if progress_bar:
                progress_bar.update(1)
        if progress_bar:
            progress_bar.close()

    elapsed = time.perf_counter() - start_time
    return pd.DataFrame(rows), audio_duration, elapsed


def write_json(path: Path, data: dict):
    path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")


def policy_to_dict(policy: PolicyConfig) -> dict:
    return asdict(policy.normalized())
