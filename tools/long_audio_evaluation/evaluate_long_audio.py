from __future__ import annotations

import argparse
import itertools
import json
import math
import time
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from detector_core import (
    FRAME_COLUMNS,
    PolicyConfig,
    apply_policy,
    build_frames_from_audio,
    evaluate_events,
    frame_level_metrics,
    load_config,
    normalize_ground_truth,
    policy_to_dict,
    read_ground_truth,
    seconds_to_timestamp,
    write_json,
)


def main():
    parser = argparse.ArgumentParser(description="Evaluate HearMe/YAMNet on long audio.")
    parser.add_argument("--audio", required=True, type=Path)
    parser.add_argument("--ground-truth", type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--sweep", action="store_true")
    parser.add_argument("--max-sweep-combinations", type=int, default=5000)
    args = parser.parse_args()

    config = load_config(args.config)
    output_dir = args.output_dir
    plots_dir = output_dir / "plots"
    plots_dir.mkdir(parents=True, exist_ok=True)

    raw_frames, duration, elapsed = build_frames_from_audio(args.audio, config, progress=True)
    ground_truth = read_ground_truth(args.ground_truth, duration)
    normalize_ground_truth(ground_truth).to_csv(output_dir / "ground_truth_normalized.csv", index=False)

    default_policy = PolicyConfig(**config["default_policy"]).normalized()
    frames, alert_log = run_policy(raw_frames, default_policy, config, duration, ground_truth, "default")
    frames[FRAME_COLUMNS].to_csv(output_dir / "frame_scores.csv", index=False)
    alert_log.to_csv(output_dir / "alert_log.csv", index=False)

    detected_events, metrics = evaluate_events(
        frames,
        ground_truth,
        duration,
        float(config["event_onset_tolerance_seconds"]),
        float(config["late_alert_seconds"]),
        "default",
    )
    metrics.update(frame_level_metrics(frames, ground_truth))
    metrics["total_analyzed_audio_duration"] = duration
    metrics["processing_seconds"] = elapsed
    metrics["real_time_factor"] = elapsed / duration if duration else math.nan
    metrics["processing_speed_audio_seconds_per_second"] = duration / elapsed if elapsed else math.inf
    detected_events.to_csv(output_dir / "detected_events.csv", index=False)

    sweep_df = run_sweep(raw_frames, ground_truth, duration, config, args.max_sweep_combinations) if args.sweep else pd.DataFrame()
    if sweep_df.empty:
        default_row = {**policy_to_dict(default_policy), **metrics, "cost": cost(metrics, config)}
        sweep_df = pd.DataFrame([default_row])
    sweep_df.to_csv(output_dir / "parameter_sweep.csv", index=False)

    recommendations = choose_recommendations(sweep_df)
    for name, row in recommendations.items():
        write_json(output_dir / f"best_{name}_config.json", policy_from_row(row))

    write_json(output_dir / "summary_metrics.json", {**metrics, "selected_policy": policy_to_dict(default_policy)})
    write_report(output_dir, args.audio, duration, metrics, recommendations)
    create_plots(frames, ground_truth, detected_events, sweep_df, plots_dir, default_policy)

    print_console_events(detected_events)
    print(f"\nResults written to {output_dir}")
    print(f"Event recall: {metrics['event_recall']:.3f}")
    print(f"Event precision: {metrics['event_precision']:.3f}")
    print(f"False alerts/hour: {metrics['false_alerts_per_hour']:.3f}")


def run_policy(raw_frames, policy, config, duration, ground_truth, config_name):
    frames, alert_log = apply_policy(raw_frames, policy)
    frames.attrs["trigger_threshold"] = policy.trigger_threshold
    return frames, alert_log


def run_sweep(raw_frames, ground_truth, duration, config, limit):
    sweep = config["sweep"]
    rows = []
    combos = itertools.product(
        sweep["aggregation"],
        sweep["decision_window_frames"],
        sweep["trigger_threshold"],
        sweep["clear_threshold_offsets"],
        sweep["persistence_frames"],
        sweep["smoothing"],
        sweep["smoothing_window_frames"],
        sweep["ema_alpha"],
        sweep["gap_merge_seconds"],
        sweep["cooldown_seconds"],
        sweep["rearming_seconds"],
    )
    start = time.perf_counter()
    for index, combo in enumerate(combos):
        if index >= limit:
            break
        aggregation, window, trigger, clear_offset, persistence, smoothing, smooth_window, ema_alpha, gap, cooldown, rearm = combo
        if smoothing == "ema" and smooth_window != sweep["smoothing_window_frames"][0]:
            continue
        if smoothing != "ema" and ema_alpha != sweep["ema_alpha"][0]:
            continue
        policy = PolicyConfig(
            aggregation=aggregation,
            decision_window_frames=window,
            trigger_threshold=trigger,
            clear_threshold=max(0.0, trigger - clear_offset),
            persistence_frames=persistence,
            smoothing=smoothing,
            smoothing_window_frames=smooth_window,
            ema_alpha=ema_alpha,
            gap_merge_seconds=gap,
            cooldown_seconds=cooldown,
            rearming_seconds=rearm,
        ).normalized()
        frames, _ = apply_policy(raw_frames, policy)
        frames.attrs["trigger_threshold"] = policy.trigger_threshold
        _, metrics = evaluate_events(
            frames,
            ground_truth,
            duration,
            float(config["event_onset_tolerance_seconds"]),
            float(config["late_alert_seconds"]),
            f"sweep_{index}",
        )
        rows.append({**policy_to_dict(policy), **metrics, "cost": cost(metrics, config)})
        if (index + 1) % 100 == 0:
            print(f"Parameter sweep checked {index + 1} combinations in {time.perf_counter() - start:.1f}s")
    return pd.DataFrame(rows)


def cost(metrics, config):
    weights = config["cost_weights"]
    missed = metrics.get("missed_crying_events", 0)
    fp = metrics.get("false_positive_alerts", 0)
    early = metrics.get("early_alerts", 0)
    redundant = metrics.get("redundant_alerts_per_crying_event", 0)
    latency = metrics.get("mean_detection_latency", 0)
    if latency is None or math.isnan(latency):
        latency = 999.0
    latency_penalty = max(0.0, latency - weights["latency_grace_seconds"])
    return (
        missed * weights["false_negative"]
        + fp * weights["false_positive"]
        + early * weights["early_alert"]
        + redundant * weights["redundant_alert"]
        + latency_penalty * weights["latency_per_second"]
    )


def choose_recommendations(sweep_df):
    if sweep_df.empty:
        return {}
    sensitive = sweep_df.sort_values(
        ["event_recall", "false_alerts_per_hour", "median_detection_latency"],
        ascending=[False, True, True],
    ).iloc[0]
    balanced = sweep_df.sort_values(["cost", "event_recall"], ascending=[True, False]).iloc[0]
    candidates = sweep_df[
        (sweep_df["false_alerts_per_hour"] <= 0.10)
        & (sweep_df["redundant_alerts_per_crying_event"] <= 0.0)
        & (sweep_df["median_detection_latency"].fillna(999) <= 3.0)
    ]
    conservative_source = candidates if not candidates.empty else sweep_df
    conservative = conservative_source.sort_values(
        ["false_alerts_per_hour", "early_alerts", "event_recall"],
        ascending=[True, True, False],
    ).iloc[0]
    return {"sensitive": sensitive, "balanced": balanced, "conservative": conservative}


def policy_from_row(row):
    fields = PolicyConfig.__dataclass_fields__.keys()
    return {field: row[field].item() if hasattr(row[field], "item") else row[field] for field in fields}


def create_plots(frames, ground_truth, events, sweep_df, plots_dir, policy):
    plt.rcParams.update({"figure.dpi": 140, "savefig.dpi": 180, "font.size": 9})
    plot_timeline(frames, ground_truth, events, plots_dir / "full_timeline", policy)
    for _, event in events.iterrows():
        plot_timeline(
            frames[(frames["frame_center_seconds"] >= event["ground_truth_start"] - 10) & (frames["frame_center_seconds"] <= event["ground_truth_end"] + 20)],
            [type("Event", (), {"start_sec": event["ground_truth_start"], "end_sec": event["ground_truth_end"]})()],
            pd.DataFrame([event]),
            plots_dir / f"zoom_event_{event['event_id']}",
            policy,
        )
    plot_score_distribution(frames, ground_truth, plots_dir / "score_distribution")
    plot_precision_recall(sweep_df, plots_dir / "precision_recall")
    plot_recall_vs_false_alerts(sweep_df, plots_dir / "recall_vs_false_alerts")
    plot_latency(events, plots_dir)
    plot_confusion(sweep_df.iloc[0], plots_dir / "confusion_matrix")
    plot_heatmap(sweep_df, plots_dir / "threshold_persistence_heatmap")
    plot_pareto(sweep_df, plots_dir / "pareto_frontier")
    plot_parameter_comparison(sweep_df, plots_dir / "parameter_comparison")


def savefig(base):
    plt.tight_layout()
    plt.savefig(f"{base}.png")
    plt.savefig(f"{base}.svg")
    plt.close()


def plot_timeline(frames, ground_truth, events, base, policy):
    plt.figure(figsize=(12, 4))
    if not frames.empty:
        x = frames["frame_center_seconds"]
        plt.plot(x, frames["raw_baby_cry_score"], label="Raw Baby Cry score", alpha=0.45)
        plt.plot(x, frames["smoothed_baby_cry_score"], label="Smoothed score", linewidth=1.5)
    plt.axhline(policy.trigger_threshold, color="red", linestyle="--", label="Trigger threshold")
    plt.axhline(policy.clear_threshold, color="orange", linestyle=":", label="Clear threshold")
    for event in ground_truth:
        plt.axvspan(event.start_sec, event.end_sec, color="red", alpha=0.12, label="Ground-truth cry")
    if not events.empty:
        for _, row in events.dropna(subset=["alert_timestamp"]).iterrows():
            plt.axvline(row["alert_timestamp"], color="purple", linestyle="-.", alpha=0.8, label="Alert")
    plt.title("Baby Cry Score Timeline")
    plt.xlabel("Time (seconds)")
    plt.ylabel("Baby Cry score")
    handles, labels = plt.gca().get_legend_handles_labels()
    unique = dict(zip(labels, handles))
    plt.legend(unique.values(), unique.keys(), loc="upper right")
    savefig(base)


def plot_score_distribution(frames, ground_truth, base):
    labels = []
    for ts in frames["frame_center_seconds"].astype(float):
        labels.append("Cry" if any(event.start_sec <= ts <= event.end_sec for event in ground_truth) else "No Cry")
    data = pd.DataFrame({"label": labels, "score": frames["smoothed_baby_cry_score"]})
    plt.figure(figsize=(7, 4))
    for label in ["Cry", "No Cry"]:
        values = data[data["label"] == label]["score"]
        if not values.empty:
            plt.hist(values, bins=30, alpha=0.55, label=label)
    plt.title("Cry-Score Distribution")
    plt.xlabel("Smoothed Baby Cry score")
    plt.ylabel("Frame count")
    plt.legend()
    savefig(base)


def plot_precision_recall(sweep_df, base):
    plt.figure(figsize=(6, 4))
    plt.scatter(sweep_df["event_recall"], sweep_df["event_precision"], s=16)
    plt.title("Event Precision-Recall")
    plt.xlabel("Event recall")
    plt.ylabel("Event precision")
    savefig(base)


def plot_recall_vs_false_alerts(sweep_df, base):
    plt.figure(figsize=(6, 4))
    plt.scatter(sweep_df["false_alerts_per_hour"], sweep_df["event_recall"], s=16)
    plt.title("Recall versus False Alerts per Hour")
    plt.xlabel("False alerts per hour")
    plt.ylabel("Event recall")
    savefig(base)


def plot_latency(events, plots_dir):
    values = events["latency"].dropna()
    plt.figure(figsize=(6, 4))
    plt.hist(values, bins=20)
    plt.title("Detection-Latency Histogram")
    plt.xlabel("Latency (seconds)")
    plt.ylabel("Event count")
    savefig(plots_dir / "latency_histogram")

    plt.figure(figsize=(4, 4))
    plt.boxplot(values if not values.empty else [0])
    plt.title("Detection-Latency Box Plot")
    plt.ylabel("Latency (seconds)")
    savefig(plots_dir / "latency_boxplot")


def plot_confusion(row, base):
    tp = row.get("true_positive_events", 0)
    fn = row.get("missed_crying_events", 0)
    fp = row.get("false_positive_alerts", 0)
    matrix = np.array([[tp, fn], [fp, 0]])
    plt.figure(figsize=(4, 4))
    plt.imshow(matrix, cmap="Blues")
    plt.title("Event Confusion Matrix")
    plt.xticks([0, 1], ["Detected", "Missed"])
    plt.yticks([0, 1], ["Cry event", "No-cry alert"])
    for (y, x), value in np.ndenumerate(matrix):
        plt.text(x, y, int(value), ha="center", va="center")
    savefig(base)


def plot_heatmap(sweep_df, base):
    pivot = sweep_df.pivot_table(
        index="persistence_frames",
        columns="trigger_threshold",
        values="event_f1",
        aggfunc="max",
    )
    plt.figure(figsize=(8, 5))
    plt.imshow(pivot.fillna(0), aspect="auto", origin="lower", cmap="viridis")
    plt.title("Threshold/Persistence Heatmap (F1)")
    plt.xlabel("Trigger threshold")
    plt.ylabel("Persistence frames")
    plt.xticks(range(len(pivot.columns)), [f"{x:.2f}" for x in pivot.columns], rotation=45)
    plt.yticks(range(len(pivot.index)), pivot.index)
    plt.colorbar(label="Event F1")
    savefig(base)


def plot_pareto(sweep_df, base):
    plt.figure(figsize=(7, 4))
    scatter = plt.scatter(
        sweep_df["false_alerts_per_hour"],
        sweep_df["event_recall"],
        c=sweep_df["median_detection_latency"].fillna(999),
        s=20,
        cmap="plasma",
    )
    plt.title("Pareto Frontier: Recall, False Alerts, Latency")
    plt.xlabel("False alerts per hour")
    plt.ylabel("Event recall")
    plt.colorbar(scatter, label="Median latency (seconds)")
    savefig(base)


def plot_parameter_comparison(sweep_df, base):
    fig, axes = plt.subplots(1, 3, figsize=(12, 4))
    for axis, column, title in [
        (axes[0], "aggregation", "Aggregation"),
        (axes[1], "smoothing", "Smoothing"),
        (axes[2], "decision_window_frames", "Decision Window"),
    ]:
        grouped = sweep_df.groupby(column)["event_f1"].max()
        axis.bar([str(x) for x in grouped.index], grouped.values)
        axis.set_title(title)
        axis.set_ylabel("Best event F1")
        axis.tick_params(axis="x", rotation=45)
    savefig(base)


def write_report(output_dir, audio, duration, metrics, recommendations):
    lines = [
        "# HearMe Long-Audio Evaluation Report",
        "",
        f"Audio: `{audio}`",
        f"Duration: {duration:.2f} seconds ({seconds_to_timestamp(duration)})",
        "",
        "## Summary Metrics",
        "",
    ]
    for key, value in metrics.items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Recommended Configurations", ""])
    for name, row in recommendations.items():
        lines.append(f"### {name.title()}")
        lines.append("")
        lines.append("```json")
        lines.append(json.dumps(policy_from_row(row), indent=2))
        lines.append("```")
    lines.extend(
        [
            "",
            "## Limitations",
            "",
            "- The mobile app currently batches microphone audio into 5-second app segments.",
            "- Python YAMNet inference requires TensorFlow or tflite-runtime installed locally.",
            "- Synthetic audio is useful for repeatability but must not replace real labeled recordings.",
        ]
    )
    markdown = "\n".join(lines)
    (output_dir / "report.md").write_text(markdown, encoding="utf-8")
    (output_dir / "report.html").write_text("<pre>" + markdown.replace("&", "&amp;").replace("<", "&lt;") + "</pre>", encoding="utf-8")


def print_console_events(events):
    for _, row in events.iterrows():
        print(f"\nCry event {row['event_id']}:")
        print(f"Ground-truth start: {row['ground_truth_start_hms']}")
        print(f"Ground-truth end:   {row['ground_truth_end_hms']}")
        print(f"First crossing:     {row['first_score_crossing_hms']}")
        print(f"Alert generated:    {row['alert_timestamp_hms']}")
        print(f"Detection latency:  {row['latency']} seconds")
        print(f"Status:             {row['result_type']}")


if __name__ == "__main__":
    main()
