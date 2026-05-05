"""
plot_scheduler_decisions.py
Generates Figure 5: Scheduler decision timeline from pilot run.
Uses: 05_results/runs/2026-05-03_195826_scheduled_high_S0_rep1/
Output: 05_results/plots/scheduler_decision_timeline.png
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import pandas as pd
import numpy as np
from pathlib import Path

RUN_DIR = (Path(__file__).resolve().parents[2]
           / "05_results/runs/2026-05-03_195826_scheduled_high_S0_rep1")
OUT     = Path(__file__).resolve().parents[2] / "05_results/plots"
OUT.mkdir(parents=True, exist_ok=True)

# ── Load data ────────────────────────────────────────────────────────
dec = pd.read_csv(RUN_DIR / "scheduler_decisions.csv")
tel = pd.read_csv(RUN_DIR / "telemetry_derived.csv")

# Clean up
dec = dec[dec["monotonic_offset_s"].notna()].copy()
dec["t"] = dec["monotonic_offset_s"].astype(float)
dec["T"] = pd.to_numeric(dec["T"], errors="coerce")
dec["T_dot"] = pd.to_numeric(dec["T_dot"], errors="coerce")

tel["t"] = tel["monotonic_offset_s"].astype(float)
tel["T"] = pd.to_numeric(tel["T"], errors="coerce")
tel["T_dot"] = pd.to_numeric(tel["T_dot"], errors="coerce")

# Map DVFS state to numeric Y for plotting
state_map = {"S0": 0, "S1": 1, "S2": 2}
dec["state_num"] = dec["dvfs_state"].map(state_map).fillna(0)

# Colour by reason
reason_colors = {
    "dwell_hold":          "#AAAAAA",
    "no_change":           "#AAAAAA",
    "confirm_hold":        "#FF8C00",
    "escalate_reactive_T": "#C00000",
    "escalate_proactive_T_dot": "#9B59B6",
    "recover_T_below_floor": "#27AE60",
    "runtime_start_default": "#AAAAAA",
    "missing_signal":      "#AAAAAA",
}

# ── Plot ─────────────────────────────────────────────────────────────
fig, axes = plt.subplots(3, 1, figsize=(11, 8), sharex=True,
                          gridspec_kw={"height_ratios": [1.5, 2, 2]})

# ── Panel 1: DVFS state ──────────────────────────────────────────────
ax = axes[0]
for _, row in dec.iterrows():
    color = reason_colors.get(str(row["reason"]).strip(), "#AAAAAA")
    ax.scatter(row["t"], row["state_num"],
               c=color, s=8, alpha=0.6, linewidths=0)

ax.set_yticks([0, 1, 2])
ax.set_yticklabels(["S0\n(2400)", "S1\n(1800)", "S2\n(1500)"], fontsize=9)
ax.set_ylabel("DVFS State", fontsize=10)
ax.set_ylim(-0.4, 2.4)
ax.grid(axis="x", alpha=0.3)

# Annotate the switch
ax.axvline(165.5, color="#FF8C00", lw=1.2, linestyle="--", alpha=0.8)
ax.axvline(167.5, color="#C00000", lw=1.5, linestyle="-", alpha=0.9)
ax.text(165.5, 2.2, "CONFIRM\nHOLD\n(t=165.5s)", ha="center", fontsize=7.5,
        color="#FF8C00", fontweight="bold")
ax.text(167.5, 2.2, "ESCALATE\n(t=167.5s)", ha="center", fontsize=7.5,
        color="#C00000", fontweight="bold")

legend_patches = [
    mpatches.Patch(color="#AAAAAA", label="No change / Dwell hold"),
    mpatches.Patch(color="#FF8C00", label="Confirm hold"),
    mpatches.Patch(color="#C00000", label="Escalate (reactive T)"),
    mpatches.Patch(color="#27AE60", label="Recover"),
]
ax.legend(handles=legend_patches, fontsize=8, loc="upper right",
          ncol=2, framealpha=0.9)
ax.set_title("Scheduler Decision Timeline — Pilot Run (10 min, passive, 22.7°C)",
             fontsize=11, fontweight="bold")

# ── Panel 2: T(t) ────────────────────────────────────────────────────
ax = axes[1]
ax.plot(tel["t"], tel["T"], color="#2C3E50", lw=1.2, label="T (°C)")
ax.axhline(75.0, color="#C00000", lw=1.0, linestyle="--", alpha=0.7,
           label="T_esc threshold (75°C)")
ax.axvline(165.5, color="#FF8C00", lw=1.2, linestyle="--", alpha=0.8)
ax.axvline(167.5, color="#C00000", lw=1.5, linestyle="-", alpha=0.9)
ax.set_ylabel("Temperature (°C)", fontsize=10)
ax.set_ylim(40, 82)
ax.legend(fontsize=9, loc="upper left")
ax.grid(alpha=0.3)

# ── Panel 3: T_dot(t) ────────────────────────────────────────────────
ax = axes[2]
tdot = tel["T_dot"].dropna()
t_td = tel.loc[tdot.index, "t"]
ax.plot(t_td, tdot, color="#2980B9", lw=1.0, alpha=0.8, label="T_dot (°C/s)")
ax.axhline(0.5, color="#9B59B6", lw=1.0, linestyle="--", alpha=0.8,
           label="Proactive trigger (0.5 °C/s)")
ax.axhline(0.0, color="black", lw=0.5, linestyle="-", alpha=0.4)
ax.axvline(165.5, color="#FF8C00", lw=1.2, linestyle="--", alpha=0.8)
ax.axvline(167.5, color="#C00000", lw=1.5, linestyle="-", alpha=0.9)

# Annotate the negative T_dot at 165.5s
ax.annotate("T_dot < 0\n→ counter reset",
            xy=(165.5, -0.06), xytext=(150, -0.35),
            fontsize=8, ha="center", color="#FF8C00",
            arrowprops=dict(arrowstyle="->", color="#FF8C00", lw=0.8))

ax.set_ylabel("T_dot (°C/s)", fontsize=10)
ax.set_xlabel("Time since run start (seconds)", fontsize=10)
ax.set_ylim(-0.7, 0.85)
ax.legend(fontsize=9, loc="upper right")
ax.grid(alpha=0.3)

ax.set_xlim(0, dec["t"].max())

fig.tight_layout()
outpath = OUT / "scheduler_decision_timeline.png"
fig.savefig(outpath, dpi=200, bbox_inches="tight")
plt.close(fig)
print(f"Saved: {outpath}")