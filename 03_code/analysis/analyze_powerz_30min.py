"""
analyze_powerz_30min.py
Extracts mean power and J/frame from the 30-minute paper-quality runs.
Uses end-time anchoring to align PowerZ (Windows clock) with Pi (UTC).
"""
import sqlite3
import json
import statistics
import csv as csv_mod
from pathlib import Path
from datetime import datetime

REPO_ROOT = Path(__file__).resolve().parents[2]
POWER_DIR = REPO_ROOT / "05_results" / "power_data"
RUNS_DIR  = REPO_ROOT / "05_results" / "runs"

MAPPING = [
    ("2026-05-03_thermalval_S0_rep1.db",
     "2026-05-03_012911_thermalval_S0",         "Static-S0", 1),
    ("2026-05-04_thermalval_S0_rep2.db",
     "2026-05-04_203732_thermalval_S0",         "Static-S0", 2),
    ("2026-05-04_thermalval_S0_rep3.db",
     "2026-05-05_011931_thermalval_S0",         "Static-S0", 3),
    ("2026-05-03_thermalval_S1_rep1.db",
     "2026-05-03_021631_thermalval_S1",         "Static-S1", 1),
    ("2026-05-04_thermalval_S1_rep2.db",
     "2026-05-05_015938_thermalval_S1",         "Static-S1", 2),
    ("2026-05-05_thermalval_S1_rep3.db",
     "2026-05-05_171318_thermalval_S1",         "Static-S1", 3),
    ("2026-05-03_thermalval_S2_rep1.db",
     "2026-05-03_053226_thermalval_S2",         "Static-S2", 1),
    ("2026-05-05_thermalval_S2_rep2.db",
     "2026-05-05_180734_thermalval_S2",         "Static-S2", 2),
    ("2026-05-05_thermalval_S2_rep3.db",
     "2026-05-05_200514_thermalval_S2",         "Static-S2", 3),
    ("2026-05-05_reactive_rep1.db",
     "2026-05-05_213247_scheduled_high_S0_rep1","Reactive-Threshold", 1),
    ("2026-05-05_reactive_rep2.db",
     "2026-05-05_220944_scheduled_high_S0_rep2","Reactive-Threshold", 2),
    ("2026-05-05_reactive_rep3.db",
     "2026-05-05_224659_scheduled_high_S0_rep3","Reactive-Threshold", 3),
    ("2026-05-05_proactive_rep1.db",
     "2026-05-06_011427_scheduled_high_S0_rep1","Proactive (Ours)", 1),
    ("2026-05-05_proactive_rep2.db",
     "2026-05-06_031811_scheduled_high_S0_rep2","Proactive (Ours)", 2),
    ("2026-05-05_proactive_rep3.db",
     "2026-05-06_035911_scheduled_high_S0_rep3","Proactive (Ours)", 3),
]


def get_pi_epochs(run_dir: Path) -> tuple[float, float]:
    with open(run_dir / "run_metadata.json") as f:
        meta = json.load(f)
    start = datetime.fromisoformat(
        meta["start_time_utc"].replace("Z", "+00:00")).timestamp()
    end   = datetime.fromisoformat(
        meta["end_time_utc"].replace("Z", "+00:00")).timestamp()
    return start, end


def get_fps_mean(run_dir: Path) -> float:
    rows = list(csv_mod.DictReader(open(run_dir / "inference_log.csv")))
    lats = [float(r["latency_ms"]) for r in rows
            if float(r["latency_ms"]) > 0]
    return 1000.0 / statistics.mean(lats)


def extract_power_window(db_path: Path,
                         pi_start: float, pi_end: float,
                         skip_s: float = 10.0,
                         window_s: float = 300.0) -> dict:
    # Get PowerZ end time to compute clock offset
    conn = sqlite3.connect(db_path)
    cur  = conn.cursor()
    cur.execute("SELECT MAX(Unix) FROM table_1")
    pz_max = float(cur.fetchone()[0])
    conn.close()

    # PowerZ clock offset relative to Pi UTC
    offset = pz_max - pi_end

    t_win_start = pi_start + offset + skip_s
    t_win_end   = pi_start + offset + skip_s + window_s

    conn = sqlite3.connect(db_path)
    cur  = conn.cursor()
    cur.execute(
        "SELECT VBUS, IBUS FROM table_1 WHERE Unix >= ? AND Unix <= ?",
        (t_win_start, t_win_end)
    )
    rows = cur.fetchall()
    conn.close()

    if len(rows) < 1000:
        raise ValueError(
            f"Only {len(rows)} rows in window "
            f"(offset={offset:.1f}s)"
        )

    power = [v * i for v, i in rows]
    return {
        "n_rows":       len(rows),
        "mean_power_w": statistics.mean(power),
        "std_power_w":  statistics.pstdev(power),
        "offset_s":     offset,
    }


# ── Main ──────────────────────────────────────────────────────────────
records = []

for db_name, run_name, condition, rep in MAPPING:
    db_path = POWER_DIR / db_name
    run_dir = RUNS_DIR  / run_name
    label   = f"{condition} rep{rep}"
    print(f"  {label:<30}", end=" ", flush=True)

    try:
        pi_start, pi_end = get_pi_epochs(run_dir)
        pwr = extract_power_window(db_path, pi_start, pi_end)
        fps = get_fps_mean(run_dir)
        jpf = pwr["mean_power_w"] / fps

        records.append({
            "condition":    condition,
            "rep":          rep,
            "label":        label,
            "mean_power_w": pwr["mean_power_w"],
            "std_power_w":  pwr["std_power_w"],
            "fps_mean":     fps,
            "j_per_frame":  jpf,
            "n_rows":       pwr["n_rows"],
            "offset_s":     pwr["offset_s"],
        })
        print(f"P={pwr['mean_power_w']:.3f}W  "
              f"FPS={fps:.3f}  J/fr={jpf:.4f}  "
              f"({pwr['n_rows']:,} samples, offset={pwr['offset_s']:.0f}s)")

    except Exception as e:
        print(f"ERROR: {e}")
        records.append({"condition": condition, "rep": rep,
                        "label": label, "error": str(e)})


# ── Summary ───────────────────────────────────────────────────────────
print("\n" + "="*80)
print("30-MIN PAPER RUNS — POWER AND ENERGY SUMMARY (n=3 per condition)")
print("="*80)
print(f"{'Condition':<22} {'N':>2} {'Power (W)':>14} "
      f"{'J/frame':>12} {'FPS':>8}")
print("-"*80)

conditions = ["Static-S0", "Static-S1", "Static-S2",
              "Reactive-Threshold", "Proactive (Ours)"]
summary = {}

for cond in conditions:
    recs = [r for r in records
            if r.get("condition") == cond and "error" not in r]
    if not recs:
        print(f"{cond:<22}  NO DATA")
        continue

    p_vals = [r["mean_power_w"] for r in recs]
    j_vals = [r["j_per_frame"]  for r in recs]
    f_vals = [r["fps_mean"]     for r in recs]

    p_mean = statistics.mean(p_vals)
    p_std  = statistics.pstdev(p_vals)
    j_mean = statistics.mean(j_vals)
    j_std  = statistics.pstdev(j_vals)
    f_mean = statistics.mean(f_vals)

    summary[cond] = {"p": p_mean, "j": j_mean, "f": f_mean}

    print(f"{cond:<22} {len(recs):>2} "
          f"{p_mean:>8.3f}±{p_std:<5.3f}  "
          f"{j_mean:>8.4f}±{j_std:<6.4f}  "
          f"{f_mean:>7.3f}")

# Ratios vs Static-S0
if "Static-S0" in summary:
    s0 = summary["Static-S0"]
    print(f"\nRatios vs Static-S0:")
    for cond, vals in summary.items():
        if cond == "Static-S0":
            continue
        pr = vals["p"] / s0["p"]
        jr = vals["j"] / s0["j"]
        print(f"  {cond:<22}: power {pr:.3f}x  "
              f"J/frame {jr:.3f}x")

print("="*80)

# Save
out = REPO_ROOT / "05_results" / "power_analysis_30min.csv"
fieldnames = ["condition", "rep", "label", "mean_power_w",
              "std_power_w", "fps_mean", "j_per_frame", "n_rows", "offset_s"]
with open(out, "w", newline="") as f:
    w = csv_mod.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
    w.writeheader()
    w.writerows([r for r in records if "error" not in r])
print(f"\nSaved: {out}")