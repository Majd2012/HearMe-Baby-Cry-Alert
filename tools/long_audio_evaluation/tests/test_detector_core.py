import math
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parents[1]))

from detector_core import (
    GroundTruthEvent,
    PolicyConfig,
    apply_policy,
    evaluate_events,
    find_baby_cry_index,
    timestamp_to_seconds,
)


def frames(scores):
    rows = []
    for index, score in enumerate(scores):
        center = index * 0.48 + 0.4875
        rows.append(
            {
                "frame_index": index,
                "frame_start_seconds": center - 0.4875,
                "frame_center_seconds": center,
                "frame_end_seconds": center + 0.4875,
                "raw_baby_cry_score": score,
            }
        )
    return pd.DataFrame(rows)


def policy():
    return PolicyConfig(
        trigger_threshold=0.30,
        clear_threshold=0.20,
        decision_window_frames=1,
        persistence_frames=3,
        smoothing="none",
        cooldown_seconds=10,
        rearming_seconds=1,
    )


def test_no_alert_below_threshold():
    out, _ = apply_policy(frames([0.1] * 20), policy())
    assert not out["alert_generated"].any()


def test_alert_after_required_positive_frames():
    out, _ = apply_policy(frames([0.1, 0.4, 0.4, 0.4]), policy())
    assert out["alert_generated"].sum() == 1


def test_no_alert_from_isolated_spike():
    out, _ = apply_policy(frames([0.1, 0.9, 0.1, 0.1, 0.1]), policy())
    assert not out["alert_generated"].any()


def test_cooldown_prevents_duplicate_alert():
    out, _ = apply_policy(frames([0.8] * 30), policy())
    assert out["alert_generated"].sum() == 1


def test_event_matching_and_latency():
    out, _ = apply_policy(frames([0.1, 0.8, 0.8, 0.8, 0.1]), policy())
    out.attrs["trigger_threshold"] = 0.30
    events = [GroundTruthEvent("1", 0.6, 3.0)]
    detected, metrics = evaluate_events(out, events, 10.0, 0.0, 5.0, "test")
    assert metrics["true_positive_events"] == 1
    assert metrics["missed_crying_events"] == 0
    assert detected.iloc[0]["latency"] >= 0


def test_timestamp_parser_accepts_hms():
    assert timestamp_to_seconds("00:17:05.500") == 1025.5


def test_class_map_lookup_is_dynamic():
    index = find_baby_cry_index(Path(__file__).parents[1] / "yamnet_class_map.csv")
    assert index == 20


def test_missed_event_is_false_negative():
    out, _ = apply_policy(frames([0.1] * 10), policy())
    events = [GroundTruthEvent("1", 0.5, 2.0)]
    _, metrics = evaluate_events(out, events, 10.0, 0.0, 5.0, "test")
    assert metrics["missed_crying_events"] == 1
    assert math.isclose(metrics["event_recall"], 0.0)
