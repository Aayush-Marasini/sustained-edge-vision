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
    # S0: FP32 @ 2400 MHz cap (ondemand, max)
    RunPair("S0_FP32_2400 rep1", "2026-04-30_inferonly_fp32_rep1.db", "2026-04-30_192521_inferonly_fp32_rep1"),
    RunPair("S0_FP32_2400 rep2", "2026-04-30_inferonly_fp32_rep2.db", "2026-04-30_193137_inferonly_fp32_rep2"),
    RunPair("S0_FP32_2400 rep3", "2026-04-30_inferonly_fp32_rep3.db", "2026-04-30_195420_inferonly_fp32_rep3"),
    # INT8 @ 2400 MHz (ablation — NOT thermally viable)
    RunPair("INT8_2400  rep1", "2026-05-01_inferonly_int8_rep1.db", "2026-05-01_201242_inferonly_int8_rep1"),
    RunPair("INT8_2400  rep2", "2026-05-01_inferonly_int8_rep2.db", "2026-05-01_201926_inferonly_int8_rep2"),
    RunPair("INT8_2400  rep3", "2026-05-01_inferonly_int8_rep3.db", "2026-05-01_203913_inferonly_int8_rep3"),
    # S1: FP32 @ 1800 MHz cap (moderate cooling state)
    RunPair("S1_FP32_1800 rep1", "2026-05-02_inferonly_fp32_1800mhz_rep1.db", "2026-05-02_020913_inferonly_fp32_1800mhz_rep1"),
    RunPair("S1_FP32_1800 rep2", "2026-05-02_inferonly_fp32_1800mhz_rep2.db", "2026-05-02_055730_inferonly_fp32_1800mhz_rep2"),
    RunPair("S1_FP32_1800 rep3", "2026-05-02_inferonly_fp32_1800mhz_rep3.db", "2026-05-02_060757_inferonly_fp32_1800mhz_rep3"),
    # S2: FP32 @ 1500 MHz cap (aggressive cooling state)
    RunPair("S2_FP32_1500 rep1", "2026-05-02_inferonly_fp32_1500mhz_rep1.db", "2026-05-02_061905_inferonly_fp32_1500mhz_rep1"),
    RunPair("S2_FP32_1500 rep2", "2026-05-02_inferonly_fp32_1500mhz_rep2.db", "2026-05-02_062948_inferonly_fp32_1500mhz_rep2"),
    RunPair("S2_FP32_1500 rep3", "2026-05-02_inferonly_fp32_1500mhz_rep3.db", "2026-05-02_063959_inferonly_fp32_1500mhz_rep3"),
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

    # Compute energy directly from power × time (don't trust ENERGY column units)
    # E = P_avg × duration  (Joules = Watts × seconds)
    avg_power_w    = statistics.mean(window_power)
    energy_window_j = avg_power_w * duration_window_s
    fps_actual  = frame_count / inference_duration_s if inference_duration_s > 0 else None
    j_per_frame    = avg_power_w / fps_actual if fps_actual else None
    # J/frame = W / FPS  (same as W × s/frame = W / (frames/s))

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

    # ── Aggregate by configuration group ─────────────────────────────────────
    def group(prefix):
        return [r for r in results if r.get("label","").startswith(prefix) and not r.get("error")]

    def agg(rows, key):
        vals = [r[key] for r in rows if r.get(key) is not None]
        if not vals:
            return None, None
        return statistics.mean(vals), statistics.pstdev(vals)

    groups = {
        "S0 FP32@2400": group("S0_FP32_2400"),
        "INT8@2400":     group("INT8_2400"),
        "S1 FP32@1800":  group("S1_FP32_1800"),
        "S2 FP32@1500":  group("S2_FP32_1500"),
    }

    print()
    print("="*85)
    print("DVFS CONFIGURATION COMPARISON (paper Table §V)")
    print("="*85)
    print(f"\n{'Config':<18} {'FPS':>12} {'Power(W)':>14} {'J/frame':>12} {'Power ratio':>13} {'J/frame ratio':>14}")
    print("-"*86)

    s0_fps, _ = agg(groups["S0 FP32@2400"], "fps")
    s0_pwr, _ = agg(groups["S0 FP32@2400"], "mean_power_w")
    s0_jpf, _ = agg(groups["S0 FP32@2400"], "j_per_frame")

    for name, grp in groups.items():
        fps_m, fps_s = agg(grp, "fps")
        pwr_m, pwr_s = agg(grp, "mean_power_w")
        jpf_m, jpf_s = agg(grp, "j_per_frame")
        if fps_m is None:
            print(f"  {name:<16} NO DATA")
            continue
        pwr_r = pwr_m / s0_pwr if s0_pwr else 0
        jpf_r = jpf_m / s0_jpf if s0_jpf else 0
        print(f"  {name:<16} "
              f"{fps_m:>6.3f}±{fps_s:.3f}  "
              f"{pwr_m:>6.3f}±{pwr_s:.3f}  "
              f"{jpf_m:>8.4f}±{jpf_s:.4f}  "
              f"{pwr_r:>10.3f}×  "
              f"{jpf_r:>11.3f}×")

    print()
    print("SCHEDULER VIABILITY SUMMARY:")
    for name, grp in groups.items():
        if name == "S0 FP32@2400":
            continue
        pwr_m, _ = agg(grp, "mean_power_w")
        jpf_m, _ = agg(grp, "j_per_frame")
        if pwr_m is None:
            continue
        pwr_r = pwr_m / s0_pwr
        jpf_r = jpf_m / s0_jpf
        thermal = "✓ THERMALLY VIABLE" if pwr_r < 0.90 else ("⚠ MARGINAL" if pwr_r < 0.95 else "✗ NOT VIABLE")
        energy  = "✓ ENERGY WIN" if jpf_r < 0.95 else ("~ NEUTRAL" if jpf_r < 1.10 else "✗ ENERGY WORSE")
        print(f"  {name:<16}: power={pwr_r:.3f}× ({thermal}), J/frame={jpf_r:.3f}× ({energy})")

    print()
    print("="*85)


if __name__ == "__main__":
    main()