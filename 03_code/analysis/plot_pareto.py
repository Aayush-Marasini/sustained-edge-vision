"""
plot_pareto.py
==============
Pareto plot: FPS vs J/frame for all 4 scheduler configurations.
Clean layout, no label overlap, INT8 clearly separated.
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.lines as mlines
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
OUT  = REPO / "05_results" / "plots"
OUT.mkdir(parents=True, exist_ok=True)

configs = [
    {"label": "S0: FP32 @ 2400 MHz\n(baseline)",
     "fps": 14.582, "fps_std": 0.019, "jpf": 0.559, "jpf_std": 0.004,
     "color": "#1f77b4", "marker": "o", "pareto": True},
    {"label": "S1: FP32 @ 1800 MHz\n(scheduler state)",
     "fps": 12.432, "fps_std": 0.015, "jpf": 0.482, "jpf_std": 0.004,
     "color": "#2ca02c", "marker": "o", "pareto": True},
    {"label": "S2: FP32 @ 1500 MHz\n(scheduler state)",
     "fps": 11.012, "fps_std": 0.016, "jpf": 0.484, "jpf_std": 0.002,
     "color": "#ff7f0e", "marker": "o", "pareto": True},
    {"label": "INT8 @ 2400 MHz\n(ablation — dominated)",
     "fps": 8.315,  "fps_std": 0.019, "jpf": 0.947, "jpf_std": 0.001,
     "color": "#d62728", "marker": "X", "pareto": False},
]

fig, ax = plt.subplots(figsize=(9, 6))

# Pareto frontier line (S2 → S1 → S0)
pareto = sorted([c for c in configs if c["pareto"]], key=lambda x: x["fps"])
ax.plot([p["fps"] for p in pareto], [p["jpf"] for p in pareto],
        color="steelblue", linestyle="--", linewidth=1.5, zorder=2,
        label="DVFS Pareto frontier")

# Plot each point
for c in configs:
    ax.errorbar(c["fps"], c["jpf"],
                xerr=c["fps_std"], yerr=c["jpf_std"],
                marker=c["marker"], markersize=14, capsize=5,
                color=c["color"], linestyle="", zorder=5,
                markeredgecolor="white", markeredgewidth=0.8)

# Manual labels — positioned to avoid overlap
label_offsets = {
    "S0": (8, -22),
    "S1": (8,  10),
    "S2": (-105, 10),
    "INT8": (8, 8),
}
for c in configs:
    key = c["label"][:3].strip(":")
    dx, dy = label_offsets.get(key, (8, 8))
    ax.annotate(c["label"],
                xy=(c["fps"], c["jpf"]),
                xytext=(dx, dy),
                textcoords="offset points",
                fontsize=9, color=c["color"],
                fontweight="bold",
                arrowprops=dict(arrowstyle="-", color=c["color"],
                                lw=0.8) if abs(dx) > 20 else None)

# Vertical separator between DVFS region and INT8
ax.axvline(x=9.8, color="gray", linestyle=":", linewidth=1, alpha=0.6)
ax.text(9.7, 0.39, "INT8\nregion", fontsize=8, color="gray",
        ha="right", va="bottom")
ax.text(9.9, 0.39, "DVFS\nregion", fontsize=8, color="steelblue",
        ha="left", va="bottom")

# Axes
ax.set_xlabel("Throughput (FPS)", fontsize=12)
ax.set_ylabel("Energy per inference (J/frame)", fontsize=12)
ax.set_title("Pareto Analysis: DVFS Frequency Scaling vs INT8 Quantization\n"
             "Raspberry Pi 5 · Passive Cooling · FP32 YOLOv8n · n=3 × 5-min runs",
             fontsize=11)
ax.set_xlim(6.5, 16.8)
ax.set_ylim(0.36, 1.05)
ax.grid(True, alpha=0.25)

# Legend
handles = [
    mpatches.Patch(color="#1f77b4", label="S0: FP32 @ 2400 MHz  14.58 FPS  8.15 W  0.559 J/fr"),
    mpatches.Patch(color="#2ca02c", label="S1: FP32 @ 1800 MHz  12.43 FPS  5.99 W  0.482 J/fr  (−26% W, −14% J/fr)"),
    mpatches.Patch(color="#ff7f0e", label="S2: FP32 @ 1500 MHz  11.01 FPS  5.33 W  0.484 J/fr  (−35% W, −13% J/fr)"),
    mpatches.Patch(color="#d62728", label="INT8 @ 2400 MHz        8.31 FPS  7.87 W  0.947 J/fr  (−3.4% W, +69% J/fr)"),
    mlines.Line2D([0],[0], color="steelblue", linestyle="--", label="DVFS Pareto frontier"),
]
ax.legend(handles=handles, loc="upper center",
          bbox_to_anchor=(0.5, -0.13),
          ncol=1, fontsize=8.2,
          framealpha=0.9, edgecolor="gray")

plt.tight_layout()
plt.subplots_adjust(bottom=0.32)

out_path = OUT / "pareto_all_configs.png"
plt.savefig(out_path, dpi=300, bbox_inches="tight")
print(f"Saved: {out_path}")