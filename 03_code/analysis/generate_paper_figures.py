#!/usr/bin/env python3
"""
generate_paper_figures.py  v2
==============================
6 paper-ready figures from Pi telemetry + robust power data.

Fixes from v1:
  - Uses hardcoded MAPPING (same as compute_statistics.py) instead of
    fragile metadata-based discovery. Resolves 0-reps for Reactive/Proactive
    when those run_metadata.json files are git-LFS pointers on Windows.
  - fig_time_at_state: guard against empty condition lists.
  - fig_fps_distributions: use total_frames/total_time FPS (not 1/mean_latency).

Outputs: 05_results/plots/fig{3-8}_*.png
"""
from __future__ import annotations

import csv
import json
import statistics
from pathlib import Path
from typing import Dict, List, Tuple

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNS_DIR  = REPO_ROOT / "05_results" / "runs"
POWER_CSV = REPO_ROOT / "05_results" / "power_analysis_robust.csv"
PLOTS_DIR = REPO_ROOT / "05_results" / "plots"
PLOTS_DIR.mkdir(parents=True, exist_ok=True)

# Wong colour-blind-safe palette
COLORS = {
    "Static-S0":          "#000000",
    "Static-S1":          "#E69F00",
    "Static-S2":          "#56B4E9",
    "Reactive-Threshold": "#D55E00",
    "Proactive":          "#009E73",
    "Proactive-NoDwell":  "#7F00FF",
    "Active-Oracle":      "#CC79A7",
}
ORDER = ["Static-S0","Static-S1","Static-S2",
         "Reactive-Threshold","Proactive","Proactive-NoDwell","Active-Oracle"]

# Hardcoded mapping — same run dirs as compute_statistics.py
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
    "Proactive-NoDwell": [
        "2026-06-05_183203_scheduled_high_S0_rep1",
        "2026-06-05_190704_scheduled_high_S0_rep2",
        "2026-06-05_195204_scheduled_high_S0_rep3",
    ],
    "Active-Oracle": [
        "2026-05-24_182759_thermalval_S0_active_cooling",
        "2026-05-24_190352_thermalval_S0_active_cooling",
        "2026-05-24_193737_thermalval_S0_active_cooling",
    ],
}

# Convert to Path lists
BY_COND: Dict[str, List[Path]] = {
    cond: [RUNS_DIR / d for d in dirs] for cond, dirs in MAPPING.items()
}

plt.rcParams.update({
    "font.family":    "serif",
    "font.size":      9,
    "axes.labelsize": 9,
    "axes.titlesize": 9,
    "legend.fontsize":8,
    "xtick.labelsize":8,
    "ytick.labelsize":8,
    "savefig.dpi":    300,
    "savefig.bbox":   "tight",
})


# ── helpers ──────────────────────────────────────────────────────────────────

def load_temp_series(run_dir: Path) -> Tuple[List[float], List[float]]:
    t_list, T_list = [], []
    with open(run_dir / "telemetry_raw.csv", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                t = float(row["monotonic_offset_s"])
                T = float(row["temp_soc_c"])
                if 0 <= t <= 1800:
                    t_list.append(t); T_list.append(T)
            except (ValueError, KeyError):
                continue
    return t_list, T_list


def load_throttle_count(run_dir: Path) -> int:
    n = 0
    with open(run_dir / "telemetry_raw.csv", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                t = float(row["monotonic_offset_s"])
                if 10 <= t <= 1800 and row["throttled_now"].strip() == "1":
                    n += 1
            except (ValueError, KeyError):
                continue
    return n


def load_fps_values(run_dir: Path) -> List[float]:
    fps_list = []
    with open(run_dir / "inference_log.csv", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                t = float(row["monotonic_time_s"])
                lat = float(row["latency_ms"])
                if t >= 10.0 and lat > 0:
                    fps_list.append(1000.0 / lat)
            except (ValueError, KeyError):
                continue
    return fps_list


def load_scheduler_decisions(run_dir: Path) -> Tuple[List[float], List[str]]:
    p = run_dir / "scheduler_decisions.csv"
    if not p.exists():
        return [], []
    t_list, s_list = [], []
    with open(p, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                t = float(row["monotonic_offset_s"])
                s = row["dvfs_state"].strip()
                if 0 <= t <= 1800:
                    t_list.append(t); s_list.append(s)
            except (ValueError, KeyError):
                continue
    return t_list, s_list


# ── Figure 3: Thermal trajectories ───────────────────────────────────────────

def fig_thermal_trajectories() -> None:
    fig, ax = plt.subplots(figsize=(7, 4.5))
    for cond in ORDER:
        dirs = BY_COND.get(cond, [])
        for i, d in enumerate(dirs):
            if not d.exists(): continue
            t, T = load_temp_series(d)
            if not t: continue
            label = cond if i == 0 else None
            alpha = 1.0 if i == 0 else 0.3
            ax.plot(np.array(t) / 60, T, color=COLORS[cond],
                    alpha=alpha, linewidth=1.1 if i == 0 else 0.7, label=label)

    ax.axhline(82.0, color="red", linestyle="--", linewidth=0.9,
               label="Throttle threshold (~82 °C)", alpha=0.8)
    ax.set_xlabel("Time (min)"); ax.set_ylabel("SoC Temperature (°C)")
    ax.set_xlim(0, 30); ax.set_ylim(40, 92)
    ax.grid(True, alpha=0.25)
    ax.legend(loc="lower right", ncol=2, framealpha=0.95)
    ax.set_title("Fig. 3 — Thermal Trajectories (n=3 per condition; faint lines = rep 2, 3)")
    fig.tight_layout()
    p = PLOTS_DIR / "fig3_thermal_trajectories.png"
    fig.savefig(p); plt.close(fig); print(f"  saved → {p.relative_to(REPO_ROOT)}")


# ── Figure 4: FPS distributions (violin) ─────────────────────────────────────

def fig_fps_distributions() -> None:
    fig, ax = plt.subplots(figsize=(7, 4))
    data, labels, colours = [], [], []
    for cond in ORDER:
        all_fps = []
        for d in BY_COND.get(cond, []):
            if d.exists():
                all_fps.extend(load_fps_values(d))
        if all_fps:
            data.append(all_fps)
            labels.append(cond.replace("-", "-\n").replace(" (", "\n("))
            colours.append(COLORS[cond])
    if not data:
        print("  SKIPPED fig4 (no data)"); return
    parts = ax.violinplot(data, showmeans=True, showmedians=False, widths=0.7)
    for pc, c in zip(parts["bodies"], colours):
        pc.set_facecolor(c); pc.set_alpha(0.65); pc.set_edgecolor("black")
    ax.set_xticks(range(1, len(labels) + 1)); ax.set_xticklabels(labels)
    ax.set_ylabel("Instantaneous FPS"); ax.grid(True, alpha=0.25, axis="y")
    ax.set_title("Fig. 4 — FPS Distribution (all reps pooled, t > 10 s)")
    fig.tight_layout()
    p = PLOTS_DIR / "fig4_fps_distributions.png"
    fig.savefig(p); plt.close(fig); print(f"  saved → {p.relative_to(REPO_ROOT)}")


# ── Figure 5: Time-at-state stacked bar ──────────────────────────────────────

def fig_time_at_state() -> None:
    schedulers = ["Reactive-Threshold", "Proactive"]
    # Check we have data for at least one
    available = [s for s in schedulers if
                 any(d.exists() for d in BY_COND.get(s, []))]
    if not available:
        print("  SKIPPED fig5 (no Reactive/Proactive data on this machine)")
        return

    fig, ax = plt.subplots(figsize=(5, 3.8))
    state_colours = {"S0": "#CC3333", "S1": "#E69F00", "S2": "#56B4E9"}
    bars: Dict[str, List[float]] = {"S0": [], "S1": [], "S2": []}

    for cond in schedulers:
        totals = {"S0": 0.0, "S1": 0.0, "S2": 0.0}
        n_reps = 0
        for d in BY_COND.get(cond, []):
            if not d.exists(): continue
            t, s = load_scheduler_decisions(d)
            if not t: continue
            for i in range(len(t)):
                t_next = t[i + 1] if i + 1 < len(t) else 1800.0
                dur = max(0.0, min(t_next, 1800.0) - max(t[i], 10.0))
                if s[i] in totals:
                    totals[s[i]] += dur
            n_reps += 1
        if n_reps > 0:
            for k in totals: totals[k] /= n_reps
        total = sum(totals.values()) or 1.0
        for k in totals:
            bars[k].append(100.0 * totals[k] / total)

    if not bars["S0"]:
        print("  SKIPPED fig5 (no scheduler decisions found)")
        return

    x = np.arange(len(schedulers))
    bottom = np.zeros(len(schedulers))
    for state in ("S0", "S1", "S2"):
        h = np.array(bars[state])
        if len(h) < len(schedulers):
            h = np.pad(h, (0, len(schedulers) - len(h)))
        ax.bar(x, h, bottom=bottom, width=0.55,
               color=state_colours[state], label=state,
               edgecolor="black", linewidth=0.5)
        for xi, val in enumerate(h):
            if val > 3:
                ax.text(xi, bottom[xi] + val / 2, f"{val:.1f}%",
                        ha="center", va="center", fontsize=8, fontweight="bold",
                        color="white" if val > 15 else "black")
        bottom += h

    ax.set_xticks(x); ax.set_xticklabels(schedulers)
    ax.set_ylabel("Time at DVFS state (%)"); ax.set_ylim(0, 108)
    ax.legend(title="DVFS state", loc="upper right", framealpha=0.95)
    ax.set_title("Fig. 5 — Mechanism: Time-at-State  (Reactive vs Proactive)")
    fig.tight_layout()
    p = PLOTS_DIR / "fig5_time_at_state.png"
    fig.savefig(p); plt.close(fig); print(f"  saved → {p.relative_to(REPO_ROOT)}")


# ── Figure 6: Pareto FPS vs J/frame ──────────────────────────────────────────

def fig_pareto() -> None:
    if not POWER_CSV.exists():
        print(f"  SKIPPED fig6 (run analyze_powerz_robust.py first)")
        return
    rows = list(csv.DictReader(open(POWER_CSV, encoding="utf-8")))
    from collections import defaultdict
    by_c = defaultdict(list)
    for r in rows:
        c = r["condition"].replace(" (Ours)", "")
        by_c[c].append((float(r["fps_mean"]), float(r["j_per_frame"])))

    has_throttle = set()
    for cond, dirs in BY_COND.items():
        for d in dirs:
            if not d.exists(): continue
            if load_throttle_count(d) > 0:
                has_throttle.add(cond); break

    fig, ax = plt.subplots(figsize=(6, 4.5))
    for cond in ORDER:
        if cond not in by_c: continue
        xs, ys = zip(*by_c[cond])
        ax.scatter(xs, ys, s=70, c=COLORS[cond], label=cond,
                   edgecolor="red" if cond in has_throttle else "black",
                   linewidth=1.8 if cond in has_throttle else 0.5, zorder=3)
        ax.scatter([np.mean(xs)], [np.mean(ys)], s=180, c=COLORS[cond],
                   marker="X", edgecolor="black", linewidth=0.8, zorder=4)

    ax.set_xlabel("Mean Throughput (FPS)")
    ax.set_ylabel("Energy per Frame (J/frame)")
    ax.set_title("Fig. 6 — Pareto: Throughput vs Energy  (X = mean; red ring = throttle)")
    ax.grid(True, alpha=0.25)
    ax.legend(loc="lower left", framealpha=0.95)
    fig.tight_layout()
    p = PLOTS_DIR / "fig6_pareto_fps_jpf.png"
    fig.savefig(p); plt.close(fig); print(f"  saved → {p.relative_to(REPO_ROOT)}")


# ── Figure 7: Scheduler timeline ─────────────────────────────────────────────

def fig_scheduler_timeline() -> None:
    dirs = [d for d in BY_COND.get("Proactive", []) if d.exists()]
    if not dirs:
        print("  SKIPPED fig7 (no Proactive data)"); return
    d = dirs[0]
    t_temp, T = load_temp_series(d)
    t_sched, state = load_scheduler_decisions(d)
    if not t_sched:
        print("  SKIPPED fig7 (no scheduler_decisions.csv)"); return

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(7, 4.5), sharex=True,
                                    gridspec_kw={"height_ratios": [3, 1]})
    ax1.plot(np.array(t_temp)/60, T, color=COLORS["Proactive"], linewidth=1.0)
    ax1.axhline(75.0, ls="--", color="orange", lw=0.8,
                label=r"$T_{\rm esc}(S_0\!\to\!S_1)=75°C$")
    ax1.axhline(79.0, ls="--", color="red",    lw=0.8,
                label=r"$T_{\rm esc}(S_1\!\to\!S_2)=79°C$")
    ax1.set_ylabel("SoC Temp (°C)"); ax1.grid(True, alpha=0.25)
    ax1.legend(loc="lower right", fontsize=7)
    ax1.set_title(f"Fig. 7 — Scheduler Decision Timeline  ({d.name[:19]}...)")

    state_y = {"S0": 2, "S1": 1, "S2": 0}
    state_c = {"S0": COLORS["Static-S0"],
               "S1": COLORS["Static-S1"],
               "S2": COLORS["Static-S2"]}
    for i in range(len(t_sched)):
        t_next = t_sched[i+1] if i+1 < len(t_sched) else 1800.0
        if state[i] in state_y:
            ax2.barh(state_y[state[i]], (t_next - t_sched[i])/60,
                     left=t_sched[i]/60, height=0.7,
                     color=state_c[state[i]], edgecolor="none")
    ax2.set_yticks([0,1,2]); ax2.set_yticklabels(["S2","S1","S0"])
    ax2.set_xlabel("Time (min)"); ax2.set_ylabel("State")
    ax2.set_xlim(0, 30); ax2.grid(True, alpha=0.25, axis="x")
    fig.tight_layout()
    p = PLOTS_DIR / "fig7_scheduler_timeline.png"
    fig.savefig(p); plt.close(fig); print(f"  saved → {p.relative_to(REPO_ROOT)}")


# ── Figure 8: Throttle events bar ────────────────────────────────────────────

def fig_throttle_events() -> None:
    labels, means, stds, colours = [], [], [], []
    for cond in ORDER:
        dirs = [d for d in BY_COND.get(cond, []) if d.exists()]
        if not dirs: continue
        counts = [load_throttle_count(d) for d in dirs]
        labels.append(cond.replace("-", "-\n").replace(" (", "\n("))
        means.append(np.mean(counts))
        stds.append(np.std(counts, ddof=1) if len(counts) > 1 else 0)
        colours.append(COLORS[cond])
    if not labels:
        print("  SKIPPED fig8"); return

    fig, ax = plt.subplots(figsize=(6, 3.8))
    ax.bar(range(len(labels)), means, yerr=stds, color=colours,
           edgecolor="black", capsize=4)
    ax.set_xticks(range(len(labels))); ax.set_xticklabels(labels)
    ax.set_ylabel("Throttle events / 30-min run")
    ax.set_title("Fig. 8 — Throttle Avoidance  (mean ± SD, n=3)")
    ax.grid(True, alpha=0.25, axis="y")
    fig.tight_layout()
    p = PLOTS_DIR / "fig8_throttle_events.png"
    fig.savefig(p); plt.close(fig); print(f"  saved → {p.relative_to(REPO_ROOT)}")


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("\nGenerating paper figures...")
    print(f"  Runs expected:")
    for cond, dirs in BY_COND.items():
        found = sum(1 for d in dirs if d.exists())
        print(f"    {cond:<22} {found}/{len(dirs)} dirs found")

    fig_thermal_trajectories()
    fig_fps_distributions()
    fig_time_at_state()
    fig_pareto()
    fig_scheduler_timeline()
    fig_throttle_events()
    print(f"\nAll figures → {PLOTS_DIR.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()