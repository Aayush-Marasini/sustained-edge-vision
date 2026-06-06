#!/usr/bin/env python3
"""
analyze_powerz_robust.py  v2
=============================
Robust PowerZ energy analysis using an ACTIVE-POWER FILTER.

Why step-detection was abandoned
---------------------------------
The v1 script attempted to detect the idle→inference power step in the
PowerZ recording. This failed for 17/18 runs because most recordings
started AFTER inference was already running at full load. No idle baseline
existed in the recording to anchor the step detection.

Revised approach
-----------------
Instead of anchoring by timing, we anchor by power level:

  1. Load all PowerZ samples for a recording.
  2. Filter to "inference-level" samples: power > IDLE_THRESHOLD_W (4.0 W).
     This removes any idle seconds at recording start/end regardless of how
     long the user waited before/after pressing Record.
  3. Mean of filtered samples = mean inference power for that run.
  4. FPS comes from Pi inference_log.csv (total valid frames / total valid
     duration, skipping first 10 s of model-load). This is independent of
     PowerZ timing.
  5. J/frame = mean_power / fps

This is robust because:
  - Idle Pi 5: ~2.5 W.  S2 inference: ~5.4 W.  Threshold 4.0 W is clean.
  - Inference power is near-constant across a 30-min run.
  - FPS from Pi clock needs no alignment with PowerZ clock.
  - If PowerZ stopped 5 minutes early, we still get a valid mean over the
    recorded portion (reported as truncated_pct < 100).

Outputs: 05_results/power_analysis_robust.csv
"""
from __future__ import annotations

import csv
import sqlite3
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import List

REPO_ROOT        = Path(__file__).resolve().parents[2]
POWER_DIR        = REPO_ROOT / "05_results" / "power_data"
RUNS_DIR         = REPO_ROOT / "05_results" / "runs"
OUTPUT           = REPO_ROOT / "05_results" / "power_analysis_robust.csv"
IDLE_THRESHOLD_W = 4.0    # samples below this are idle, not inference
SKIP_S           = 10.0   # skip first 10 s of inference (model-load ramp)


@dataclass
class RunPair:
    db_file:   str
    run_dir:   str
    condition: str
    rep:       int


# Explicit mapping — same source of truth as compute_statistics.py
MAPPING: List[RunPair] = [
    RunPair("2026-05-03_thermalval_S0_rep1.db",
            "2026-05-03_012911_thermalval_S0",          "Static-S0", 1),
    RunPair("2026-05-04_thermalval_S0_rep2.db",
            "2026-05-04_203732_thermalval_S0",          "Static-S0", 2),
    RunPair("2026-05-04_thermalval_S0_rep3.db",
            "2026-05-05_011931_thermalval_S0",          "Static-S0", 3),
    RunPair("2026-05-03_thermalval_S1_rep1.db",
            "2026-05-03_021631_thermalval_S1",          "Static-S1", 1),
    RunPair("2026-05-04_thermalval_S1_rep2.db",
            "2026-05-05_015938_thermalval_S1",          "Static-S1", 2),
    RunPair("2026-05-05_thermalval_S1_rep3.db",
            "2026-05-05_171318_thermalval_S1",          "Static-S1", 3),
    RunPair("2026-05-03_thermalval_S2_rep1.db",
            "2026-05-03_053226_thermalval_S2",          "Static-S2", 1),
    RunPair("2026-05-05_thermalval_S2_rep2.db",
            "2026-05-05_180734_thermalval_S2",          "Static-S2", 2),
    RunPair("2026-05-05_thermalval_S2_rep3.db",
            "2026-05-05_200514_thermalval_S2",          "Static-S2", 3),
    RunPair("2026-05-05_reactive_rep1.db",
            "2026-05-05_213247_scheduled_high_S0_rep1", "Reactive-Threshold", 1),
    RunPair("2026-05-05_reactive_rep2.db",
            "2026-05-05_220944_scheduled_high_S0_rep2", "Reactive-Threshold", 2),
    RunPair("2026-05-05_reactive_rep3.db",
            "2026-05-05_224659_scheduled_high_S0_rep3", "Reactive-Threshold", 3),
    RunPair("2026-05-05_proactive_rep1.db",
            "2026-05-06_011427_scheduled_high_S0_rep1", "Proactive (Ours)", 1),
    RunPair("2026-05-05_proactive_rep2.db",
            "2026-05-06_031811_scheduled_high_S0_rep2", "Proactive (Ours)", 2),
    RunPair("2026-05-05_proactive_rep3.db",
            "2026-05-06_035911_scheduled_high_S0_rep3", "Proactive (Ours)", 3),
    RunPair("active_cooling_S0_rep1.db",
            "2026-05-24_182759_thermalval_S0_active_cooling", "Active-Oracle", 1),
    RunPair("active_cooling_S0_rep2.db",
            "2026-05-24_190352_thermalval_S0_active_cooling", "Active-Oracle", 2),
    RunPair("active_cooling_S0_rep3.db",
            "2026-05-24_193737_thermalval_S0_active_cooling", "Active-Oracle", 3),
    RunPair("2026-06-05_nodwell_rep1.db",
            "2026-06-05_183203_scheduled_high_S0_rep1", "Proactive-NoDwell", 1),
    RunPair("2026-06-05_nodwell_rep2.db",
            "2026-06-05_190704_scheduled_high_S0_rep2", "Proactive-NoDwell", 2),
    RunPair("2026-06-05_nodwell_rep3.db",
            "2026-06-05_195204_scheduled_high_S0_rep3", "Proactive-NoDwell", 3),
]


def load_powerz(db_path: Path):
    conn = sqlite3.connect(str(db_path))
    cur  = conn.cursor()
    cur.execute("SELECT VBUS, IBUS FROM table_1 ORDER BY Unix ASC")
    rows = cur.fetchall()
    conn.close()
    return [v * i for v, i in rows]


def load_inference_log(run_dir: Path):
    """Return (fps, frame_count, window_s) from inference_log.csv after SKIP_S."""
    path = run_dir / "inference_log.csv"
    first_t = last_t = None
    n = 0
    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                t = float(row["monotonic_time_s"])
                if t < SKIP_S:
                    continue
                if first_t is None:
                    first_t = t
                last_t = t
                n += 1
            except (ValueError, KeyError):
                continue
    if n < 100 or first_t is None:
        raise ValueError("Too few frames in inference_log.csv")
    duration = last_t - first_t
    return n / duration, n, duration


def analyze_run(pair: RunPair) -> dict:
    db_path = POWER_DIR / pair.db_file
    run_dir = RUNS_DIR  / pair.run_dir

    if not db_path.exists():
        return {"condition": pair.condition, "rep": pair.rep,
                "error": f"DB missing: {pair.db_file}"}
    if not run_dir.exists():
        return {"condition": pair.condition, "rep": pair.rep,
                "error": f"Run dir missing: {pair.run_dir}"}

    # PowerZ: filter to inference-level samples
    all_power = load_powerz(db_path)
    inference_power = [p for p in all_power if p > IDLE_THRESHOLD_W]

    if len(inference_power) < 1000:
        return {"condition": pair.condition, "rep": pair.rep,
                "error": f"Only {len(inference_power)} samples > {IDLE_THRESHOLD_W}W "
                         f"(PowerZ may have stopped too early)"}

    mean_power = statistics.mean(inference_power)
    std_power  = statistics.pstdev(inference_power)

    # FPS from Pi (clock-independent)
    fps, frame_count, window_s = load_inference_log(run_dir)
    j_per_frame = mean_power / fps

    # Coverage: what fraction of Pi run did PowerZ capture
    expected_samples = window_s * 1000   # approximate at 1 kSPS
    coverage_pct = min(100.0, 100.0 * len(inference_power) / expected_samples)

    return {
        "condition":        pair.condition,
        "rep":              pair.rep,
        "label":            f"{pair.condition} rep{pair.rep}",
        "mean_power_w":     round(mean_power, 4),
        "std_power_w":      round(std_power, 4),
        "fps_mean":         round(fps, 4),
        "frame_count":      frame_count,
        "window_s":         round(window_s, 1),
        "j_per_frame":      round(j_per_frame, 4),
        "pz_inference_samples": len(inference_power),
        "pz_coverage_pct":  round(coverage_pct, 1),
    }


def main():
    print(f"\nRobust PowerZ analysis  (n={len(MAPPING)} runs, v2: active-power filter)")
    print("=" * 90)
    print(f"{'Run':<28} {'Power_W':>10} {'FPS':>8} {'J/frame':>10} "
          f"{'Window_s':>10} {'Cover%':>8}")
    print("-" * 90)

    records = []
    for pair in MAPPING:
        try:
            r = analyze_run(pair)
        except Exception as e:
            r = {"condition": pair.condition, "rep": pair.rep, "error": str(e)}
        records.append(r)

        if "error" in r:
            print(f"  {pair.condition} rep{pair.rep}  ERROR: {r['error'][:60]}")
        else:
            print(f"  {r['label']:<26} {r['mean_power_w']:>10.4f} "
                  f"{r['fps_mean']:>8.3f} {r['j_per_frame']:>10.4f} "
                  f"{r['window_s']:>10.1f} {r['pz_coverage_pct']:>8.1f}")

    valid = [r for r in records if "error" not in r]
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    if valid:
        with open(OUTPUT, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(valid[0].keys()))
            w.writeheader(); w.writerows(valid)

    print(f"\nSaved {len(valid)}/{len(MAPPING)} runs → "
          f"{OUTPUT.relative_to(REPO_ROOT)}")

    # Per-condition summary
    from collections import defaultdict
    by_c = defaultdict(list)
    for r in valid:
        by_c[r["condition"]].append(r)

    print("\n" + "=" * 90)
    print("PER-CONDITION SUMMARY")
    print(f"{'Condition':<22} {'n':>3} {'Power_W':>18} {'J/frame':>18}")
    print("-" * 65)
    for cond in ["Static-S0","Static-S1","Static-S2",
                 "Reactive-Threshold","Proactive (Ours)","Proactive-NoDwell","Active-Oracle"]:
        if cond not in by_c: continue
        rows = by_c[cond]
        pw = [r["mean_power_w"] for r in rows]
        jp = [r["j_per_frame"]  for r in rows]
        print(f"  {cond:<20} {len(rows):>3} "
              f"{statistics.mean(pw):>7.3f}±{statistics.pstdev(pw):.3f} "
              f"{statistics.mean(jp):>9.4f}±{statistics.pstdev(jp):.4f}")

    # Key comparisons
    if "Proactive (Ours)" in by_c and "Reactive-Threshold" in by_c:
        p_jp = [r["j_per_frame"] for r in by_c["Proactive (Ours)"]]
        r_jp = [r["j_per_frame"] for r in by_c["Reactive-Threshold"]]
        delta_pct = 100*(statistics.mean(p_jp)-statistics.mean(r_jp))/statistics.mean(r_jp)
        print(f"\nProactive vs Reactive J/frame: {delta_pct:+.1f}%")

    if "Active-Oracle" in by_c and "Proactive (Ours)" in by_c:
        oracle_fps = statistics.mean(r["fps_mean"] for r in by_c["Active-Oracle"])
        proact_fps = statistics.mean(r["fps_mean"] for r in by_c["Proactive (Ours)"])
        print(f"Proactive as % of oracle FPS:  {100*proact_fps/oracle_fps:.1f}%")


if __name__ == "__main__":
    main()