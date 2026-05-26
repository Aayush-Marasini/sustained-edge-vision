#!/usr/bin/env python3
"""
compute_sustainability_metrics.py  v2
======================================
SUSCOM sustainability metrics across all 6 conditions.

FIX (v2): Replaced run_metadata.json-based discovery with the same hardcoded
MAPPING used by analyze_powerz_robust.py and generate_paper_figures.py.
Previous version silently dropped Reactive-Threshold and Proactive runs when
their metadata files were git-LFS pointers on Windows.

Inputs:
  05_results/power_analysis_robust.csv
  05_results/runs/.../telemetry_raw.csv
  05_results/runs/.../scheduler_decisions.csv (when present)

Outputs:
  05_results/sustainability_metrics.csv
"""
from __future__ import annotations

import csv
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Dict, List

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNS_DIR  = REPO_ROOT / "05_results" / "runs"
POWER_CSV = REPO_ROOT / "05_results" / "power_analysis_robust.csv"
OUTPUT    = REPO_ROOT / "05_results" / "sustainability_metrics.csv"

T_THROTTLE_C = 82.0
MAP50        = 0.538

MAPPING: Dict[str, List[str]] = {
    "Static-S0":  [
        "2026-05-03_012911_thermalval_S0",
        "2026-05-04_203732_thermalval_S0",
        "2026-05-05_011931_thermalval_S0",
    ],
    "Static-S1":  [
        "2026-05-03_021631_thermalval_S1",
        "2026-05-05_015938_thermalval_S1",
        "2026-05-05_171318_thermalval_S1",
    ],
    "Static-S2":  [
        "2026-05-03_053226_thermalval_S2",
        "2026-05-05_180734_thermalval_S2",
        "2026-05-05_200514_thermalval_S2",
    ],
    "Reactive-Threshold": [
        "2026-05-05_213247_scheduled_high_S0_rep1",
        "2026-05-05_220944_scheduled_high_S0_rep2",
        "2026-05-05_224659_scheduled_high_S0_rep3",
    ],
    "Proactive":  [
        "2026-05-06_011427_scheduled_high_S0_rep1",
        "2026-05-06_031811_scheduled_high_S0_rep2",
        "2026-05-06_035911_scheduled_high_S0_rep3",
    ],
    "Active-Oracle": [
        "2026-05-24_182759_thermalval_S0_active_cooling",
        "2026-05-24_190352_thermalval_S0_active_cooling",
        "2026-05-24_193737_thermalval_S0_active_cooling",
    ],
}


def per_run_metrics(run_dir: Path) -> Dict[str, float]:
    t_temp: List[float] = []
    T_soc:  List[float] = []
    throttle_flags: List[int] = []
    with open(run_dir / "telemetry_raw.csv", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                t = float(row["monotonic_offset_s"])
                if 10.0 <= t <= 1800.0:
                    t_temp.append(t)
                    T_soc.append(float(row["temp_soc_c"]))
                    throttle_flags.append(int(row["throttled_now"]))
            except (ValueError, KeyError):
                continue
    if not t_temp:
        return {}

    plateau_T = [T for t, T in zip(t_temp, T_soc) if t >= 1500.0]
    t_plateau = statistics.mean(plateau_T) if plateau_T else statistics.mean(T_soc)
    throttle_event_count  = sum(throttle_flags)
    throttle_exposure_pct = 100.0 * throttle_event_count / len(throttle_flags)

    # Time-to-throttle (TTT): first sample where throttled_now == 1
    ttt = None
    for t, f in zip(t_temp, throttle_flags):
        if f == 1:
            ttt = t
            break

    # Scheduler decisions
    n_decisions = 0
    overshoot = float("nan")
    decisions_path = run_dir / "scheduler_decisions.csv"
    if decisions_path.exists():
        try:
            with open(decisions_path, encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
            state_changes = []
            prev_state = None
            for r in rows:
                s = r["dvfs_state"].strip()
                if prev_state is not None and s != prev_state:
                    state_changes.append((float(r["monotonic_offset_s"]), s))
                prev_state = s
            n_decisions = len(state_changes)
            if state_changes:
                first_esc_t = state_changes[0][0]
                T_after = [T for t, T in zip(t_temp, T_soc) if t > first_esc_t]
                if T_after:
                    overshoot = max(T_after) - 79.0
        except Exception:
            pass

    # FPS — throughput method, matches analyze_powerz_robust.py
    first_t = last_t = None
    n = 0
    with open(run_dir / "inference_log.csv", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                t = float(row["monotonic_time_s"])
                if t < 10.0:
                    continue
                if first_t is None:
                    first_t = t
                last_t = t
                n += 1
            except (ValueError, KeyError):
                continue
    fps_mean = n / (last_t - first_t) if (last_t and first_t and n) else float("nan")

    return {
        "fps_mean": fps_mean,
        "t_plateau_c": t_plateau,
        "thermal_safety_margin_c": T_THROTTLE_C - t_plateau,
        "thermal_overshoot_c": overshoot,
        "throttle_event_count": throttle_event_count,
        "throttle_exposure_pct": throttle_exposure_pct,
        "scheduler_decision_count": n_decisions,
        "time_to_throttle_s": ttt if ttt is not None else float("nan"),
    }


def load_power_data() -> Dict[str, List[Dict[str, float]]]:
    if not POWER_CSV.exists():
        print(f"WARN: {POWER_CSV} missing. Run analyze_powerz_robust.py first.")
        return {}
    out: Dict[str, List[Dict[str, float]]] = defaultdict(list)
    with open(POWER_CSV, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            cond = row["condition"].replace(" (Ours)", "")
            out[cond].append({
                "mean_power_w": float(row["mean_power_w"]),
                "j_per_frame":  float(row["j_per_frame"]),
            })
    return out


def main():
    by_cond = {c: [RUNS_DIR / d for d in dirs] for c, dirs in MAPPING.items()}
    power_by_cond = load_power_data()

    print("Conditions:")
    for c, dirs in by_cond.items():
        n = sum(1 for d in dirs if d.exists())
        print(f"  {c:<22} {n}/{len(dirs)} dirs")

    oracle_fps = float("nan")
    if "Active-Oracle" in by_cond:
        rows = [per_run_metrics(d) for d in by_cond["Active-Oracle"] if d.exists()]
        rows = [r for r in rows if r]
        if rows:
            oracle_fps = statistics.mean(r["fps_mean"] for r in rows)

    aggregated = []
    for cond in ["Static-S0","Static-S1","Static-S2",
                 "Reactive-Threshold","Proactive","Active-Oracle"]:
        if cond not in by_cond:
            continue
        per_run = [per_run_metrics(d) for d in by_cond[cond] if d.exists()]
        per_run = [r for r in per_run if r]
        if not per_run:
            continue

        def avg(k):
            vals = [r[k] for r in per_run if r[k] == r[k]]
            return statistics.mean(vals) if vals else float("nan")
        def sd(k):
            vals = [r[k] for r in per_run if r[k] == r[k]]
            return statistics.pstdev(vals) if len(vals) > 1 else 0.0

        fps_mean = avg("fps_mean")
        if cond in power_by_cond:
            pw = power_by_cond[cond]
            power_mean = statistics.mean(r["mean_power_w"] for r in pw)
            jpf_mean   = statistics.mean(r["j_per_frame"]   for r in pw)
            j_per_correct = jpf_mean / MAP50
        else:
            power_mean = jpf_mean = j_per_correct = float("nan")

        passive_eff = fps_mean / oracle_fps if oracle_fps == oracle_fps else float("nan")

        ttt_val = avg("time_to_throttle_s")
        aggregated.append({
            "condition":               cond,
            "n_reps":                  len(per_run),
            "fps_mean":                round(fps_mean, 3),
            "fps_std":                 round(sd("fps_mean"), 4),
            "power_mean_w":            round(power_mean, 3),
            "j_per_frame":             round(jpf_mean, 4),
            "j_per_correct_detection": round(j_per_correct, 4),
            "t_plateau_c":             round(avg("t_plateau_c"), 2),
            "thermal_safety_margin_c": round(avg("thermal_safety_margin_c"), 2),
            "thermal_overshoot_c":     round(avg("thermal_overshoot_c"), 2) if avg("thermal_overshoot_c") == avg("thermal_overshoot_c") else "N/A",
            "throttle_event_count":    int(avg("throttle_event_count")),
            "throttle_exposure_pct":   round(avg("throttle_exposure_pct"), 2),
            "scheduler_decision_count": int(avg("scheduler_decision_count")),
            "time_to_throttle_s":      "N/A" if ttt_val != ttt_val else round(ttt_val, 1),
            "passive_cooling_efficiency_pct": round(100.0 * passive_eff, 1),
        })

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    if aggregated:
        with open(OUTPUT, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(aggregated[0].keys()))
            w.writeheader(); w.writerows(aggregated)

    print("\n" + "=" * 115)
    print("SUSCOM SUSTAINABILITY METRICS  (FPS from inference_log throughput method)")
    print("=" * 115)
    print(f"{'Cond':<22}{'FPS':>7}{'Pw_W':>7}{'J/fr':>7}{'J/det':>7}"
          f"{'T_pl':>7}{'Marg':>7}{'Over':>7}{'Throt':>8}{'Exp%':>7}{'Eff%':>7}")
    print("-" * 115)
    for r in aggregated:
        over = r["thermal_overshoot_c"]
        over_s = f"{over:>+5.1f}" if isinstance(over, float) else f"{'N/A':>5}"
        print(f"{r['condition']:<22}"
              f"{r['fps_mean']:>7.2f}"
              f"{r['power_mean_w']:>7.2f}"
              f"{r['j_per_frame']:>7.3f}"
              f"{r['j_per_correct_detection']:>7.3f}"
              f"{r['t_plateau_c']:>7.1f}"
              f"{r['thermal_safety_margin_c']:>+7.1f}"
              f"{over_s:>7}"
              f"{r['throttle_event_count']:>8}"
              f"{r['throttle_exposure_pct']:>7.1f}"
              f"{r['passive_cooling_efficiency_pct']:>7.1f}")


if __name__ == "__main__":
    main()