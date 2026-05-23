#!/usr/bin/env python3
"""
merge_power_into_stats.py
Quick fix: merge power_analysis_30min.csv into condition_stats.csv.
The compute_statistics.py expected run_dir as the merge key, but
the power CSV uses condition+rep. This script does the merge correctly.
"""
import csv
from pathlib import Path
import numpy as np

POWER_CSV = Path("05_results/power_analysis_30min.csv")
OUT_CSV   = Path("05_results/condition_stats_with_power.csv")

# Map power CSV condition names to paper condition names
NAME_MAP = {
    "Static-S0": "Static-S0",
    "Static-S1": "Static-S1",
    "Static-S2": "Static-S2",
    "Reactive-Threshold": "Reactive-Threshold",
    "Proactive (Ours)": "Proactive",
}

per_condition = {v: {"power": [], "jpf": [], "fps_pz": []} for v in NAME_MAP.values()}

with open(POWER_CSV, encoding="utf-8") as f:
    for row in csv.DictReader(f):
        cond = NAME_MAP.get(row["condition"].strip())
        if cond is None:
            continue
        per_condition[cond]["power"].append(float(row["mean_power_w"]))
        per_condition[cond]["jpf"].append(float(row["j_per_frame"]))
        per_condition[cond]["fps_pz"].append(float(row["fps_mean"]))

print(f"{'Condition':<22} {'Power_W':>10} {'PowerStd':>10} {'J/frame':>10} {'JpfStd':>10}")
print("-" * 70)
rows = []
for cond, data in per_condition.items():
    if not data["jpf"]:
        continue
    p_mean = np.mean(data["power"])
    p_std  = np.std(data["power"], ddof=1)
    j_mean = np.mean(data["jpf"])
    j_std  = np.std(data["jpf"], ddof=1)
    print(f"{cond:<22} {p_mean:>10.4f} {p_std:>10.4f} {j_mean:>10.4f} {j_std:>10.4f}")
    rows.append({
        "condition": cond,
        "n_reps": len(data["jpf"]),
        "mean_power_w": round(p_mean, 4),
        "std_power_w": round(p_std, 4),
        "j_per_frame_mean": round(j_mean, 4),
        "j_per_frame_std": round(j_std, 4),
    })

# Paired Proactive vs Reactive J/frame
p_jpf = per_condition["Proactive"]["jpf"]
r_jpf = per_condition["Reactive-Threshold"]["jpf"]
diffs = [a - b for a, b in zip(p_jpf, r_jpf)]
mean_d = np.mean(diffs)
std_d  = np.std(diffs, ddof=1)
cohen_d = mean_d / std_d if std_d > 0 else float("nan")
print(f"\nProactive vs Reactive J/frame:")
print(f"  Delta:       {mean_d:.4f} J/frame ({100*mean_d/np.mean(r_jpf):+.1f}%)")
print(f"  Cohen's d:   {cohen_d:.3f}")

with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
    w.writeheader()
    w.writerows(rows)
print(f"\nSaved -> {OUT_CSV}")