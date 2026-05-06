# 03_code/analysis/plot_pareto.py
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from pathlib import Path

OUT = Path(__file__).resolve().parents[2] / "05_results" / "plots"
OUT.mkdir(parents=True, exist_ok=True)

conditions = {
    "Static-S0\n(uncontrolled)": {"fps": 13.024, "j": 0.633, "cv": 11.9,
                                   "marker": "X", "color": "#C00000", "size": 120},
    "Static-S1":                 {"fps": 12.804, "j": 0.471, "cv":  3.4,
                                   "marker": "s", "color": "#FF8C00", "size": 100},
    "Static-S2":                 {"fps": 11.326, "j": 0.475, "cv":  3.1,
                                   "marker": "s", "color": "#FFC000", "size": 100},
    "Reactive-\nThreshold":      {"fps": 11.674, "j": 0.596, "cv": 12.2,
                                   "marker": "^", "color": "#7030A0", "size": 110},
    "Proactive\n(Ours)":         {"fps": 12.464, "j": 0.566, "cv": 10.2,
                                   "marker": "*", "color": "#1F77B4", "size": 250},
}

fig, ax = plt.subplots(figsize=(7, 5))

for name, d in conditions.items():
    ax.scatter(d["j"], d["fps"],
               marker=d["marker"], color=d["color"],
               s=d["size"], zorder=5,
               edgecolors="black", linewidths=0.6)
    offset = {"Static-S0\n(uncontrolled)": (0.005, -0.12),
              "Static-S1":                 (0.004,  0.05),
              "Static-S2":                 (0.004, -0.12),
              "Reactive-\nThreshold":      (0.004,  0.05),
              "Proactive\n(Ours)":         (-0.055, 0.05)}.get(name, (0.005, 0.05))
    ax.annotate(name,
                xy=(d["j"], d["fps"]),
                xytext=(d["j"] + offset[0], d["fps"] + offset[1]),
                fontsize=8.5, ha="left",
                color=d["color"])

# Dominance region annotation
ax.annotate("", xy=(0.44, 13.2), xytext=(0.65, 11.2),
            arrowprops=dict(arrowstyle="->", color="gray",
                            lw=1.2, linestyle="dashed"))
ax.text(0.535, 12.15, "better", fontsize=8, color="gray",
        rotation=-45, ha="center")

ax.set_xlabel("Energy per frame (J/frame)\n← lower is better",
              fontsize=11)
ax.set_ylabel("Mean FPS  → higher is better", fontsize=11)
ax.set_title("Scheduler Operating Points:\nThroughput vs Energy Efficiency",
             fontsize=11, fontweight="bold")
ax.grid(True, alpha=0.3)
ax.set_xlim(0.42, 0.70)
ax.set_ylim(10.8, 13.6)

# Zero throttle annotation
for name, d in conditions.items():
    if "S0" in name and "Static" in name:
        ax.annotate("✗ throttles", xy=(d["j"], d["fps"]),
                    xytext=(d["j"] + 0.005, d["fps"] - 0.35),
                    fontsize=7.5, color="#C00000")
    elif name not in ["Static-S0\n(uncontrolled)"]:
        ax.annotate("✓ no throttle", xy=(d["j"], d["fps"]),
                    xytext=(d["j"] + 0.005, d["fps"] - 0.35),
                    fontsize=7, color="#375623", alpha=0.7)

fig.tight_layout()
outpath = OUT / "pareto_frontier.png"
fig.savefig(outpath, dpi=200, bbox_inches="tight")
plt.close(fig)
print(f"Saved: {outpath}")