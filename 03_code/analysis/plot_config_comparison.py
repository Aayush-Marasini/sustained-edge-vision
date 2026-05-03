"""
plot_config_comparison.py
=========================
Three-panel bar chart: FPS, Power, J/frame for all 4 configurations.
Solves the visualization problem where S1 and S2 look identical in J/frame
but actually differ significantly in Power.
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
OUT  = REPO / "05_results" / "plots"
OUT.mkdir(parents=True, exist_ok=True)

configs = ["S0\nFP32@2400", "S1\nFP32@1800", "S2\nFP32@1500", "INT8\n@2400\n(ablation)"]
fps     = [14.582, 12.432, 11.012, 8.315]
fps_std = [ 0.019,  0.015,  0.016, 0.019]
pwr     = [ 8.149,  5.996,  5.329, 7.872]
pwr_std = [ 0.053,  0.056,  0.017, 0.017]
jpf     = [ 0.559,  0.482,  0.484, 0.947]
jpf_std = [ 0.004,  0.004,  0.002, 0.001]
colors  = ["#1f77b4", "#2ca02c", "#ff7f0e", "#d62728"]

fig, axes = plt.subplots(1, 3, figsize=(11, 4.2))
x = np.arange(len(configs))

# Panel 1: FPS
ax = axes[0]
bars = ax.bar(x, fps, yerr=fps_std, color=colors, capsize=4,
              edgecolor="black", linewidth=0.5)
ax.set_title("Throughput", fontsize=12, fontweight="bold")
ax.set_ylabel("FPS", fontsize=11)
ax.set_xticks(x)
ax.set_xticklabels(configs, fontsize=8.5)
ax.grid(axis="y", alpha=0.3)
ax.set_ylim(0, 17)
for b, v in zip(bars, fps):
    ax.text(b.get_x() + b.get_width()/2, v + 0.4,
            f"{v:.2f}", ha="center", fontsize=9, fontweight="bold")

# Panel 2: Power (THIS is the key panel showing S1 vs S2 difference)
ax = axes[1]
bars = ax.bar(x, pwr, yerr=pwr_std, color=colors, capsize=4,
              edgecolor="black", linewidth=0.5)
ax.set_title("Average Power Draw", fontsize=12, fontweight="bold")
ax.set_ylabel("Power (W)", fontsize=11)
ax.set_xticks(x)
ax.set_xticklabels(configs, fontsize=8.5)
ax.grid(axis="y", alpha=0.3)
ax.set_ylim(0, 10)
for b, v in zip(bars, pwr):
    ax.text(b.get_x() + b.get_width()/2, v + 0.2,
            f"{v:.2f} W", ha="center", fontsize=9, fontweight="bold")

# Annotation showing S1-S2 power gap
ax.annotate("", xy=(1, 5.99), xytext=(2, 5.33),
            arrowprops=dict(arrowstyle="<->", color="darkred", lw=1.5))
ax.text(1.5, 5.6, "−11%\npower\nvs S1", fontsize=8, color="darkred",
        ha="center", fontweight="bold")

# Panel 3: J/frame
ax = axes[2]
bars = ax.bar(x, jpf, yerr=jpf_std, color=colors, capsize=4,
              edgecolor="black", linewidth=0.5)
ax.set_title("Energy per Inference", fontsize=12, fontweight="bold")
ax.set_ylabel("J/frame", fontsize=11)
ax.set_xticks(x)
ax.set_xticklabels(configs, fontsize=8.5)
ax.grid(axis="y", alpha=0.3)
ax.set_ylim(0, 1.1)
for b, v in zip(bars, jpf):
    ax.text(b.get_x() + b.get_width()/2, v + 0.025,
            f"{v:.3f}", ha="center", fontsize=9, fontweight="bold")

# S0 baseline reference line on J/frame panel
ax.axhline(y=jpf[0], color="gray", linestyle=":", linewidth=1, alpha=0.6)
ax.text(3.45, jpf[0] + 0.02, "S0 baseline", fontsize=7,
        color="gray", style="italic", ha="right")

plt.suptitle("Scheduler Configuration Profiling — Pi 5, Passive Cooling, n=3 × 5-min Runs",
             fontsize=12, fontweight="bold", y=1.02)
plt.tight_layout()

out_path = OUT / "config_comparison.png"
plt.savefig(out_path, dpi=300, bbox_inches="tight")
print(f"Saved: {out_path}")