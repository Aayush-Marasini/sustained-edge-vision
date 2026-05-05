"""
analyze_thermal_validation.py
=============================
Analyze 30-min thermal validation runs for S0/S1/S2.

Produces:
  - Console summary table (T_start, T_peak, T_plateau, throttle events,
    mean FPS, FPS_std) → fills CHANGELOG v0.8.1 table
  - 05_results/plots/thermal_validation_trajectories.png → paper §V.A Fig

WorkPlan grounding:
  Task 20 (§8.1): configuration profiling — thermal rise rate, FPS per config.
  Task 23 (§8.4): T(t) time-series figure, time-to-throttle plot.

Throttle decoding (Pi 5 / vcgencmd get_throttled bitmask):
  bit 0  (0x00001): throttled_now  — actively throttling RIGHT NOW
  bit 1  (0x00002): arm_freq_cap   — freq cap active (soft limit, not thermal)
  bit 2  (0x00004): undervolt_now
  bit 16 (0x10000): throttled_ever — has throttled since last clear
  bit 17 (0x20000): arm_freq_cap_ever
  bit 18 (0x40000): undervolt_ever
  0xE0000 = bits 17+18+19 set = sticky historical flags, NOT active throttle.
  ALWAYS use throttled_now (bit 0) for active-throttle detection.
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
RESULTS_ROOT = Path(__file__).resolve().parents[2] / "05_results"
RUNS_ROOT    = RESULTS_ROOT / "runs"
PLOTS_DIR    = RESULTS_ROOT / "plots"
PLOTS_DIR.mkdir(parents=True, exist_ok=True)

# Replace the RUN_DIRS block (around line 30) with this:
import glob

def find_runs_for_state(state: str) -> list:
    pattern = str(RUNS_ROOT / f"*thermalval_{state}*")
    dirs = sorted(Path(p) for p in glob.glob(pattern) if Path(p).is_dir())
    return [d for d in dirs if (d / "telemetry_raw.csv").exists()]

RUN_DIRS = {
    state: find_runs_for_state(state)
    for state in ["S0", "S1", "S2"]
}

THROTTLE_TEMP_C  = 80.0   # Pi 5 hardware throttle threshold
PLATEAU_WINDOW_S = 300.0  # last 5 min used to compute T_plateau
COLORS = {"S0": "#d62728", "S1": "#ff7f0e", "S2": "#1f77b4"}
LABELS = {
    "S0": "S0: 2400 MHz (uncapped)",
    "S1": "S1: 1800 MHz cap",
    "S2": "S2: 1500 MHz cap",
}

# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------

def load_telemetry(run_dir: Path) -> pd.DataFrame:
    csv = run_dir / "telemetry_raw.csv"
    df  = pd.read_csv(csv)
    # monotonic_offset_s is our canonical time axis
    df["t_s"]  = df["monotonic_offset_s"]
    df["t_min"] = df["t_s"] / 60.0
    return df


def load_inference(run_dir: Path) -> pd.DataFrame:
    csv = run_dir / "inference_log.csv"
    df  = pd.read_csv(csv)
    return df


def load_metadata(run_dir: Path) -> dict:
    return json.loads((run_dir / "run_metadata.json").read_text(encoding="utf-8"))

# ---------------------------------------------------------------------------
# Per-run metrics
# ---------------------------------------------------------------------------

def compute_fps_from_inference(df_inf: pd.DataFrame) -> tuple[float, float]:
    """Compute mean and std FPS from per-frame latency_ms column."""
    latencies_ms = df_inf["latency_ms"].dropna()
    fps_per_frame = 1000.0 / latencies_ms
    return float(fps_per_frame.mean()), float(fps_per_frame.std())


def find_throttle_events(df_tel: pd.DataFrame) -> pd.DataFrame:
    """Return rows where throttled_now == 1 (bit 0 active)."""
    return df_tel[df_tel["throttled_now"] == 1]


def time_to_first_throttle_s(df_tel: pd.DataFrame) -> float | None:
    """Return time (s) of first active throttle sample, or None."""
    throttled = find_throttle_events(df_tel)
    if throttled.empty:
        return None
    return float(throttled["t_s"].iloc[0])


def plateau_temp_c(df_tel: pd.DataFrame, window_s: float = PLATEAU_WINDOW_S) -> float:
    """Mean temperature in the last `window_s` seconds of the run."""
    t_max = df_tel["t_s"].max()
    window = df_tel[df_tel["t_s"] >= (t_max - window_s)]
    return float(window["temp_soc_c"].mean())


def temp_rise_rate(df_tel: pd.DataFrame, fit_window_s: float = 300.0) -> float:
    """Linear dT/dt (°C/min) over first `fit_window_s` seconds."""
    early = df_tel[df_tel["t_s"] <= fit_window_s]
    if len(early) < 10:
        return float("nan")
    coeffs = np.polyfit(early["t_min"], early["temp_soc_c"], 1)
    return float(coeffs[0])  # °C/min

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def summarize(state: str, run_dir: Path) -> dict:
    df_tel = load_telemetry(run_dir)
    df_inf = load_inference(run_dir)

    fps_mean, fps_std = compute_fps_from_inference(df_inf)
    t_peak            = float(df_tel["temp_soc_c"].max())
    t_start           = float(df_tel["temp_soc_c"].iloc[:4].mean())  # first 2 s
    t_plat            = plateau_temp_c(df_tel)
    ttt               = time_to_first_throttle_s(df_tel)
    n_throttle        = len(find_throttle_events(df_tel))
    rise_rate         = temp_rise_rate(df_tel)

    return {
        "state":           state,
        "T_start_c":       round(t_start, 1),
        "T_peak_c":        round(t_peak, 1),
        "T_plateau_c":     round(t_plat, 1),
        "throttled":       ttt is not None,
        "time_to_throttle_s": ttt,
        "n_throttle_samples": n_throttle,
        "rise_rate_c_per_min": round(rise_rate, 3),
        "fps_mean":        round(fps_mean, 3),
        "fps_std":         round(fps_std, 3),
    }

# ---------------------------------------------------------------------------
# Figure
# ---------------------------------------------------------------------------

def plot_trajectories(data: dict[str, tuple]) -> Path:
    """
    data: {state_name: (df_telemetry, summary_dict)}
    Produces §V.A T(t) figure.
    """
    fig, axes = plt.subplots(2, 1, figsize=(9, 7), sharex=True)
    ax_T, ax_fps = axes

    for state, (df_tel, df_inf, summ) in data.items():
        col   = COLORS[state]
        label = LABELS[state]

        # Temperature trajectory
        ax_T.plot(df_tel["t_min"], df_tel["temp_soc_c"],
                  color=col, linewidth=1.2, label=label, alpha=0.9)

        # FPS: compute rolling 60-frame window from per-frame latencies
        df_inf = df_inf.copy()
        df_inf["fps"] = 1000.0 / df_inf["latency_ms"]
        # Bin into 30-s windows aligned to telemetry
        t_max_min = df_tel["t_min"].max()
        bins = np.arange(0, t_max_min + 0.5, 0.5)  # 30-s bins
        df_inf["t_min"] = df_inf["monotonic_time_s"] / 60.0
        df_inf["bin"]   = pd.cut(df_inf["t_min"], bins=bins,
                                  labels=bins[:-1] + 0.25)
        fps_binned = df_inf.groupby("bin", observed=True)["fps"].mean()
        ax_fps.plot(fps_binned.index.astype(float), fps_binned.values,
                    color=col, linewidth=1.2, label=label, alpha=0.9)

    # Throttle threshold
    ax_T.axhline(THROTTLE_TEMP_C, color="black", linestyle="--",
                 linewidth=1.0, label="Throttle threshold (80°C)")

    ax_T.set_ylabel("SoC Temperature (°C)", fontsize=11)
    ax_T.set_ylim(40, 90)
    ax_T.yaxis.set_minor_locator(ticker.MultipleLocator(5))
    ax_T.legend(fontsize=9, loc="lower right")
    ax_T.grid(True, which="major", alpha=0.3)
    ax_T.set_title("30-min Thermal Validation: Temperature & FPS per DVFS State\n"
                   "(FP32, passive cooling, 23.0°C ambient)", fontsize=11)

    ax_fps.set_ylabel("FPS (30-s rolling mean)", fontsize=11)
    ax_fps.set_xlabel("Time (minutes)", fontsize=11)
    ax_fps.set_xlim(0, 30)
    ax_fps.legend(fontsize=9, loc="upper right")
    ax_fps.grid(True, which="major", alpha=0.3)

    fig.tight_layout()
    out = PLOTS_DIR / "thermal_validation_trajectories.png"
    fig.savefig(out, dpi=200, bbox_inches="tight")
    plt.close(fig)
    return out

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print("Loading runs...")
    all_summaries = {"S0": [], "S1": [], "S2": []}
    plot_data = {}

    for state, run_dirs in RUN_DIRS.items():
        if not run_dirs:
            print(f"  {state}: NO RUNS FOUND")
            continue
        print(f"  {state}: {len(run_dirs)} rep(s)")
        for run_dir in run_dirs:
            print(f"    {run_dir.name}")
            summ = summarize(state, run_dir)
            all_summaries[state].append(summ)
        # For plotting, use first rep (most representative single trace)
        plot_data[state] = (
            load_telemetry(run_dirs[0]),
            load_inference(run_dirs[0]),
            all_summaries[state][0],
        )

    print("\n" + "=" * 85)
    print("TASK 20 CONFIGURATION PROFILING — MULTI-REP SUMMARY")
    print("=" * 85)
    hdr = (f"{'State':<6} {'N':>3} {'T_start':>8} {'T_peak':>8} {'T_plateau':>10} "
           f"{'Throttled':>10} {'N_thr_mean':>11} {'Rise°C/min':>11} "
           f"{'FPS_mean':>9} {'FPS_std':>8} {'FPS_CV':>7}")
    print(hdr)
    print("-" * 85)
    for state in ["S0", "S1", "S2"]:
        reps = all_summaries[state]
        if not reps:
            continue
        n = len(reps)
        fps_means   = [r["fps_mean"] for r in reps]
        fps_stds    = [r["fps_std"]  for r in reps]
        t_plateaus  = [r["T_plateau_c"] for r in reps]
        t_peaks     = [r["T_peak_c"]    for r in reps]
        n_thrs      = [r["n_throttle_samples"] for r in reps]
        rises       = [r["rise_rate_c_per_min"] for r in reps]
        throttled   = any(r["throttled"] for r in reps)
        fps_cv = float(np.mean(fps_stds)) / float(np.mean(fps_means)) * 100

        print(
            f"{state:<6} {n:>3} "
            f"{reps[0]['T_start_c']:>8.1f} "
            f"{float(np.mean(t_peaks)):>8.1f}±{float(np.std(t_peaks)):.1f} "
            f"{float(np.mean(t_plateaus)):>8.1f}±{float(np.std(t_plateaus)):.1f}  "
            f"{'Yes' if throttled else 'No':>10} "
            f"{float(np.mean(n_thrs)):>11.0f} "
            f"{float(np.mean(rises)):>11.3f} "
            f"{float(np.mean(fps_means)):>9.3f} "
            f"{float(np.mean(fps_stds)):>8.3f} "
            f"{fps_cv:>6.1f}%"
        )
    print("=" * 85)

    # Figure (single-rep traces)
    if plot_data:
        out = plot_trajectories(plot_data)
        print(f"\nFigure saved → {out}")

if __name__ == "__main__":
    main()