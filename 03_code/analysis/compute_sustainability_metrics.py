#!/usr/bin/env python3
"""
compute_sustainability_metrics.py
=================================
Computes all SUSCOM-relevant sustainability metrics from existing run data.

Inputs:
  05_results/power_analysis_robust.csv  (from analyze_powerz_robust.py)
  05_results/runs/.../telemetry_raw.csv  (Pi telemetry)
  05_results/runs/.../scheduler_decisions.csv  (when present)

Outputs:
  05_results/sustainability_metrics.csv

Metrics computed per condition (mean ± std across reps):
  fps_mean, fps_cv_pct        — throughput + stability
  power_mean_w, j_per_frame   — energy efficiency
  j_per_correct_detection     — j_per_frame / mAP50 (mAP50 = 0.538 deployed)
  throttle_event_count        — total samples with throttled_now=1
  throttle_exposure_pct       — % of inference samples throttled
  t_plateau_c                 — mean of last-300-seconds temperatures
  thermal_safety_margin_c     — T_throttle (82°C) - t_plateau
  thermal_overshoot_c         — max T after first DVFS escalation - T_esc threshold
  scheduler_decision_count    — total scheduler state changes
  passive_cooling_efficiency  — fps_mean / oracle_fps_mean
"""
from __future__ import annotations

import csv
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNS_DIR  = REPO_ROOT / "05_results" / "runs"
POWER_CSV = REPO_ROOT / "05_results" / "power_analysis_robust.csv"
OUTPUT    = REPO_ROOT / "05_results" / "sustainability_metrics.csv"

T_THROTTLE_C = 82.0   # Pi 5 kernel soft throttle onset (empirically ~82°C)
MAP50        = 0.538  # Deployed OpenVINO FP32 mAP50 from HANDOFF v0.9.7


# ---------- Run discovery (matches generate_paper_figures.py) ----------

def discover_runs() -> Dict[str, List[Path]]:
    by_cond: Dict[str, List[Path]] = defaultdict(list)
    for d in sorted(RUNS_DIR.iterdir()):
        if not d.is_dir():
            continue
        name = d.name
        if any(x in name for x in ("smoketest", "dht11_integration", "smoke",
                                    "pilot", "high_ambient", "practice")):
            continue
        if "active_cooling" in name:
            by_cond["Active-Oracle"].append(d)
        elif "thermalval_S0" in name:
            by_cond["Static-S0"].append(d)
        elif "thermalval_S1" in name:
            by_cond["Static-S1"].append(d)
        elif "thermalval_S2" in name:
            by_cond["Static-S2"].append(d)
        elif "scheduled" in name:
            meta_path = d / "run_metadata.json"
            if not meta_path.exists():
                continue
            import json
            mode = json.loads(meta_path.read_text()).get("scheduler_mode", "")
            if mode == "reactive_threshold":
                by_cond["Reactive-Threshold"].append(d)
            elif mode == "proactive":
                by_cond["Proactive"].append(d)
    return by_cond


# ---------- Per-run metric extraction ----------

def per_run_metrics(run_dir: Path) -> Dict[str, float]:
    """Extract all telemetry-based metrics for one run."""
    t_temp: List[float] = []
    T_soc:  List[float] = []
    throttle_flags: List[int] = []

    with open(run_dir / "telemetry_raw.csv", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                t = float(row["monotonic_offset_s"])
                if 10.0 <= t <= 1800.0:  # skip first 10s startup
                    t_temp.append(t)
                    T_soc.append(float(row["temp_soc_c"]))
                    throttle_flags.append(int(row["throttled_now"]))
            except (ValueError, KeyError):
                continue

    if not t_temp:
        return {}

    # Last 5 minutes (plateau)
    plateau_T = [T for t, T in zip(t_temp, T_soc) if t >= 1500.0]
    t_plateau = statistics.mean(plateau_T) if plateau_T else statistics.mean(T_soc)

    # Throttle metrics
    throttle_event_count = sum(throttle_flags)
    throttle_exposure_pct = 100.0 * throttle_event_count / len(throttle_flags)

    # Thermal overshoot: max T after t=10s minus highest T_esc threshold (79°C if scheduler, else N/A)
    decisions_path = run_dir / "scheduler_decisions.csv"
    overshoot = float("nan")
    n_decisions = 0
    if decisions_path.exists():
        try:
            with open(decisions_path, encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
            # Count meaningful decisions (escalations + recoveries)
            state_changes = []
            prev_state = None
            for r in rows:
                s = r["dvfs_state"].strip()
                if prev_state is not None and s != prev_state:
                    state_changes.append((float(r["monotonic_offset_s"]), s))
                prev_state = s
            n_decisions = len(state_changes)
            # Overshoot = max T after first escalation - 79°C target
            if state_changes:
                first_esc_t = state_changes[0][0]
                T_after = [T for t, T in zip(t_temp, T_soc) if t > first_esc_t]
                if T_after:
                    overshoot = max(T_after) - 79.0
        except Exception:
            pass

    # FPS from inference log
    fps_values: List[float] = []
    with open(run_dir / "inference_log.csv", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                t = float(row["monotonic_time_s"])
                lat = float(row["latency_ms"])
                if t >= 10.0 and lat > 0:
                    fps_values.append(1000.0 / lat)
            except (ValueError, KeyError):
                continue
    fps_mean = statistics.mean(fps_values) if fps_values else float("nan")
    fps_std  = statistics.pstdev(fps_values) if len(fps_values) > 1 else 0.0
    fps_cv_pct = 100.0 * fps_std / fps_mean if fps_mean > 0 else float("nan")

    return {
        "fps_mean":              fps_mean,
        "fps_std":               fps_std,
        "fps_cv_pct":            fps_cv_pct,
        "t_plateau_c":           t_plateau,
        "thermal_safety_margin_c": T_THROTTLE_C - t_plateau,
        "thermal_overshoot_c":   overshoot,
        "throttle_event_count":  throttle_event_count,
        "throttle_exposure_pct": throttle_exposure_pct,
        "scheduler_decision_count": n_decisions,
    }


# ---------- Main aggregation ----------

def load_power_data() -> Dict[str, List[Dict[str, float]]]:
    """Return {condition: [{mean_power_w, j_per_frame, fps_mean}]} from robust analysis."""
    if not POWER_CSV.exists():
        print(f"WARNING: {POWER_CSV} missing. Run analyze_powerz_robust.py first.")
        return {}
    out: Dict[str, List[Dict[str, float]]] = defaultdict(list)
    with open(POWER_CSV, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            cond = row["condition"].replace(" (Ours)", "")
            out[cond].append({
                "mean_power_w": float(row["mean_power_w"]),
                "j_per_frame":  float(row["j_per_frame"]),
                "fps_mean_pz":  float(row["fps_mean"]),
            })
    return out


def main() -> None:
    by_cond = discover_runs()
    power_by_cond = load_power_data()

    print(f"\nConditions discovered:")
    for c, dirs in by_cond.items():
        print(f"  {c:<22} {len(dirs)} reps")

    # Oracle FPS for passive cooling efficiency
    oracle_fps = float("nan")
    if "Active-Oracle" in by_cond:
        oracle_runs = [per_run_metrics(d) for d in by_cond["Active-Oracle"]]
        oracle_fps = statistics.mean(r["fps_mean"] for r in oracle_runs if r)

    # Per-condition aggregation
    aggregated = []
    for cond in ["Static-S0", "Static-S1", "Static-S2",
                 "Reactive-Threshold", "Proactive", "Active-Oracle"]:
        if cond not in by_cond:
            continue

        per_run = [per_run_metrics(d) for d in by_cond[cond]]
        per_run = [r for r in per_run if r]
        if not per_run:
            continue

        def avg(key: str) -> float:
            vals = [r[key] for r in per_run if not (r[key] != r[key])]  # nan filter
            return statistics.mean(vals) if vals else float("nan")

        def sd(key: str) -> float:
            vals = [r[key] for r in per_run if not (r[key] != r[key])]
            return statistics.pstdev(vals) if len(vals) > 1 else 0.0

        fps_mean   = avg("fps_mean")
        fps_cv     = avg("fps_cv_pct")
        t_plat     = avg("t_plateau_c")
        margin     = avg("thermal_safety_margin_c")
        overshoot  = avg("thermal_overshoot_c")
        thr_count  = avg("throttle_event_count")
        thr_exp    = avg("throttle_exposure_pct")
        n_dec      = avg("scheduler_decision_count")

        # Power data (paired)
        if cond in power_by_cond:
            pw = power_by_cond[cond]
            power_mean = statistics.mean(r["mean_power_w"] for r in pw)
            jpf_mean   = statistics.mean(r["j_per_frame"]   for r in pw)
            jpf_std    = statistics.pstdev(r["j_per_frame"] for r in pw)
            j_per_correct = jpf_mean / MAP50
        else:
            power_mean = jpf_mean = jpf_std = j_per_correct = float("nan")

        passive_eff = fps_mean / oracle_fps if oracle_fps and oracle_fps == oracle_fps else float("nan")

        aggregated.append({
            "condition":               cond,
            "n_reps":                  len(per_run),
            "fps_mean":                round(fps_mean, 3),
            "fps_std":                 round(sd("fps_mean"), 3),
            "fps_cv_pct":              round(fps_cv, 1),
            "power_mean_w":            round(power_mean, 3),
            "j_per_frame":             round(jpf_mean, 4),
            "j_per_frame_std":         round(jpf_std, 4),
            "j_per_correct_detection": round(j_per_correct, 4),
            "t_plateau_c":             round(t_plat, 2),
            "thermal_safety_margin_c": round(margin, 2),
            "thermal_overshoot_c":     round(overshoot, 2) if overshoot == overshoot else "N/A",
            "throttle_event_count":    int(thr_count) if thr_count == thr_count else 0,
            "throttle_exposure_pct":   round(thr_exp, 2),
            "scheduler_decision_count": int(n_dec) if n_dec == n_dec else 0,
            "passive_cooling_efficiency_pct": round(100.0 * passive_eff, 1),
        })

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    if aggregated:
        with open(OUTPUT, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(aggregated[0].keys()))
            w.writeheader(); w.writerows(aggregated)

    # Print summary
    print("\n" + "=" * 110)
    print("SUSCOM SUSTAINABILITY METRICS")
    print("=" * 110)
    hdr = ["Condition", "FPS", "CV%", "Pow_W", "J/frm", "J/det", "T_plat", "Safety",
           "Throt", "Exp%", "Eff%"]
    print(f"{hdr[0]:<22}{hdr[1]:>7}{hdr[2]:>6}{hdr[3]:>8}{hdr[4]:>8}"
          f"{hdr[5]:>8}{hdr[6]:>8}{hdr[7]:>8}{hdr[8]:>8}{hdr[9]:>7}{hdr[10]:>7}")
    print("-" * 110)
    for r in aggregated:
        print(f"{r['condition']:<22}"
              f"{r['fps_mean']:>7.2f}"
              f"{r['fps_cv_pct']:>6.1f}"
              f"{r['power_mean_w']:>8.2f}"
              f"{r['j_per_frame']:>8.3f}"
              f"{r['j_per_correct_detection']:>8.3f}"
              f"{r['t_plateau_c']:>8.1f}"
              f"{r['thermal_safety_margin_c']:>8.1f}"
              f"{r['throttle_event_count']:>8}"
              f"{r['throttle_exposure_pct']:>7.1f}"
              f"{r['passive_cooling_efficiency_pct']:>7.1f}")
    print(f"\nSaved → {OUTPUT.relative_to(REPO_ROOT)}")
    print(f"\n(mAP50 = {MAP50} from deployed OpenVINO FP32, n=481 val images)")


if __name__ == "__main__":
    main()