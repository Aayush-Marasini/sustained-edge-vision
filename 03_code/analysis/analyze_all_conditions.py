"""
analyze_all_conditions.py
Produces Table IV (main comparison table) from all 15 paper-quality runs.
Reads: telemetry_raw.csv, inference_log.csv, scheduler_decisions.csv
PowerZ analysis is handled separately by analyze_powerz_energy.py
Run from repo root on Windows.
"""
import pandas as pd
import numpy as np
import glob
from pathlib import Path

RUNS_ROOT = Path(__file__).resolve().parents[2] / "05_results" / "runs"

# ── Run directory mapping ─────────────────────────────────────────────
CONDITIONS = {
    "Static-S0": {
        "pattern": "*thermalval_S0*",
        "type": "static",
    },
    "Static-S1": {
        "pattern": "*thermalval_S1*",
        "type": "static",
    },
    "Static-S2": {
        "pattern": "*thermalval_S2*",
        "type": "static",
    },
    "Reactive-Threshold": {
        "pattern": "*213247*|*220944*|*224659*",
        "dirs": [
            "2026-05-05_213247_scheduled_high_S0_rep1",
            "2026-05-05_220944_scheduled_high_S0_rep2",
            "2026-05-05_224659_scheduled_high_S0_rep3",
        ],
        "type": "dynamic",
    },
    "Proactive (Ours)": {
        "dirs": [
            "2026-05-06_011427_scheduled_high_S0_rep1",
            "2026-05-06_031811_scheduled_high_S0_rep2",
            "2026-05-06_035911_scheduled_high_S0_rep3",
        ],
        "type": "dynamic",
    },
}

def get_dirs(cond_cfg):
    if "dirs" in cond_cfg:
        return [RUNS_ROOT / d for d in cond_cfg["dirs"]
                if (RUNS_ROOT / d).exists()]
    pattern = cond_cfg["pattern"]
    return sorted([Path(p) for p in glob.glob(str(RUNS_ROOT / pattern))
                   if Path(p).is_dir() and
                   (Path(p) / "telemetry_raw.csv").exists()])

def analyze_run(run_dir: Path, cond_type: str) -> dict:
    tel = pd.read_csv(run_dir / "telemetry_raw.csv")
    inf = pd.read_csv(run_dir / "inference_log.csv")

    # ── FPS from inference log ────────────────────────────────────────
    # inference_log has latency_ms column
    if "latency_ms" in inf.columns:
        fps_series = 1000.0 / inf["latency_ms"].replace(0, np.nan).dropna()
    else:
        # fallback: compute from frame timestamps if available
        fps_series = pd.Series(dtype=float)

    fps_mean = float(fps_series.mean()) if len(fps_series) > 0 else np.nan
    fps_std  = float(fps_series.std())  if len(fps_series) > 0 else np.nan
    fps_cv   = fps_std / fps_mean * 100 if fps_mean > 0 else np.nan

    # ── Throttle events ───────────────────────────────────────────────
    n_throttle = int(tel["throttled_now"].sum())

    # ── Temperature plateau (last 600s = stable window) ───────────────
    t_max = tel["monotonic_offset_s"].max()
    stable = tel[tel["monotonic_offset_s"] > t_max - 600]
    t_plateau = float(stable["temp_soc_c"].mean())
    t_peak    = float(tel["temp_soc_c"].max())

    result = {
        "fps_mean": fps_mean,
        "fps_std":  fps_std,
        "fps_cv":   fps_cv,
        "n_throttle": n_throttle,
        "t_plateau": t_plateau,
        "t_peak":    t_peak,
        "n_samples": len(tel),
    }

    # ── Time at each DVFS state (dynamic runs only) ───────────────────
    if cond_type == "dynamic":
        sched_f = run_dir / "scheduler_decisions.csv"
        if sched_f.exists():
            sched = pd.read_csv(sched_f)
            sched = sched.sort_values("monotonic_offset_s")
            total_t = t_max

            # Build state timeline
            times = sched["monotonic_offset_s"].tolist()
            states = sched["dvfs_state"].tolist()

            time_in_state = {"S0": 0.0, "S1": 0.0, "S2": 0.0}
            for i in range(len(times)):
                t_start = times[i]
                t_end   = times[i+1] if i+1 < len(times) else total_t
                state   = states[i]
                if state in time_in_state:
                    time_in_state[state] += (t_end - t_start)

            result["time_S0_s"] = time_in_state["S0"]
            result["time_S1_s"] = time_in_state["S1"]
            result["time_S2_s"] = time_in_state["S2"]
            result["pct_S1"]    = time_in_state["S1"] / total_t * 100

    return result

# ── Main ──────────────────────────────────────────────────────────────
print("\n" + "="*100)
print("MAIN COMPARISON TABLE — ALL CONDITIONS")
print("="*100)

hdr = (f"{'Condition':<22} {'N':>2} {'FPS mean':>9} {'FPS std':>8} "
       f"{'FPS CV':>7} {'Throttle/30min':>15} "
       f"{'T_plateau':>10} {'T_peak':>8}")
print(hdr)
print("-"*100)

all_results = {}

for cond_name, cond_cfg in CONDITIONS.items():
    dirs = get_dirs(cond_cfg)
    if not dirs:
        print(f"{cond_name:<22}  NO RUNS FOUND")
        continue

    reps = [analyze_run(d, cond_cfg["type"]) for d in dirs]
    n = len(reps)

    fps_means   = [r["fps_mean"]   for r in reps]
    fps_stds    = [r["fps_std"]    for r in reps]
    n_throttles = [r["n_throttle"] for r in reps]
    t_plateaus  = [r["t_plateau"]  for r in reps]
    fps_cv_vals = [r["fps_cv"]     for r in reps]

    fps_mean_agg   = np.mean(fps_means)
    fps_std_agg    = np.mean(fps_stds)
    fps_cv_agg     = fps_std_agg / fps_mean_agg * 100
    throttle_mean  = np.mean(n_throttles)
    throttle_std   = np.std(n_throttles)
    t_plateau_mean = np.mean(t_plateaus)
    t_plateau_std  = np.std(t_plateaus)
    t_peak_mean    = np.mean([r["t_peak"] for r in reps])

    print(
        f"{cond_name:<22} {n:>2} "
        f"{fps_mean_agg:>9.3f} "
        f"{fps_std_agg:>8.3f} "
        f"{fps_cv_agg:>6.1f}% "
        f"{throttle_mean:>12.0f}±{throttle_std:<3.0f} "
        f"{t_plateau_mean:>7.1f}±{t_plateau_std:.1f} "
        f"{t_peak_mean:>8.1f}"
    )

    all_results[cond_name] = reps

    # Time-at-state for dynamic conditions
    if cond_cfg["type"] == "dynamic" and "time_S1_s" in reps[0]:
        s0_times = [r.get("time_S0_s", 0) for r in reps]
        s1_times = [r.get("time_S1_s", 0) for r in reps]
        s2_times = [r.get("time_S2_s", 0) for r in reps]
        print(f"  {'':22} Time at S0: {np.mean(s0_times):.0f}s  "
              f"S1: {np.mean(s1_times):.0f}s ({np.mean([r['pct_S1'] for r in reps]):.1f}%)  "
              f"S2: {np.mean(s2_times):.0f}s")

print("="*100)

# ── Per-rep detail for key conditions ────────────────────────────────
print("\n── Per-rep detail: Proactive (Ours) ──")
for i, (d, r) in enumerate(zip(
        get_dirs(CONDITIONS["Proactive (Ours)"]),
        all_results.get("Proactive (Ours)", []))):
    print(f"  rep{i+1} ({d.name[:19]}): "
          f"FPS={r['fps_mean']:.3f} CV={r['fps_cv']:.1f}% "
          f"throttle={r['n_throttle']} "
          f"T_pl={r['t_plateau']:.1f}°C "
          f"S1={r.get('time_S1_s',0):.0f}s "
          f"S2={r.get('time_S2_s',0):.0f}s")

print("\n── Per-rep detail: Reactive-Threshold ──")
for i, (d, r) in enumerate(zip(
        get_dirs(CONDITIONS["Reactive-Threshold"]),
        all_results.get("Reactive-Threshold", []))):
    print(f"  rep{i+1} ({d.name[:19]}): "
          f"FPS={r['fps_mean']:.3f} CV={r['fps_cv']:.1f}% "
          f"throttle={r['n_throttle']} "
          f"T_pl={r['t_plateau']:.1f}°C "
          f"S1={r.get('time_S1_s',0):.0f}s "
          f"S2={r.get('time_S2_s',0):.0f}s")