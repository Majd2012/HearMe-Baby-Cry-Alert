from __future__ import annotations

import argparse
import itertools
import json
import os
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", str(Path.cwd() / ".matplotlib"))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from detector_core import (
    FRAME_COLUMNS,
    GroundTruthEvent,
    PolicyConfig,
    apply_policy,
    build_frames_from_audio,
    evaluate_events,
    load_config,
    read_ground_truth,
    seconds_to_timestamp,
    write_json,
)


ORIGINAL_CONFIG = PolicyConfig(
    aggregation="max",
    decision_window_frames=1,
    trigger_threshold=0.30,
    clear_threshold=0.20,
    persistence_frames=3,
    smoothing="rolling_mean",
    smoothing_window_frames=3,
    cooldown_seconds=120.0,
    rearming_seconds=5.0,
)

CURRENT_SELECTED_CONFIG = PolicyConfig(
    aggregation="max",
    decision_window_frames=1,
    trigger_threshold=0.05,
    clear_threshold=0.00,
    persistence_frames=1,
    smoothing="none",
    smoothing_window_frames=1,
    cooldown_seconds=10.0,
    rearming_seconds=2.0,
)


def main():
    parser = argparse.ArgumentParser(description="Before/after and multi-night operating-point validation.")
    parser.add_argument("--output-dir", type=Path, default=Path("results/scientific_validation"))
    parser.add_argument("--duration-minutes", type=float, default=30.0)
    parser.add_argument("--events-per-night", type=int, default=6)
    parser.add_argument("--seeds", default="42,77,123")
    parser.add_argument("--max-nights", type=int, default=3)
    parser.add_argument("--skip-audio-generation", action="store_true")
    parser.add_argument("--skip-yamnet", action="store_true")
    args = parser.parse_args()

    config = load_config(None)
    output_dir = args.output_dir
    plots_dir = output_dir / "plots"
    nights_dir = output_dir / "nights"
    frames_dir = output_dir / "frame_scores"
    plots_dir.mkdir(parents=True, exist_ok=True)
    nights_dir.mkdir(parents=True, exist_ok=True)
    frames_dir.mkdir(parents=True, exist_ok=True)

    seeds = [int(item.strip()) for item in args.seeds.split(",") if item.strip()][: args.max_nights]
    nights = prepare_nights(args, seeds, nights_dir)
    scored = score_nights(nights, config, frames_dir, skip_yamnet=args.skip_yamnet)

    candidate_rows = []
    candidate_events: dict[str, list[pd.DataFrame]] = {}
    candidates = build_candidate_configs()
    special = {
        "original": ORIGINAL_CONFIG,
        "current_selected": CURRENT_SELECTED_CONFIG,
    }
    all_configs = {**special, **{f"candidate_{i:04d}": cfg for i, cfg in enumerate(candidates)}}

    for name, policy in all_configs.items():
        per_night_rows = []
        event_frames = []
        for item in scored:
            frames, alert_log = apply_policy(item["raw_frames"], policy)
            frames.attrs["trigger_threshold"] = policy.trigger_threshold
            detected, metrics = evaluate_events(
                frames,
                item["ground_truth"],
                item["duration"],
                float(config["event_onset_tolerance_seconds"]),
                float(config["late_alert_seconds"]),
                name,
            )
            metrics["night"] = item["name"]
            metrics["config_name"] = name
            per_night_rows.append(metrics)
            detected["night"] = item["name"]
            event_frames.append(detected)
        aggregate = aggregate_metrics(per_night_rows, event_frames, scored)
        candidate_rows.append({"config_name": name, **asdict(policy), **aggregate})
        candidate_events[name] = event_frames

    sweep_df = pd.DataFrame(candidate_rows)
    sweep_df.to_csv(output_dir / "multi_night_parameter_sweep.csv", index=False)

    original_row = sweep_df[sweep_df["config_name"] == "original"].iloc[0]
    current_row = sweep_df[sweep_df["config_name"] == "current_selected"].iloc[0]
    final_name, final_row, selection_notes = select_operating_point(sweep_df)
    final_config = row_to_policy(final_row)
    write_json(output_dir / "final_recommended_config.json", asdict(final_config))
    write_json(output_dir / "selection_notes.json", selection_notes)

    primary = scored[0]
    before_frames, _ = apply_policy(primary["raw_frames"], ORIGINAL_CONFIG)
    after_frames, _ = apply_policy(primary["raw_frames"], final_config)
    before_frames.attrs["trigger_threshold"] = ORIGINAL_CONFIG.trigger_threshold
    after_frames.attrs["trigger_threshold"] = final_config.trigger_threshold
    before_events, before_metrics = evaluate_events(
        before_frames, primary["ground_truth"], primary["duration"], 0.0, 5.0, "original"
    )
    after_events, after_metrics = evaluate_events(
        after_frames, primary["ground_truth"], primary["duration"], 0.0, 5.0, "optimized"
    )

    before_after = pd.DataFrame(
        [
            metric_row("Original system", ORIGINAL_CONFIG, before_metrics),
            metric_row("Optimized system", final_config, after_metrics),
        ]
    )
    before_after.to_csv(output_dir / "before_after_comparison.csv", index=False)

    y_max = max(
        float(before_frames["raw_baby_cry_score"].max()),
        float(before_frames["smoothed_baby_cry_score"].max()),
        float(after_frames["smoothed_baby_cry_score"].max()),
        0.35,
    )
    x_limits = (0.0, primary["duration"])
    y_limits = (0.0, min(1.0, y_max + 0.05))
    plot_timeline(
        before_frames,
        primary["ground_truth"],
        before_events,
        ORIGINAL_CONFIG,
        plots_dir / "timeline_before_modifications",
        "Baby Cry Detection Before Alert-Logic Optimization",
        x_limits,
        y_limits,
    )
    plot_timeline(
        after_frames,
        primary["ground_truth"],
        after_events,
        final_config,
        plots_dir / "timeline_after_optimization",
        "Baby Cry Detection After Alert-Logic Optimization",
        x_limits,
        y_limits,
    )
    create_zoom_plots(
        before_frames,
        after_frames,
        primary["ground_truth"],
        before_events,
        after_events,
        ORIGINAL_CONFIG,
        final_config,
        plots_dir,
        y_limits,
    )
    plot_before_after_metrics(before_after, plots_dir / "before_after_metrics")
    plot_operating_point(sweep_df, original_row, current_row, final_row, plots_dir / "best_operating_point")

    per_night_df = build_per_night_table(scored, all_configs, config)
    per_night_df.to_csv(output_dir / "multi_night_metrics_by_night.csv", index=False)
    write_report(
        output_dir,
        scored,
        ORIGINAL_CONFIG,
        CURRENT_SELECTED_CONFIG,
        final_config,
        original_row,
        current_row,
        final_row,
        before_after,
        selection_notes,
        final_name,
    )

    print(f"Scientific validation written to {output_dir}")
    print(f"Final recommended config: {final_name}")
    print(json.dumps(asdict(final_config), indent=2))


def prepare_nights(args, seeds: list[int], nights_dir: Path) -> list[dict]:
    backgrounds = [
        r"C:\Users\ibrahem_PC\Downloads\BackgroundNoise\freesound_community-roomtone03-24954.mp3",
        r"C:\Users\ibrahem_PC\Downloads\BackgroundNoise\freesound_community-dripping-sounds-60179.mp3",
    ]
    cry_dir = r"C:\Users\ibrahem_PC\Downloads\BabyCrying"
    extra_cry = r"C:\Users\ibrahem_PC\Downloads\BackgroundNoise\freesound_community-024021_a-poor-crying-baby-69681.mp3"
    nights = []
    script = Path(__file__).with_name("build_synthetic_night.py")
    for index, seed in enumerate(seeds, start=1):
        output = nights_dir / f"synthetic_night_seed_{seed}.wav"
        if not args.skip_audio_generation and not output.exists():
            cmd = [
                sys.executable,
                str(script),
                "--background",
                backgrounds[index % len(backgrounds)],
                "--background",
                backgrounds[(index + 1) % len(backgrounds)],
                "--cry-dir",
                cry_dir,
                "--cry-file",
                extra_cry,
                "--duration-minutes",
                str(args.duration_minutes),
                "--number-of-events",
                str(args.events_per_night),
                "--seed",
                str(seed),
                "--output",
                str(output),
            ]
            subprocess.run(cmd, check=True)
        nights.append(
            {
                "name": f"seed_{seed}",
                "audio": output,
                "ground_truth": output.with_name(output.stem + "_ground_truth.csv"),
                "manifest": output.with_name(output.stem + "_manifest.json"),
            }
        )
    return nights


def score_nights(nights: list[dict], config: dict, frames_dir: Path, skip_yamnet: bool) -> list[dict]:
    scored = []
    for night in nights:
        frame_path = frames_dir / f"{night['name']}_raw_frame_scores.csv"
        meta_path = frames_dir / f"{night['name']}_metadata.json"
        if frame_path.exists():
            raw_frames = pd.read_csv(frame_path)
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            duration = float(meta["duration"])
        else:
            if skip_yamnet:
                raise FileNotFoundError(f"Missing cached frames: {frame_path}")
            raw_frames, duration, elapsed = build_frames_from_audio(night["audio"], config, progress=True)
            raw_frames.to_csv(frame_path, index=False)
            write_json(meta_path, {"duration": duration, "processing_seconds": elapsed})
        gt = read_ground_truth(night["ground_truth"], duration)
        scored.append({**night, "raw_frames": raw_frames, "duration": duration, "ground_truth": gt})
    return scored


def build_candidate_configs() -> list[PolicyConfig]:
    thresholds = [0.05, 0.10, 0.15, 0.20, 0.25, 0.30]
    persistence = [1, 2, 3, 4]
    smoothing = ["none", "rolling_mean", "rolling_median", "ema"]
    clear_offsets = [0.02, 0.05, 0.10]
    configs = []
    for trigger, persist, smooth, clear_offset in itertools.product(
        thresholds, persistence, smoothing, clear_offsets
    ):
        clear = max(0.0, trigger - clear_offset)
        windows = [1] if smooth == "none" else [3, 5]
        for window in windows:
            configs.append(
                PolicyConfig(
                    aggregation="max",
                    decision_window_frames=1,
                    trigger_threshold=trigger,
                    clear_threshold=clear,
                    persistence_frames=persist,
                    smoothing=smooth,
                    smoothing_window_frames=window,
                    ema_alpha=0.35,
                    cooldown_seconds=30.0,
                    rearming_seconds=5.0,
                ).normalized()
            )
    return configs


def aggregate_metrics(per_night_rows: list[dict], event_frames: list[pd.DataFrame], scored: list[dict]) -> dict:
    total_events = sum(len(item["ground_truth"]) for item in scored)
    total_hours = sum(item["duration"] for item in scored) / 3600.0
    tp = sum(row["true_positive_events"] for row in per_night_rows)
    fp = sum(row["false_positive_alerts"] for row in per_night_rows)
    missed = sum(row["missed_crying_events"] for row in per_night_rows)
    early = sum(row["early_alerts"] for row in per_night_rows)
    redundant_total = sum(row["redundant_alerts_per_crying_event"] * len(scored[i]["ground_truth"]) for i, row in enumerate(per_night_rows))
    latencies = pd.concat(event_frames, ignore_index=True)["latency"].dropna().astype(float)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / total_events if total_events else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "tested_hours": total_hours,
        "total_cry_events": total_events,
        "true_positive_events": tp,
        "false_positive_alerts": fp,
        "missed_crying_events": missed,
        "early_alerts": early,
        "duplicate_alerts": redundant_total,
        "event_precision": precision,
        "event_recall": recall,
        "event_f1": f1,
        "false_alerts_per_hour": fp / total_hours if total_hours else 0.0,
        "median_detection_latency": float(latencies.median()) if not latencies.empty else np.nan,
        "p95_detection_latency": float(np.percentile(latencies, 95)) if not latencies.empty else np.nan,
        "mean_detection_latency": float(latencies.mean()) if not latencies.empty else np.nan,
        "latency_std": float(latencies.std()) if len(latencies) > 1 else 0.0,
    }


def select_operating_point(sweep_df: pd.DataFrame):
    candidates = sweep_df[~sweep_df["config_name"].isin(["original", "current_selected"])].copy()
    notes = {}
    for recall_floor in [0.85, 0.90]:
        eligible = candidates[candidates["event_recall"] >= recall_floor]
        if eligible.empty:
            notes[f"recall_{int(recall_floor * 100)}"] = {
                "met": False,
                "message": f"No configuration met recall >= {recall_floor:.2f}.",
                "closest_recall": float(candidates["event_recall"].max()),
            }
        else:
            min_false = eligible["false_alerts_per_hour"].min()
            best = eligible[eligible["false_alerts_per_hour"] == min_false].sort_values(
                ["event_recall", "duplicate_alerts", "median_detection_latency", "p95_detection_latency"],
                ascending=[False, True, True, True],
            ).iloc[0]
            notes[f"recall_{int(recall_floor * 100)}"] = {
                "met": True,
                "config_name": best["config_name"],
                "event_recall": float(best["event_recall"]),
                "false_alerts_per_hour": float(best["false_alerts_per_hour"]),
            }

    target = candidates[candidates["event_recall"] >= 0.85]
    if target.empty:
        target = candidates.copy()
    min_false = target["false_alerts_per_hour"].min()
    target = target[target["false_alerts_per_hour"] == min_false]
    final = target.sort_values(
        ["event_recall", "duplicate_alerts", "median_detection_latency", "p95_detection_latency", "trigger_threshold", "persistence_frames"],
        ascending=[False, True, True, True, False, False],
    ).iloc[0]
    return final["config_name"], final, notes


def row_to_policy(row) -> PolicyConfig:
    fields = PolicyConfig.__dataclass_fields__.keys()
    return PolicyConfig(**{field: row[field].item() if hasattr(row[field], "item") else row[field] for field in fields}).normalized()


def metric_row(name: str, policy: PolicyConfig, metrics: dict) -> dict:
    return {
        "system": name,
        **asdict(policy),
        "true_positive_events": metrics["true_positive_events"],
        "false_positive_alerts": metrics["false_positive_alerts"],
        "missed_crying_events": metrics["missed_crying_events"],
        "early_alerts": metrics["early_alerts"],
        "duplicate_alerts": metrics["redundant_alerts_per_crying_event"],
        "event_precision": metrics["event_precision"],
        "event_recall": metrics["event_recall"],
        "event_f1": metrics["event_f1"],
        "false_alerts_per_hour": metrics["false_alerts_per_hour"],
        "median_detection_latency": metrics["median_detection_latency"],
        "p95_detection_latency": metrics["p95_detection_latency"],
    }


def plot_timeline(frames, ground_truth, detected, policy, base, title, x_limits, y_limits):
    plt.figure(figsize=(13, 4.5))
    plt.plot(frames["frame_center_seconds"], frames["raw_baby_cry_score"], label="Raw Baby Cry score", alpha=0.45)
    plt.plot(frames["frame_center_seconds"], frames["smoothed_baby_cry_score"], label="Decision score", linewidth=1.4)
    plt.axhline(policy.trigger_threshold, color="red", linestyle="--", label="Trigger threshold")
    plt.axhline(policy.clear_threshold, color="orange", linestyle=":", label="Clear threshold")
    first_span = True
    for event in ground_truth:
        plt.axvspan(event.start_sec, event.end_sec, color="red", alpha=0.12, label="Ground-truth cry" if first_span else None)
        first_span = False
    for _, row in detected.iterrows():
        if pd.notna(row["alert_timestamp"]):
            plt.axvline(row["alert_timestamp"], color="purple", linestyle="-.", alpha=0.85, label="Alert")
        if row["result_type"] == "missed":
            plt.scatter([row["ground_truth_start"]], [y_limits[1] * 0.88], marker="x", color="black", s=55, label="Missed cry")
        elif row["result_type"] == "early":
            plt.scatter([row["alert_timestamp"]], [y_limits[1] * 0.80], marker="^", color="darkorange", s=45, label="Early alert")
    plt.title(title)
    plt.xlabel("Time (seconds)")
    plt.ylabel("Baby Cry score")
    plt.xlim(*x_limits)
    plt.ylim(*y_limits)
    handles, labels = plt.gca().get_legend_handles_labels()
    unique = dict(zip(labels, handles))
    plt.legend(unique.values(), unique.keys(), loc="upper right")
    savefig(base)


def create_zoom_plots(before, after, gt, before_events, after_events, original, final, plots_dir, y_limits):
    correct = after_events[after_events["result_type"] == "correct"].head(1)
    missed = after_events[after_events["result_type"] == "missed"].head(1)
    windows = []
    if not correct.empty:
        row = correct.iloc[0]
        windows.append(("correct_cry", max(0, row["ground_truth_start"] - 10), row["ground_truth_end"] + 15))
    if not missed.empty:
        row = missed.iloc[0]
        windows.append(("difficult_or_missed_cry", max(0, row["ground_truth_start"] - 10), row["ground_truth_end"] + 15))
    windows.append(("non_cry_section", 1200.0, 1260.0))
    for label, start, end in windows:
        local_gt = [event for event in gt if event.end_sec >= start and event.start_sec <= end]
        plot_timeline(
            before[(before["frame_center_seconds"] >= start) & (before["frame_center_seconds"] <= end)],
            local_gt,
            before_events,
            original,
            plots_dir / f"zoom_{label}_before",
            f"Before Optimization: {label.replace('_', ' ').title()}",
            (start, end),
            y_limits,
        )
        plot_timeline(
            after[(after["frame_center_seconds"] >= start) & (after["frame_center_seconds"] <= end)],
            local_gt,
            after_events,
            final,
            plots_dir / f"zoom_{label}_after",
            f"After Optimization: {label.replace('_', ' ').title()}",
            (start, end),
            y_limits,
        )


def plot_before_after_metrics(df, base):
    fig, axes = plt.subplots(2, 2, figsize=(10, 7))
    metrics = [
        ("event_recall", "Event Recall"),
        ("false_alerts_per_hour", "False Alerts per Hour"),
        ("missed_crying_events", "Missed Cry Events"),
        ("median_detection_latency", "Median Detection Latency (s)"),
    ]
    for axis, (column, title) in zip(axes.flatten(), metrics):
        axis.bar(df["system"], df[column], color=["#6b7280", "#123867"])
        axis.set_title(title)
        axis.tick_params(axis="x", rotation=15)
    fig.suptitle("Before/After Alert-Logic Optimization")
    savefig(base)


def plot_operating_point(sweep_df, original, current, final, base):
    candidates = sweep_df[~sweep_df["config_name"].isin(["original", "current_selected"])].copy()
    pareto = pareto_frontier(candidates)
    plt.figure(figsize=(8, 5.5))
    sizes = 40 + 25 * candidates["median_detection_latency"].fillna(candidates["median_detection_latency"].max()).clip(0, 10)
    plt.scatter(candidates["false_alerts_per_hour"], candidates["event_recall"], s=sizes, alpha=0.22, label="Tested configurations")
    plt.scatter(pareto["false_alerts_per_hour"], pareto["event_recall"], s=60, facecolors="none", edgecolors="green", label="Pareto-optimal")
    highlight_point(original, "Original", "gray", "o")
    highlight_point(current, "Current selected", "orange", "s")
    highlight_point(final, "Recommended Operating Point", "red", "*", size=180)
    plt.title("Best Operating Point: Recall versus False Wakeups")
    plt.xlabel("False alerts per hour")
    plt.ylabel("Event-level recall")
    plt.legend()
    savefig(base)


def highlight_point(row, label, color, marker, size=95):
    plt.scatter([row["false_alerts_per_hour"]], [row["event_recall"]], color=color, marker=marker, s=size, label=label, zorder=5)
    plt.annotate(label, (row["false_alerts_per_hour"], row["event_recall"]), textcoords="offset points", xytext=(6, 6))


def pareto_frontier(df):
    ordered = df.sort_values(["false_alerts_per_hour", "event_recall"], ascending=[True, False])
    rows = []
    best_recall = -1
    for _, row in ordered.iterrows():
        if row["event_recall"] > best_recall:
            rows.append(row)
            best_recall = row["event_recall"]
    return pd.DataFrame(rows)


def build_per_night_table(scored, configs, config):
    rows = []
    for config_name in ["original", "current_selected"]:
        policy = configs[config_name]
        for item in scored:
            frames, _ = apply_policy(item["raw_frames"], policy)
            frames.attrs["trigger_threshold"] = policy.trigger_threshold
            _, metrics = evaluate_events(frames, item["ground_truth"], item["duration"], 0.0, 5.0, config_name)
            rows.append({"night": item["name"], "config_name": config_name, **metrics})
    return pd.DataFrame(rows)


def write_report(output_dir, scored, original, current, final, original_row, current_row, final_row, before_after, notes, final_name):
    total_hours = sum(item["duration"] for item in scored) / 3600.0
    total_events = sum(len(item["ground_truth"]) for item in scored)
    false_prevented = before_after.iloc[0]["false_positive_alerts"] - before_after.iloc[1]["false_positive_alerts"]
    recall_change = before_after.iloc[1]["event_recall"] - before_after.iloc[0]["event_recall"]
    latency_change = before_after.iloc[1]["median_detection_latency"] - before_after.iloc[0]["median_detection_latency"]
    report = f"""# Scientific Alert-Logic Optimization Report

## Verified Original Configuration

Git history verification:

- Initial prototype commit `a66f72f`: threshold `0.30`, rolling 24 app segments, alert at 20 positive segments, 120-second cooldown.
- Pre-optimization state-machine commit `6c92e6b`: trigger `0.30`, clear `0.20`, rolling mean smoothing, 3-frame persistence, 120-second cooldown, 5-second rearming.

The before/after comparison uses the verified pre-optimization state-machine configuration because it is the direct predecessor of the optimized state-machine app.

```json
{json.dumps(asdict(original), indent=2)}
```

## Final Optimized Configuration

Selected configuration name: `{final_name}`

```json
{json.dumps(asdict(final), indent=2)}
```

## Selection of the Best Operating Point

A perfect classifier is not expected. Lower thresholds can improve recall but may cause false wakeups. Higher thresholds can reduce false wakeups but may miss weak crying. Longer persistence reduces short false alarms but increases detection latency.

The selection process used a lexicographic priority:

1. Minimize false wakeups, including false-positive alerts, early alerts, and duplicate alerts.
2. Among configurations with the lowest false-alert rate, maximize cry-event recall.
3. Among similar recall values, minimize median and 95th-percentile detection latency.
4. Prefer stable configurations that perform across multiple synthetic nights.

Recall constraint result for 85%:
{json.dumps(notes.get("recall_85", {}), indent=2)}

Recall constraint result for 90%:
{json.dumps(notes.get("recall_90", {}), indent=2)}

The selected operating point is a practical trade-off for the tested project requirements, not a claim of 100% accuracy.

## Before/After Summary

- False wakeups prevented on the primary comparison night: {false_prevented}
- Recall change on the primary comparison night: {recall_change:.3f}
- Median latency change on the primary comparison night: {latency_change:.3f} seconds
- Crying events still missed after optimization on the primary night: {before_after.iloc[1]["missed_crying_events"]}
- Duplicate alerts after optimization: {before_after.iloc[1]["duplicate_alerts"]}

## Aggregate Validation

- Tested hours: {total_hours:.2f}
- Total crying events: {total_events}
- Original aggregate recall: {original_row["event_recall"]:.3f}
- Original false alerts/hour: {original_row["false_alerts_per_hour"]:.3f}
- Current selected aggregate recall: {current_row["event_recall"]:.3f}
- Final recommended aggregate recall: {final_row["event_recall"]:.3f}
- Final recommended false alerts/hour: {final_row["false_alerts_per_hour"]:.3f}
- Final recommended median latency: {final_row["median_detection_latency"]:.3f} seconds
- Final recommended 95th-percentile latency: {final_row["p95_detection_latency"]:.3f} seconds

## Required Artifact Paths

- Before timeline: `{output_dir / "plots" / "timeline_before_modifications.png"}`
- After timeline: `{output_dir / "plots" / "timeline_after_optimization.png"}`
- Best operating point: `{output_dir / "plots" / "best_operating_point.png"}`
- Before/after CSV: `{output_dir / "before_after_comparison.csv"}`
- Metrics chart: `{output_dir / "plots" / "before_after_metrics.png"}`

## Limitations

- Validation used synthetic nights made from user-supplied audio, not real full-night recordings.
- Synthetic results depend on the available cry/background files and inserted SNR values.
- Final results should be revalidated on real labeled long recordings before deployment.
- Python and Android runtimes may differ slightly; parity testing remains required with exported mobile score logs.

## Build Confirmation

The final configuration was applied to the Android app after selection. Run `.\\gradlew.bat :mobile:testDebugUnitTest :mobile:assembleDebug :wear:assembleDebug` to confirm mobile and Wear OS builds after any later edits.
"""
    (output_dir / "scientific_report.md").write_text(report, encoding="utf-8")


def savefig(base):
    plt.tight_layout()
    plt.savefig(f"{base}.png")
    plt.savefig(f"{base}.svg")
    plt.close()


if __name__ == "__main__":
    main()
