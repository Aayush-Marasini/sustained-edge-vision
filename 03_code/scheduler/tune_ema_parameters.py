"""
EMA parameter tuning for the scheduler's derivative estimator.

Sweeps (alpha, derivative_stride) pairs against the 4 calibration
traces collected in Phase B. Selects the pair on the Pareto frontier
of (noise variance, response lag) with the lowest noise subject to
lag <= 2.0 seconds.

Outputs:
  - 05_results/calibration_analysis/pareto_alpha_stride.png
  - 05_results/calibration_analysis/tuning_report.md
  - 05_results/calibration_analysis/sweep_raw_data.csv

This script is read-only with respect to the calibration runs and
derivatives.py. It does NOT mutate the source calibration data and
prints recommended parameter values for the operator to apply manually
to derivatives.py DEFAULT_CONFIG_5HZ. This preserves the No Silent
Changes Rule from the WorkPlan.
"""
from __future__ import annotations

import csv
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# --- Path bootstrap so we can import derivatives module ---------------------
_THIS = Path(__file__).resolve()
_REPO_ROOT = _THIS.parent.parent.parent  # research_project/
_CODE_ROOT = _REPO_ROOT / "03_code"
sys.path.insert(0, str(_CODE_ROOT))

# We re-implement EMA + derivative locally rather than importing from
# scheduler.derivatives, so we can sweep without monkey-patching.

import numpy as np
import matplotlib

matplotlib.use("Agg")  # headless, for paper figure rendering
import matplotlib.pyplot as plt


# --- Sweep grid -------------------------------------------------------------
ALPHA_GRID = [0.10, 0.15, 0.20, 0.25, 0.30]
STRIDE_GRID = [3, 5, 7, 10]
SAMPLING_RATE_HZ = 5.0  # must match what's in derivatives.py

# Selection criterion threshold
LAG_BUDGET_SEC = 10.0  # 90% rise time budget matching Pi 5 passive cooling thermal RC


# --- Calibration run inventory ----------------------------------------------
CALIB_RUNS_DIR = _REPO_ROOT / "05_results" / "runs"
OUTPUT_DIR = _REPO_ROOT / "05_results" / "calibration_analysis"


@dataclass
class CalibRun:
    name: str
    workload: str  # "idle" or "stress"
    csv_path: Path
    metadata_path: Path


def discover_calibration_runs() -> List[CalibRun]:
    """Find all calibration runs by directory name pattern."""
    runs: List[CalibRun] = []
    for d in sorted(CALIB_RUNS_DIR.glob("*calib_*")):
        if not d.is_dir():
            continue
        csv_path = d / "telemetry_raw.csv"
        meta_path = d / "run_metadata.json"
        if not csv_path.exists() or not meta_path.exists():
            print(f"WARN: skipping {d.name} (missing files)")
            continue
        if "idle" in d.name:
            workload = "idle"
        elif "stress" in d.name:
            workload = "stress"
        else:
            workload = "unknown"
        runs.append(CalibRun(name=d.name, workload=workload,
                             csv_path=csv_path, metadata_path=meta_path))
    return runs


# --- Signal loading ---------------------------------------------------------
def load_telemetry(csv_path: Path) -> Dict[str, np.ndarray]:
    """Load a telemetry_raw.csv into numpy arrays."""
    cols = {
        "monotonic_offset_s": [], "temp_soc_c": [], "volt_core_v": [],
        "cpu_util_percent": [], "cpu_freq_mhz": [],
    }
    with open(csv_path, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            for k in cols:
                v = row.get(k, "")
                cols[k].append(float(v) if v not in ("", "None") else math.nan)
    return {k: np.asarray(v, dtype=np.float64) for k, v in cols.items()}


# --- EMA + finite-difference derivative ------------------------------------
def ema_smooth(x: np.ndarray, alpha: float) -> np.ndarray:
    """Recursive EMA: y[t] = alpha*x[t] + (1-alpha)*y[t-1]. NaN-safe."""
    y = np.empty_like(x)
    state = math.nan
    for i in range(len(x)):
        xi = x[i]
        if math.isnan(xi):
            y[i] = state if not math.isnan(state) else math.nan
            continue
        if math.isnan(state):
            state = xi
        else:
            state = alpha * xi + (1.0 - alpha) * state
        y[i] = state
    return y


def derivative_strided(y_smooth: np.ndarray, stride: int,
                       dt_per_sample: float) -> np.ndarray:
    """First-order finite difference over a stride-sample window.
    Output is aligned to the LATER of the two samples; first `stride`
    values are NaN."""
    n = len(y_smooth)
    out = np.full(n, math.nan, dtype=np.float64)
    window_dt = stride * dt_per_sample
    for i in range(stride, n):
        a, b = y_smooth[i - stride], y_smooth[i]
        if math.isnan(a) or math.isnan(b):
            continue
        out[i] = (b - a) / window_dt
    return out


# --- Metrics ----------------------------------------------------------------
def steady_state_window(t: np.ndarray, workload: str) -> Tuple[int, int]:
    """Return [start_idx, end_idx) of the steady-state window.
    Idle: last 5 minutes (1500 samples at 5Hz).
    Stress: minutes 10-25 (samples 3000-7500 at 5Hz) -- after thermal soak,
    before cooldown begins when stress-ng exits."""
    if workload == "idle":
        return max(0, len(t) - 1500), len(t)
    elif workload == "stress":
        return 3000, 7500
    return 0, len(t)


def transition_window(t: np.ndarray, workload: str) -> Optional[Tuple[int, int]]:
    """For stress runs, the heating ramp occurs from t=10s (when stress-ng
    starts after a 10s idle baseline) to t=70s (when thermal equilibrium
    is being approached). This is samples 50-350 at 5 Hz. Idle runs have
    no clear transition."""
    if workload != "stress":
        return None
    # Heating ramp window: t=10s (sample 50) to t=70s (sample 350)
    return 50, min(350, len(t))


def noise_variance(dot_signal: np.ndarray, window: Tuple[int, int]) -> float:
    """Std dev of the derivative signal during a steady state.
    Lower = less noisy = better."""
    seg = dot_signal[window[0]:window[1]]
    seg = seg[~np.isnan(seg)]
    if len(seg) < 10:
        return math.nan
    return float(np.std(seg))


def response_lag_sec(dot_signal: np.ndarray, window: Tuple[int, int],
                     dt_per_sample: float) -> float:
    """Estimate response lag as the 90% rise time: time from the start
    of the heating ramp to when T_dot reaches 90% of its peak value.
    This is a standard control-systems metric for step response speed.

    Lower = faster response = better."""
    seg = dot_signal[window[0]:window[1]]
    if len(seg) < 5 or np.all(np.isnan(seg)):
        return math.nan
    
    # Find peak value in the window
    valid = ~np.isnan(seg)
    if not valid.any():
        return math.nan
    seg_valid = seg.copy()
    seg_valid[~valid] = 0.0
    peak_value = float(np.max(seg_valid))
    
    if peak_value <= 0.0:
        return math.nan
    
    # Find first index where signal crosses 90% of peak
    threshold = 0.9 * peak_value
    for i, val in enumerate(seg):
        if not math.isnan(val) and val >= threshold:
            return i * dt_per_sample
    
    # Never reached 90% in the window
    return math.nan


# --- Sweep ------------------------------------------------------------------
@dataclass
class SweepResult:
    alpha: float
    stride: int
    noise_idle: float       # mean across idle runs
    noise_stress: float     # mean across stress runs (steady state)
    noise_combined: float   # 0.5*idle + 0.5*stress
    lag_heating: float      # mean across stress runs (heating ramp)


def run_sweep(runs: List[CalibRun]) -> List[SweepResult]:
    dt = 1.0 / SAMPLING_RATE_HZ
    results: List[SweepResult] = []

    # Pre-load all telemetry once
    loaded: Dict[str, Dict[str, np.ndarray]] = {}
    for r in runs:
        print(f"loading {r.name}...")
        loaded[r.name] = load_telemetry(r.csv_path)

    for alpha in ALPHA_GRID:
        for stride in STRIDE_GRID:
            noise_idle_list, noise_stress_list, lag_list = [], [], []

            for r in runs:
                data = loaded[r.name]
                t_signal = data["temp_soc_c"]

                # Smooth then differentiate
                t_smooth = ema_smooth(t_signal, alpha)
                t_dot = derivative_strided(t_smooth, stride, dt)

                ss_win = steady_state_window(t_signal, r.workload)
                noise = noise_variance(t_dot, ss_win)
                if r.workload == "idle":
                    noise_idle_list.append(noise)
                elif r.workload == "stress":
                    noise_stress_list.append(noise)

                trans_win = transition_window(t_signal, r.workload)
                if trans_win is not None:
                    lag = response_lag_sec(t_dot, trans_win, dt)
                    if not math.isnan(lag):
                        lag_list.append(lag)

            noise_idle = float(np.nanmean(noise_idle_list)) if noise_idle_list else math.nan
            noise_stress = float(np.nanmean(noise_stress_list)) if noise_stress_list else math.nan
            noise_combined = float(np.nanmean([noise_idle, noise_stress]))
            lag_heating = float(np.nanmean(lag_list)) if lag_list else math.nan

            results.append(SweepResult(
                alpha=alpha, stride=stride,
                noise_idle=noise_idle, noise_stress=noise_stress,
                noise_combined=noise_combined,
                lag_heating=lag_heating,
            ))
    return results


# --- Pareto + selection -----------------------------------------------------
def pareto_frontier(results: List[SweepResult]) -> List[SweepResult]:
    """A point is Pareto-optimal if no other point has both lower noise
    AND lower lag."""
    frontier: List[SweepResult] = []
    for r in results:
        if math.isnan(r.noise_combined) or math.isnan(r.lag_heating):
            continue
        dominated = False
        for s in results:
            if s is r or math.isnan(s.noise_combined) or math.isnan(s.lag_heating):
                continue
            if (s.noise_combined <= r.noise_combined and
                s.lag_heating <= r.lag_heating and
                (s.noise_combined < r.noise_combined or
                 s.lag_heating < r.lag_heating)):
                dominated = True
                break
        if not dominated:
            frontier.append(r)
    return frontier


def select_best(frontier: List[SweepResult]) -> Optional[SweepResult]:
    """Lowest noise subject to lag <= LAG_BUDGET_SEC."""
    feasible = [r for r in frontier if r.lag_heating <= LAG_BUDGET_SEC]
    if not feasible:
        # Constraint infeasible -- fall back to lowest lag overall
        return min(frontier, key=lambda r: r.lag_heating) if frontier else None
    return min(feasible, key=lambda r: r.noise_combined)


# --- Plot + report ----------------------------------------------------------
def plot_pareto(results: List[SweepResult], frontier: List[SweepResult],
                best: Optional[SweepResult], output_path: Path) -> None:
    fig, ax = plt.subplots(figsize=(8, 6), dpi=150)

    # All points
    for r in results:
        if math.isnan(r.noise_combined) or math.isnan(r.lag_heating):
            continue
        ax.scatter(r.lag_heating, r.noise_combined,
                   c="#888888", s=30, zorder=2)
        ax.annotate(f"a={r.alpha},s={r.stride}",
                    (r.lag_heating, r.noise_combined),
                    xytext=(4, 4), textcoords="offset points",
                    fontsize=7, color="#444444")

    # Frontier
    front_sorted = sorted(frontier, key=lambda r: r.lag_heating)
    if front_sorted:
        ax.plot([r.lag_heating for r in front_sorted],
                [r.noise_combined for r in front_sorted],
                "o-", color="#1f77b4", linewidth=2, markersize=8,
                label="Pareto frontier", zorder=3)

    # Selected point
    if best is not None:
        ax.scatter([best.lag_heating], [best.noise_combined],
                   c="#d62728", s=200, marker="*",
                   edgecolors="black", linewidths=1.5,
                   label=f"Selected: alpha={best.alpha}, stride={best.stride}",
                   zorder=4)

    ax.axvline(LAG_BUDGET_SEC, linestyle="--", color="#888888",
               linewidth=1, label=f"Lag budget ({LAG_BUDGET_SEC}s)")
    ax.set_xlabel("90% rise time (heating ramp) [s]")
    ax.set_ylabel("Steady-state noise std (T_dot) [C/s]")
    ax.set_title("EMA parameter sweep: noise vs response lag")
    ax.legend(loc="best", fontsize=9)
    ax.grid(True, linestyle=":", linewidth=0.5)
    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"wrote {output_path}")


def write_csv(results: List[SweepResult], output_path: Path) -> None:
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["alpha", "stride", "noise_idle", "noise_stress",
                    "noise_combined", "lag_heating_sec"])
        for r in results:
            w.writerow([r.alpha, r.stride,
                        r.noise_idle, r.noise_stress,
                        r.noise_combined, r.lag_heating])
    print(f"wrote {output_path}")


def write_report(results: List[SweepResult], frontier: List[SweepResult],
                 best: Optional[SweepResult], runs: List[CalibRun],
                 output_path: Path) -> None:
    lines = ["# Phase B.5 EMA Parameter Tuning Report",
             "",
             "## Methodology",
             "",
             f"Swept alpha in {ALPHA_GRID} and derivative_stride in {STRIDE_GRID}",
             f"({len(ALPHA_GRID) * len(STRIDE_GRID)} pairs total).",
             "",
             "For each (alpha, stride) pair, computed across all calibration",
             "runs:",
             "- **Steady-state noise variance**: std dev of T_dot during",
             "  idle plateau (last 5 min of idle runs) and stress soak",
             "  (minutes 10-25 of stress runs).",
             "- **Response lag (90% rise time)**: time from heating ramp",
             "  start (t=10s, when stress-ng begins) to when T_dot reaches",
             "  90% of its peak value. Standard control-systems metric for",
             "  step response speed.",
             "Selection criterion: minimize combined noise (mean of idle",
             f"and stress noise) subject to response lag <= {LAG_BUDGET_SEC}s.",
             "",
             "## Calibration Runs Used",
             "",
             "| Run | Workload |",
             "|-----|----------|"]
    for r in runs:
        lines.append(f"| {r.name} | {r.workload} |")
    lines += ["",
              "## Sweep Results (sorted by combined noise, ascending)",
              "",
              "| alpha | stride | noise_idle | noise_stress | noise_combined | lag_heating_sec |",
              "|-------|--------|------------|--------------|----------------|-----------------|"]
    for r in sorted(results, key=lambda x: x.noise_combined):
        lines.append(f"| {r.alpha} | {r.stride} | {r.noise_idle:.4f} | "
                     f"{r.noise_stress:.4f} | {r.noise_combined:.4f} | "
                     f"{r.lag_heating:.3f} |")
    lines += ["",
              "## Pareto Frontier",
              ""]
    if frontier:
        lines.append("Pareto-optimal pairs (no other pair has both lower noise AND lower lag):")
        lines.append("")
        for r in sorted(frontier, key=lambda x: x.lag_heating):
            lines.append(f"- alpha={r.alpha}, stride={r.stride} -> "
                         f"noise={r.noise_combined:.4f}, lag={r.lag_heating:.3f}s")
    else:
        lines.append("(empty — sweep produced no usable points)")
    lines += ["",
              "## Selected Configuration"]
    if best is not None:
        lines += ["",
                  f"**alpha = {best.alpha}**",
                  f"**derivative_stride = {best.stride}**",
                  "",
                  f"- Combined noise: {best.noise_combined:.4f} C/s",
                  f"- 90% rise time: {best.lag_heating:.3f} s",
                  f"  ({'within' if best.lag_heating <= LAG_BUDGET_SEC else 'EXCEEDS'} {LAG_BUDGET_SEC}s budget)",
                  "",
                  "## Action Required (Manual)",
                  "",
                  "Update `03_code/scheduler/derivatives.py` `DEFAULT_CONFIG_5HZ`:",
                  "```python",
                  "DEFAULT_CONFIG_5HZ = DerivativeConfig(",
                  f"    alpha={best.alpha},",
                  f"    derivative_stride={best.stride},",
                  "    sampling_rate_hz=5.0,",
                  ")",
                  "```",
                  "",
                  "Re-run `python tests/test_derivatives.py`. All 9 tests must pass."]
    else:
        lines += ["",
                  "**SWEEP FAILED** — no feasible (alpha, stride) pair found.",
                  "Investigate calibration data quality."]
    output_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {output_path}")


# --- Main -------------------------------------------------------------------
def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    runs = discover_calibration_runs()
    if not runs:
        print("ERROR: no calibration runs found in", CALIB_RUNS_DIR)
        return 1
    print(f"Found {len(runs)} calibration runs:")
    for r in runs:
        print(f"  - {r.name}  ({r.workload})")
    print()

    print("Running sweep...")
    results = run_sweep(runs)
    print(f"Got {len(results)} sweep points")
    print()

    frontier = pareto_frontier(results)
    print(f"Pareto frontier has {len(frontier)} points")
    best = select_best(frontier)
    if best is not None:
        print(f"Selected: alpha={best.alpha}, stride={best.stride} "
              f"(noise={best.noise_combined:.4f}, "
              f"lag={best.lag_heating:.3f}s)")
    else:
        print("No best point selected (sweep failed?)")
    print()

    write_csv(results, OUTPUT_DIR / "sweep_raw_data.csv")
    plot_pareto(results, frontier, best, OUTPUT_DIR / "pareto_alpha_stride.png")
    write_report(results, frontier, best, runs, OUTPUT_DIR / "tuning_report.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())