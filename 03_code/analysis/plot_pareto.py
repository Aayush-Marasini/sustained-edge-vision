"""
plot_pareto.py
==============
Generate Pareto plot: FPS vs J/frame for FP32 and INT8 baselines.
Annotates each point and marks the Pareto frontier.

Output: 05_results/plots/pareto_fp32_int8.png (300 DPI, paper-ready)
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
OUT  = REPO / "05_results" / "plots"
OUT.mkdir(parents=True, exist_ok=True)

# Data from analyze_powerz_energy.py (n=3 each, 5-min runs, passive cooling)
points = [
    {"label": "FP32 @ 2400 MHz", "fps": 14.582, "fps_std": 0.019,
     "jpf": 0.559, "jpf_std": 0.004, "color": "#1f77b4"},
    {"label": "INT8 @ 2400 MHz", "fps":  8.315, "fps_std": 0.019,
     "jpf": 0.947, "jpf_std": 0.001, "color": "#d62728"},
]

fig, ax = plt.subplots(figsize=(7, 5))

for p in points:
    ax.errorbar(p["fps"], p["jpf"],
                xerr=p["fps_std"], yerr=p["jpf_std"],
                marker="o", markersize=10, capsize=4,
                color=p["color"], label=p["label"], linestyle="")
    ax.annotate(p["label"],
                xy=(p["fps"], p["jpf"]),
                xytext=(8, -8), textcoords="offset points",
                fontsize=9)

ax.set_xlabel("Throughput (FPS)", fontsize=12)
ax.set_ylabel("Energy per inference (J/frame)", fontsize=12)
ax.set_title("FPS vs Energy: FP32 vs INT8 baselines\n"
             "(Pi 5, passive cooling, thermal_benchmark_30fps.mp4)",
             fontsize=11)
ax.grid(True, alpha=0.3)
ax.set_xlim(7, 16)
ax.set_ylim(0.4, 1.1)

# Annotate the finding
ax.text(0.02, 0.97,
        "Finding: INT8 is dominated by FP32\n"
        "  - 43% slower (8.3 vs 14.6 FPS)\n"
        "  - 70% more energy per frame\n"
        "  - 3.4% lower power (within noise)",
        transform=ax.transAxes,
        fontsize=9,
        verticalalignment="top",
        bbox=dict(boxstyle="round", facecolor="wheat", alpha=0.8))

ax.legend(loc="lower right")
plt.tight_layout()

out_path = OUT / "pareto_fp32_int8_baselines.png"
plt.savefig(out_path, dpi=300, bbox_inches="tight")
print(f"Saved: {out_path}")