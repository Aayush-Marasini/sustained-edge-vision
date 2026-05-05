"""
plot_int8_comparison.py
Generates Figure 2: INT8 vs FP32 power and energy comparison bar chart.
Data from CHANGELOG v0.7.10 / v0.7.11 (n=3 x 5-min runs each).
Output: 05_results/plots/int8_vs_fp32_comparison.png
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from pathlib import Path

OUT = Path(__file__).resolve().parents[2] / "05_results" / "plots"
OUT.mkdir(parents=True, exist_ok=True)

# ── Measured data (from CHANGELOG v0.7.10 / v0.7.11, n=3 each) ──────
models = ["FP32\n@ 2400 MHz", "INT8\n@ 2400 MHz"]

power_mean = [8.149, 7.872]
power_err  = [0.053, 0.017]

jpf_mean   = [0.559, 0.947]
jpf_err    = [0.004, 0.001]

fps_mean   = [14.582, 8.315]

x = np.array([0, 1])
width = 0.32

fig, axes = plt.subplots(1, 2, figsize=(9, 4.5))

# ── Left: Mean Power ─────────────────────────────────────────────────
ax = axes[0]
bars = ax.bar(x, power_mean, width=0.5, yerr=power_err, capsize=5,
              color=["#4472C4", "#ED7D31"], edgecolor="black", linewidth=0.7,
              error_kw={"elinewidth": 1.2, "capthick": 1.2})
ax.set_xticks(x)
ax.set_xticklabels(models, fontsize=11)
ax.set_ylabel("Mean Power (W)", fontsize=11)
ax.set_ylim(0, 10)
ax.set_title("Power Draw", fontsize=12, fontweight="bold")
ax.grid(axis="y", alpha=0.3)

# Annotate reduction
ax.annotate("−3.4%\n(within noise)", xy=(1, power_mean[1]),
            xytext=(1.22, power_mean[1] + 0.4),
            fontsize=9, ha="center",
            arrowprops=dict(arrowstyle="->", color="black", lw=0.8))

for bar, val in zip(bars, power_mean):
    ax.text(bar.get_x() + bar.get_width()/2, val + 0.15,
            f"{val:.3f} W", ha="center", va="bottom", fontsize=9)

# ── Right: Energy per Frame ──────────────────────────────────────────
ax = axes[1]
bars = ax.bar(x, jpf_mean, width=0.5, yerr=jpf_err, capsize=5,
              color=["#4472C4", "#ED7D31"], edgecolor="black", linewidth=0.7,
              error_kw={"elinewidth": 1.2, "capthick": 1.2})
ax.set_xticks(x)
ax.set_xticklabels(models, fontsize=11)
ax.set_ylabel("Energy per Frame (J/frame)", fontsize=11)
ax.set_ylim(0, 1.15)
ax.set_title("Energy Efficiency", fontsize=12, fontweight="bold")
ax.grid(axis="y", alpha=0.3)

# Annotate 69.4% increase
ax.annotate("+69.4%\n(INT8 WORSE)", xy=(1, jpf_mean[1]),
            xytext=(1.22, jpf_mean[1] - 0.08),
            fontsize=9, ha="center", color="#C00000", fontweight="bold",
            arrowprops=dict(arrowstyle="->", color="#C00000", lw=1.0))

for bar, val, fps in zip(bars, jpf_mean, fps_mean):
    ax.text(bar.get_x() + bar.get_width()/2, val + 0.02,
            f"{val:.3f} J\n({fps:.1f} FPS)",
            ha="center", va="bottom", fontsize=8.5)

fig.suptitle(
    "INT8 vs FP32: Power and Energy per Frame\n"
    "(n=3 × 5-min runs, passive cooling, ~22.5°C ambient)",
    fontsize=11, fontweight="bold"
)
fig.tight_layout()

outpath = OUT / "int8_vs_fp32_comparison.png"
fig.savefig(outpath, dpi=200, bbox_inches="tight")
plt.close(fig)
print(f"Saved: {outpath}")