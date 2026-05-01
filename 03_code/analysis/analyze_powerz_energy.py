"""
analyze_powerz_energy.py
========================
Compute energy-per-frame for FP32 and INT8 inference runs
by joining PowerZ .db recordings with inference_log.csv timing.

Method:
  1. Load PowerZ .db (1 kSPS power samples, Unix epoch timestamps)
  2. Load inference_log.csv (per-frame monotonic timestamps)
  3. Convert inference timestamps to Unix epoch via:
       epoch = recording_start_unix + (monotonic_offset - first_monotonic_offset)
  4. Slice PowerZ to the inference window
  5. Compute: avg_power = mean(VBUS * IBUS), total_energy = ENERGY[-1] - ENERGY[0]
  6. J/frame = total_energy / frame_count

Usage:
    python 03_code/analysis/analyze_powerz_energy.py

Requires:
    pip install pandas --break-system-packages
"""

import sqlite3
import csv
import statistics
from pathlib import Path
from dataclasses import dataclass
from typing import Optional
import sys

# ── Try pandas, fall back to stdlib if missing ──────────────────────────────
try:
    import pandas as pd
    HAS_PANDAS = True
except ImportError:
    HAS_PANDAS = False
    print("Note: pandas not available, using stdlib (slower for large .db)")


REPO_ROOT = Path(__file__).resolve().parents[2]
POWER_DATA = REPO_ROOT / "05_results" / "power_data"
RUNS_DIR   = REPO_ROOT / "05_results" / "runs"


@dataclass
class RunPair:
    label: str
    db_file: str        # filename in power_data/
    run_dir: str        # directory name in runs/


# ── Define the run pairs to analyze ─────────────────────────────────────────
# Match PowerZ recording to the inference run directory.
# The PowerZ Unix start time and the run_metadata.json start time
# must overlap for the join to be valid.

RUNS = [
    # FP32 inference-only (no telemetry)
    RunPair("FP32 rep1", "2026-04-30_inferonly_fp32_rep1.db", "2026-04-30_192521_inferonly_fp32_rep1"),
    RunPair("FP32 rep2", "2026-04-30_inferonly_fp32_rep2.db", "2026-04-30_193137_inferonly_fp32_rep2"),
    RunPair("FP32 rep3", "2026-04-30_inferonly_fp32_rep3.db", "2026-04-30_195420_inferonly_fp32_rep3"),
    # INT8 inference-only
    RunPair("INT8 rep1", "2026-05-01_inferonly_int8_rep1.db", "2026-05-01_201242_inferonly_int8_rep1"),
    RunPair("INT8 rep2", "2026-05-01_inferonly_int8_rep2.db", "2026-05-01_201926_inferonly_int8_rep2"),
    RunPair("INT8 rep3", "2026-05-01_inferonly_int8_rep3.db", "2026-05-01_203913_inferonly_int8_rep3"),
]


def load_powerz(db_path: Path) -> tuple:
    """
    Returns (timestamps_unix, power_watts, energy_joules_cumulative, recording_start_unix).
    """
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    # Get recording start time from params
    cursor.execute("SELECT Unix FROM table_1_param LIMIT 1")
    row = cursor.fetchone()
    recording_start_unix = float(row[0]) if row else None

    # Load power data
    cursor.execute("SELECT Unix, VBUS, IBUS, ENERGY FROM table_1 ORDER BY Unix")
    rows = cursor.fetchall()
    conn.close()

    timestamps = [r[0] for r in rows]
    power      = [r[1] * r[2] for r in rows]  # VBUS * IBUS = Watts
    energy     = [r[3] for r in rows]

    return timestamps, power, energy, recording_start_unix


def load_inference_log(run_dir: Path) -> tuple:
    """
    Returns (first_monotonic, last_monotonic, frame_count).
    """
    log_path = run_dir / "inference_log.csv"
    if not log_path.exists():
        raise FileNotFoundError(f"inference_log.csv not found in {run_dir}")

    rows = list(csv.DictReader(open(log_path)))
    if len(rows) < 2:
        raise ValueError(f"Too few rows in {log_path}")

    first_mono = float(rows[0]["monotonic_time_s"])
    last_mono  = float(rows[-1]["monotonic_time_s"])
    frame_count = len(rows)
    return first_mono, last_mono, frame_count


def get_run_metadata_start_unix(run_dir: Path) -> Optional[float]:
    """
    Try to get the run start time from run_metadata.json or metadata.json.
    Returns Unix epoch float or None.
    """
    import json
    for fname in ["run_metadata.json", "metadata.json"]:
        p = run_dir / fname
        if p.exists():
            meta = json.load(open(p))
            # telemetry pipeline stores start_time_utc as ISO string
            st = meta.get("start_time_utc")
            if st:
                from datetime import datetime, timezone
                dt = datetime.fromisoformat(st)
                return dt.timestamp()
    return None


def find_inference_window(pz_times, pz_power, inference_duration_s=300.0):
    """
    Detect the inference window in PowerZ data using power step detection.
    
    Strategy:
    - First 10s = model load (ramp-up), exclude
    - Last bucket may be partial, use inference_duration_s as hard cap
    - Inference window = [t_start + 10s, t_start + 10s + inference_duration_s]
    
    This is robust to idle tails of any length.
    """
    t_start = pz_times[0]
    
    # Skip first 10s (model load) and cap at inference_duration_s
    window_start_unix = t_start + 10.0       # skip 10s startup
    window_end_unix   = t_start + 10.0 + inference_duration_s  # 300s window
    
    # Slice to window
    indices = [i for i, t in enumerate(pz_times)
               if window_start_unix <= t <= window_end_unix]
    
    if len(indices) < 100:
        raise ValueError(f"Too few samples in inference window: {len(indices)}")
    
    window_power = [pz_power[i] for i in indices]
    window_times = [pz_times[i] for i in indices]
    
    return window_power, window_times


def analyze_run(pair: RunPair) -> dict:
    db_path  = POWER_DATA / pair.db_file
    run_dir  = RUNS_DIR / pair.run_dir

    if not db_path.exists():
        return {"label": pair.label, "error": f"DB not found: {db_path.name}"}
    if not run_dir.exists():
        return {"label": pair.label, "error": f"Run dir not found: {run_dir.name}"}

    # Load PowerZ
    pz_times, pz_power, pz_energy, rec_start = load_powerz(db_path)

    # Load inference timing
    first_mono, last_mono, frame_count = load_inference_log(run_dir)
    inference_duration_s = last_mono - first_mono

    # Detect inference window (skip 10s startup, use exact 300s window)
    window_power, window_times = find_inference_window(
        pz_times, pz_power, inference_duration_s=inference_duration_s
    )

    # Energy and power stats from the clean window
    duration_window_s = window_times[-1] - window_times[0]

    # Get cumulative energy for this window from pz_energy
    # Find corresponding indices in original arrays
    w_start_unix = window_times[0]
    w_end_unix   = window_times[-1]
    energy_indices = [i for i, t in enumerate(pz_times)
                      if w_start_unix <= t <= w_end_unix]
    energy_window_j = pz_energy[energy_indices[-1]] - pz_energy[energy_indices[0]]

    avg_power_w = energy_window_j / duration_window_s if duration_window_s > 0 else None
    j_per_frame = energy_window_j / frame_count if frame_count > 0 else None
    fps_actual  = frame_count / inference_duration_s if inference_duration_s > 0 else None

    mean_power = statistics.mean(window_power)
    std_power  = statistics.pstdev(window_power)

    return {
        "label":           pair.label,
        "frame_count":     frame_count,
        "fps":             fps_actual,
        "duration_s":      inference_duration_s,
        "mean_power_w":    mean_power,
        "std_power_w":     std_power,
        "min_power_w":     min(window_power),
        "max_power_w":     max(window_power),
        "total_energy_j":  energy_window_j,
        "j_per_frame":     j_per_frame,
        "pz_samples":      len(window_power),
        "pz_duration_s":   duration_window_s,
        "window_start_s":  window_times[0] - pz_times[0],
        "window_end_s":    window_times[-1] - pz_times[0],
        "error":           None,
    }


def main():
    print("="*75)
    print("PowerZ Energy Analysis: FP32 vs INT8 on Pi 5 (passive cooling)")
    print("="*75)
    print()

    results = []
    for pair in RUNS:
        print(f"Analyzing {pair.label}...", end=" ", flush=True)
        try:
            r = analyze_run(pair)
            results.append(r)
            if r["error"]:
                print(f"ERROR: {r['error']}")
            else:
                print(f"OK ({r['pz_samples']:,} PowerZ samples, {r['frame_count']} frames)")
        except Exception as e:
            print(f"EXCEPTION: {e}")
            results.append({"label": pair.label, "error": str(e)})

    # ── Per-run table ────────────────────────────────────────────────────────
    print()
    print(f"{'Label':<15} {'FPS':>7} {'Window':>12} {'Power(W)':>10} {'±':>6} {'J/frame':>10} {'Energy(J)':>10}")
    print("-"*75)
    for r in results:
        if r.get("error"):
            print(f"  {r['label']:<13} ERROR: {r['error']}")
        else:
            window_str = f"{r.get('window_start_s',0):.0f}-{r.get('window_end_s',0):.0f}s"
            print(f"  {r['label']:<13} "
                f"{r['fps']:>7.3f} "
                f"{window_str:>12} "
                f"{r['mean_power_w']:>10.3f} "
                f"{r['std_power_w']:>6.3f} "
                f"{r['j_per_frame']:>10.6f} "
                f"{r['total_energy_j']:>10.3f}")

    # ── Aggregate FP32 vs INT8 ───────────────────────────────────────────────
    fp32 = [r for r in results if "FP32" in r.get("label","") and not r.get("error")]
    int8 = [r for r in results if "INT8" in r.get("label","") and not r.get("error")]

    if fp32 and int8:
        print()
        print("="*75)
        print("AGGREGATE COMPARISON")
        print("="*75)

        def agg(rows, key):
            vals = [r[key] for r in rows if r.get(key) is not None]
            return statistics.mean(vals), statistics.pstdev(vals)

        fp32_fps,   fp32_fps_std   = agg(fp32, "fps")
        fp32_pwr,   fp32_pwr_std   = agg(fp32, "mean_power_w")
        fp32_jpf,   fp32_jpf_std   = agg(fp32, "j_per_frame")

        int8_fps,   int8_fps_std   = agg(int8, "fps")
        int8_pwr,   int8_pwr_std   = agg(int8, "mean_power_w")
        int8_jpf,   int8_jpf_std   = agg(int8, "j_per_frame")

        print(f"\n{'Metric':<25} {'FP32':>18} {'INT8':>18} {'Ratio (I/F)':>14}")
        print("-"*78)
        print(f"{'FPS':<25} {fp32_fps:>7.3f} ±{fp32_fps_std:.3f}    "
              f"{int8_fps:>7.3f} ±{int8_fps_std:.3f}    "
              f"{int8_fps/fp32_fps:>10.3f}×")
        print(f"{'Avg power (W)':<25} {fp32_pwr:>7.3f} ±{fp32_pwr_std:.3f}    "
              f"{int8_pwr:>7.3f} ±{int8_pwr_std:.3f}    "
              f"{int8_pwr/fp32_pwr:>10.3f}×")
        print(f"{'J/frame':<25} {fp32_jpf:>7.5f} ±{fp32_jpf_std:.5f}  "
              f"{int8_jpf:>7.5f} ±{int8_jpf_std:.5f}  "
              f"{int8_jpf/fp32_jpf:>10.3f}×")

        print()
        jpf_ratio = int8_jpf / fp32_jpf
        pwr_ratio = int8_pwr / fp32_pwr

        print("SCHEDULER VIABILITY ASSESSMENT:")
        print(f"  INT8/FP32 power ratio:   {pwr_ratio:.3f}×")
        print(f"  INT8/FP32 J/frame ratio: {jpf_ratio:.3f}×")
        print()

        if pwr_ratio < 0.80:
            print(f"  ✓ INT8 draws {(1-pwr_ratio)*100:.1f}% less power → THERMALLY VIABLE")
            print(f"    Switching to INT8 reduces heat dissipation by {(1-pwr_ratio)*100:.1f}%")
        elif pwr_ratio < 0.95:
            print(f"  ⚠ INT8 draws {(1-pwr_ratio)*100:.1f}% less power → MARGINALLY VIABLE")
            print(f"    Small thermal benefit; scheduler should dwell in INT8 longer to help")
        else:
            print(f"  ✗ INT8 draws {pwr_ratio:.3f}× FP32 power → NOT THERMALLY VIABLE")
            print(f"    INT8 won't help shed thermal load — Task 12 design must change")

        if jpf_ratio < 0.95:
            print(f"  ✓ INT8 uses {(1-jpf_ratio)*100:.1f}% less energy per frame → ENERGY EFFICIENT")
        elif jpf_ratio < 1.10:
            print(f"  ~ INT8 J/frame within 10% of FP32 → ENERGY NEUTRAL")
        else:
            print(f"  ✗ INT8 uses {(jpf_ratio-1)*100:.1f}% MORE energy per frame → ENERGY WORSE")

        print()
        print("PAPER §V PARETO IMPLICATIONS:")
        if pwr_ratio < 0.90 and jpf_ratio > 1.05:
            print("  INT8: lower power, higher latency, higher J/frame")
            print("  → INT8 buys thermal headroom at cost of per-frame energy")
            print("  → Scheduler uses INT8 during thermal stress, FP32 during normal ops")
            print("  → This IS the non-trivial trade-off that makes the paper interesting")
        elif pwr_ratio >= 0.95:
            print("  INT8 provides no thermal relief → scheduler cannot use it for cooling")
            print("  → Must redesign: use DVFS (CPU freq reduction) as primary cooling mechanism")
            print("  → INT8 may still appear in paper as ablation to validate this finding")

    print()
    print("="*75)


if __name__ == "__main__":
    main()