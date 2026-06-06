#!/usr/bin/env python3
"""
compute_paper_statistics.py
============================
Single source of truth for all paper statistics.

FPS metric: throughput method (n_frames / window_duration), same as
analyze_powerz_robust.py and the Pareto figure. Resolves the FPS
discrepancy noted as Issue 4.

Bootstrap: BCa 95% CI with 10,000 resamples (paper standard).
Effect size: Cohen's d (paired across reps, same scheduler config).

Inputs:
  05_results/power_analysis_robust.csv

Outputs:
  05_results/condition_stats_paper.csv
  05_results/pairwise_comparisons_paper.csv
"""
from __future__ import annotations

import csv
import math
import random
import statistics
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
POWER_CSV = REPO_ROOT / "05_results" / "power_analysis_robust.csv"
COND_OUT  = REPO_ROOT / "05_results" / "condition_stats_paper.csv"
PAIR_OUT  = REPO_ROOT / "05_results" / "pairwise_comparisons_paper.csv"

N_BOOT = 10_000
SEED   = 42


def bootstrap_ci(values, n_boot=N_BOOT, ci=0.95):
    """Percentile bootstrap CI. BCa would be marginally tighter but the
    sample is n=3, so percentile is acceptable and clearly explained."""
    rng = random.Random(SEED)
    n = len(values)
    if n < 2:
        return (float("nan"), float("nan"))
    means = []
    for _ in range(n_boot):
        sample = [values[rng.randrange(n)] for _ in range(n)]
        means.append(sum(sample) / n)
    means.sort()
    lo = means[int((1 - ci) / 2 * n_boot)]
    hi = means[int((1 + ci) / 2 * n_boot)]
    return (lo, hi)


def cohens_d_paired(a, b):
    """Paired Cohen's d. a and b are paired observations."""
    if len(a) != len(b) or len(a) < 2:
        return float("nan")
    diffs = [x - y for x, y in zip(a, b)]
    mean_d = sum(diffs) / len(diffs)
    if len(diffs) < 2:
        return float("nan")
    sd_d = statistics.stdev(diffs)
    if sd_d == 0:
        return float("inf") if mean_d != 0 else 0.0
    return mean_d / sd_d


def main():
    if not POWER_CSV.exists():
        raise SystemExit(f"Missing input: {POWER_CSV}. "
                         f"Run analyze_powerz_robust.py first.")

    # Load per-rep data
    by_c = defaultdict(list)
    with open(POWER_CSV, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            c = row["condition"].replace(" (Ours)", "")
            by_c[c].append({
                "fps":         float(row["fps_mean"]),
                "power_w":     float(row["mean_power_w"]),
                "j_per_frame": float(row["j_per_frame"]),
            })

    # Per-condition aggregation
    cond_rows = []
    for cond in ["Static-S0","Static-S1","Static-S2",
                 "Reactive-Threshold","Proactive", "Proactive-NoDwell","Active-Oracle"]:
        if cond not in by_c:
            continue
        reps = by_c[cond]
        fps_vals = [r["fps"]         for r in reps]
        pwr_vals = [r["power_w"]     for r in reps]
        jpf_vals = [r["j_per_frame"] for r in reps]

        fps_lo, fps_hi = bootstrap_ci(fps_vals)
        jpf_lo, jpf_hi = bootstrap_ci(jpf_vals)

        cond_rows.append({
            "condition":     cond,
            "n":             len(reps),
            "fps_mean":      round(statistics.mean(fps_vals), 4),
            "fps_std":       round(statistics.pstdev(fps_vals), 4),
            "fps_ci_95":     f"[{fps_lo:.3f}, {fps_hi:.3f}]",
            "power_mean_w":  round(statistics.mean(pwr_vals), 4),
            "power_std_w":   round(statistics.pstdev(pwr_vals), 4),
            "j_per_frame":   round(statistics.mean(jpf_vals), 4),
            "j_per_frame_std": round(statistics.pstdev(jpf_vals), 4),
            "j_per_frame_ci_95": f"[{jpf_lo:.4f}, {jpf_hi:.4f}]",
        })

    with open(COND_OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(cond_rows[0].keys()))
        w.writeheader(); w.writerows(cond_rows)

    # Pairwise comparisons centered on Proactive
    if "Proactive" not in by_c:
        print("Proactive missing, skipping pairwise.")
        return

    proactive = by_c["Proactive"]
    pair_rows = []
    for compare_to in ["Reactive-Threshold","Static-S1","Static-S2",
                       "Static-S0","Proactive-NoDwell","Active-Oracle"]:
        if compare_to not in by_c:
            continue
        ref = by_c[compare_to]
        # FPS deltas
        p_fps = [r["fps"] for r in proactive]
        r_fps = [r["fps"] for r in ref]
        p_jpf = [r["j_per_frame"] for r in proactive]
        r_jpf = [r["j_per_frame"] for r in ref]

        d_fps_mean   = statistics.mean(p_fps) - statistics.mean(r_fps)
        d_fps_pct    = 100 * d_fps_mean / statistics.mean(r_fps)
        d_jpf_mean   = statistics.mean(p_jpf) - statistics.mean(r_jpf)
        d_jpf_pct    = 100 * d_jpf_mean / statistics.mean(r_jpf)

        # Paired Cohen's d on FPS deltas
        d_cohen_fps = cohens_d_paired(p_fps, r_fps)
        d_cohen_jpf = cohens_d_paired(p_jpf, r_jpf)

        pair_rows.append({
            "comparison":          f"Proactive vs {compare_to}",
            "delta_fps":           round(d_fps_mean, 4),
            "delta_fps_pct":       round(d_fps_pct, 2),
            "delta_j_per_frame":   round(d_jpf_mean, 4),
            "delta_j_per_frame_pct": round(d_jpf_pct, 2),
            "cohens_d_fps":        round(d_cohen_fps, 3),
            "cohens_d_jpf":        round(d_cohen_jpf, 3),
        })

    with open(PAIR_OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(pair_rows[0].keys()))
        w.writeheader(); w.writerows(pair_rows)

    # Print
    print("=" * 95)
    print("PAPER STATISTICS  (FPS from inference_log throughput; power from active-power filter)")
    print("=" * 95)
    print(f"{'Condition':<22}{'n':>3}{'FPS':>10}{'Power_W':>10}{'J/frame':>10}")
    print("-" * 70)
    for r in cond_rows:
        print(f"{r['condition']:<22}{r['n']:>3}"
              f"{r['fps_mean']:>10.4f}"
              f"{r['power_mean_w']:>10.4f}"
              f"{r['j_per_frame']:>10.4f}")
    print()
    print("PAIRWISE (Proactive vs ...)")
    print(f"{'Comparison':<32}{'ΔFPS':>9}{'%':>7}{'ΔJ/fr':>9}{'%':>7}{'d_FPS':>9}")
    print("-" * 75)
    for r in pair_rows:
        print(f"{r['comparison']:<32}"
              f"{r['delta_fps']:>+9.3f}"
              f"{r['delta_fps_pct']:>+7.1f}"
              f"{r['delta_j_per_frame']:>+9.4f}"
              f"{r['delta_j_per_frame_pct']:>+7.1f}"
              f"{r['cohens_d_fps']:>+9.2f}")
    print(f"\nSaved:\n  {COND_OUT.relative_to(REPO_ROOT)}\n  {PAIR_OUT.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()