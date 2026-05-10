#!/usr/bin/env python3
"""
compute_statistics.py
=====================
Task 24 (WorkPlan §8.5): Formal statistical analysis for IEEE IoT-J paper.

Reads all run directories from 05_results/runs/, computes per-run raw statistics
from inference_log.csv + telemetry_raw.csv, merges power data from
power_analysis_30min.csv, and produces three output CSVs:

  run_stats.csv            — raw per-run stats (15 rows)
  condition_stats.csv      — mean ± SD + 95% bootstrap CI per condition (5 rows)
  pairwise_comparisons.csv — Proactive vs each baseline: delta, CI, Cohen's d

Statistical notes
-----------------
n=3 per condition. t-test with df=2 will be underpowered — p-values are
reported for completeness but NOT the primary evidence. Primary evidence:
bootstrap CI overlap and effect size (Cohen's d). Both are printed.

Bootstrap method: BCa (scipy ≥1.7) with percentile fallback. seed=42 per
Reproducibility Rule. 10,000 resamples. CI level: 95%.

Analysis window
---------------
  Skip: t < 10.0 s  (model load transient — per EXPERIMENTAL_PROTOCOL.md)
  Plateau window: t ≥ 600 s (well past τ_thermal for all conditions)
  Full window: 10.0 s < t ≤ 1800.0 s (30 min)

Usage (run from repo root on Windows dev machine)
-------------------------------------------------
  python 03_code/analysis/compute_statistics.py
  python 03_code/analysis/compute_statistics.py --runs-dir 05_results/runs --output-dir 05_results

Dependencies
------------
  numpy, scipy (pip install numpy scipy)

No Silent Changes Rule
----------------------
  This script is read-only with respect to run data. It reads CSVs and writes
  only to 05_results/. No run data is modified. Document any changes to
  threshold constants (SKIP_S, PLATEAU_START_S) in CHANGELOG.md before rerunning.

Grounding
---------
  WorkPlan_marked.pdf §8.5 (Task 24): statistical analysis
  HANDOFF.md: run directory naming convention, condition mapping, analysis window
  EXPERIMENTAL_PROTOCOL.md: SKIP_S, TOTAL_DURATION_S
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

log = logging.getLogger("compute_statistics")
logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")

# ---------------------------------------------------------------------------
# Analysis constants — match EXPERIMENTAL_PROTOCOL.md.
# To change any of these, add a CHANGELOG entry first (No Silent Changes Rule).
# ---------------------------------------------------------------------------

SKIP_S: float = 10.0           # skip first N seconds (model load transient)
PLATEAU_START_S: float = 600.0 # T_plateau window start (all conds plateau by 6 min)
TOTAL_DURATION_S: float = 1800.0  # 30-min nominal run duration

BOOTSTRAP_SEED: int = 42        # fixed per Reproducibility Rule
N_RESAMPLES: int = 10_000
CI_LEVEL: float = 0.95

# Paper-order for output rows
PAPER_CONDITION_ORDER: List[str] = [
    "Static-S0",
    "Static-S1",
    "Static-S2",
    "Reactive-Threshold",
    "Proactive",
]

# Directory name tokens → condition label
# Static runs: *_thermalval_S{0,1,2}*
# Dynamic runs: *_scheduled_*  (scheduler_mode from run_metadata.json)
STATIC_TOKEN_MAP: Dict[str, str] = {
    "thermalval_S0": "Static-S0",
    "thermalval_S1": "Static-S1",
    "thermalval_S2": "Static-S2",
}

# Pilot run prefix — excluded from paper analysis
PILOT_TOKENS = ("rep0", "pilot", "195826")  # matches 2026-05-03_195826 pilot dir


# ---------------------------------------------------------------------------
# Directory parsing
# ---------------------------------------------------------------------------

def parse_run_directory(run_dir: Path) -> Optional[Dict]:
    """
    Determine condition and rep from directory name + run_metadata.json.
    Returns None for non-paper runs (pilot, partial runs, unknown dirs).
    """
    name = run_dir.name

    # Exclude pilot run explicitly
    if any(tok in name for tok in PILOT_TOKENS):
        log.info("Excluding pilot run: %s", name)
        return None

    meta = _load_metadata(run_dir)

    # Static runs: name contains thermalval_S{0,1,2}
    for token, condition in STATIC_TOKEN_MAP.items():
        if token in name:
            rep = _extract_rep(name, meta)
            return {
                "condition": condition,
                "rep": rep,
                "path": run_dir,
                "meta": meta or {},
                "scheduler_mode": "static",
            }

    # Dynamic runs: name contains "scheduled"
    if "scheduled" in name:
        if meta is None:
            log.warning("No run_metadata.json in dynamic run %s — skipping", name)
            return None
        mode = meta.get("tags", {}).get("scheduler", "")
        if mode == "reactive_threshold":
            condition = "Reactive-Threshold"
        elif mode == "proactive":
            condition = "Proactive"
        else:
            log.warning("Unknown scheduler_mode '%s' in %s — skipping", mode, name)
            return None
        rep = _extract_rep(name, meta)
        return {
            "condition": condition,
            "rep": rep,
            "path": run_dir,
            "meta": meta,
            "scheduler_mode": mode,
        }

    log.debug("Not a paper run: %s", name)
    return None


def _extract_rep(name: str, meta: Optional[Dict]) -> str:
    """Extract rep number. Directory name takes precedence for dynamic runs."""
    # Try metadata first
    if meta:
        for key in ("rep", "rep_number", "repetition"):
            if key in meta:
                return str(meta[key])
    # Fall back to dir name suffix _rep{N}
    for part in name.split("_"):
        if part.startswith("rep") and len(part) > 3 and part[3:].isdigit():
            return part[3:]
    return "?"


def _load_metadata(run_dir: Path) -> Optional[Dict]:
    for fname in ("run_metadata.json", "metadata.json"):
        p = run_dir / fname
        if p.exists():
            try:
                with open(p, encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                log.warning("Could not parse %s: %s", p, e)
    return None


# ---------------------------------------------------------------------------
# Per-run statistics from CSV files
# ---------------------------------------------------------------------------

def compute_inference_stats(run_dir: Path) -> Optional[Dict]:
    """
    FPS statistics from inference_log.csv.
    Window: monotonic_time_s > SKIP_S.
    Returns fps_mean, fps_std, fps_cv_pct, frame_count.
    """
    path = run_dir / "inference_log.csv"
    if not path.exists():
        log.warning("inference_log.csv missing: %s", run_dir.name)
        return None

    fps_vals: List[float] = []
    try:
        with open(path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                t = _to_float(row.get("monotonic_time_s"))
                lat = _to_float(row.get("latency_ms"))
                if t is None or lat is None or lat <= 0:
                    continue
                if t > SKIP_S:
                    fps_vals.append(1000.0 / lat)
    except Exception as e:
        log.error("Failed reading inference_log.csv in %s: %s", run_dir.name, e)
        return None

    if len(fps_vals) < 50:
        log.warning("Only %d valid frames in %s — data suspect", len(fps_vals), run_dir.name)
        return None

    arr = np.array(fps_vals)
    mean = float(np.mean(arr))
    std = float(np.std(arr, ddof=1))
    cv = (std / mean * 100.0) if mean > 0 else float("nan")
    return {
        "fps_mean": mean,
        "fps_std": std,
        "fps_cv_pct": cv,
        "frame_count": len(fps_vals),
    }


def compute_thermal_stats(run_dir: Path) -> Optional[Dict]:
    """
    Thermal + throttle statistics from telemetry_raw.csv.

    T_plateau: mean(T) for t in [PLATEAU_START_S, TOTAL_DURATION_S]
    T_plateau_std: std(T) same window — captures sensor noise at steady state
    throttle_count: Σ(throttled_now == 1) for t in (SKIP_S, TOTAL_DURATION_S]
    throttle_fraction: throttle_count / total_samples_in_window

    Note: throttled_now = bit 0 of vcgencmd get_throttled (current throttle only,
    not sticky historical bits). See HANDOFF.md §Telemetry CSV Schema.
    """
    path = run_dir / "telemetry_raw.csv"
    if not path.exists():
        log.warning("telemetry_raw.csv missing: %s", run_dir.name)
        return None

    temps_plateau: List[float] = []
    throttle_count = 0
    total_samples = 0

    try:
        with open(path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                t = _to_float(row.get("monotonic_offset_s"))
                if t is None:
                    continue

                # Throttle window: full analysis window
                if SKIP_S < t <= TOTAL_DURATION_S:
                    total_samples += 1
                    thr_raw = row.get("throttled_now", "").strip()
                    # Accept "1", "1.0", "True" — reject "0", "0.0", "", "None"
                    if thr_raw in ("1", "1.0", "True"):
                        throttle_count += 1

                # Plateau temperature window
                if PLATEAU_START_S <= t <= TOTAL_DURATION_S:
                    temp = _to_float(row.get("temp_soc_c"))
                    if temp is not None:
                        temps_plateau.append(temp)

    except Exception as e:
        log.error("Failed reading telemetry_raw.csv in %s: %s", run_dir.name, e)
        return None

    if not temps_plateau:
        log.warning("No plateau temperature samples in %s (plateau_start=%.0fs)",
                    run_dir.name, PLATEAU_START_S)
        T_plateau = T_std = None
    else:
        arr = np.array(temps_plateau)
        T_plateau = float(np.mean(arr))
        T_std = float(np.std(arr, ddof=1))

    return {
        "T_plateau_c": T_plateau,
        "T_plateau_std_c": T_std,
        "throttle_count": throttle_count,
        "throttle_fraction": (throttle_count / total_samples) if total_samples > 0 else None,
        "total_thermal_samples": total_samples,
    }


def compute_time_at_state(run_dir: Path) -> Optional[Dict]:
    """
    Time-at-state breakdown from scheduler_decisions.csv.
    Valid only for dynamic runs (reactive/proactive). Returns None for static.

    Method: each row gives state active FROM that timestamp TO the next row's
    timestamp (or TOTAL_DURATION_S for the final row). Clipped to analysis window.
    """
    path = run_dir / "scheduler_decisions.csv"
    if not path.exists():
        return None  # Normal for static runs

    rows: List[Tuple[float, str]] = []
    try:
        with open(path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                t = _to_float(row.get("monotonic_offset_s"))
                state = row.get("dvfs_state", "").strip()
                if t is not None and state:
                    rows.append((t, state))
    except Exception as e:
        log.error("Failed reading scheduler_decisions.csv in %s: %s", run_dir.name, e)
        return None

    if len(rows) < 2:
        log.warning("Fewer than 2 decision rows in %s", run_dir.name)
        return {"time_at_S0_s": None, "time_at_S1_s": None, "time_at_S2_s": None}

    time_at: Dict[str, float] = defaultdict(float)

    for i, (t_start, state) in enumerate(rows):
        t_end = rows[i + 1][0] if (i + 1 < len(rows)) else TOTAL_DURATION_S
        t_end = min(t_end, TOTAL_DURATION_S)
        t_start_clipped = max(t_start, SKIP_S)
        if t_end > t_start_clipped and state in ("S0", "S1", "S2"):
            time_at[state] += t_end - t_start_clipped

    total = sum(time_at.values())
    result = {}
    for state in ("S0", "S1", "S2"):
        result[f"time_at_{state}_s"] = time_at.get(state, 0.0)
        result[f"time_at_{state}_pct"] = (
            100.0 * time_at.get(state, 0.0) / total if total > 0 else None
        )
    return result


# ---------------------------------------------------------------------------
# Bootstrap CI and effect sizes
# ---------------------------------------------------------------------------

def bootstrap_ci(
    data: List[float],
    statistic=None,
    n_resamples: int = N_RESAMPLES,
    ci: float = CI_LEVEL,
    seed: int = BOOTSTRAP_SEED,
) -> Tuple[Optional[float], Optional[float]]:
    """
    Compute bootstrap confidence interval.

    Attempts BCa method via scipy.stats.bootstrap (preferred for skewed small-n).
    Falls back to percentile bootstrap if scipy unavailable or BCa fails (can
    happen at n=3 where acceleration jackknife estimate is degenerate).

    Arguments
    ---------
    data      : list of per-run statistics (e.g., 3 FPS means)
    statistic : callable, default np.mean
    """
    if statistic is None:
        statistic = np.mean

    arr = np.array(data, dtype=float)
    n = len(arr)

    if n < 2:
        return None, None

    # BCa via scipy (best method)
    try:
        from scipy.stats import bootstrap as sp_bootstrap
        result = sp_bootstrap(
            (arr,),
            statistic=statistic,
            n_resamples=n_resamples,
            confidence_level=ci,
            random_state=seed,
            method="BCa",
        )
        lo = float(result.confidence_interval.low)
        hi = float(result.confidence_interval.high)
        if np.isfinite(lo) and np.isfinite(hi):
            return lo, hi
        # BCa degenerate at n=3 — fall through
        log.debug("BCa returned non-finite CI for n=%d, falling back to percentile", n)
    except Exception:
        pass

    # Percentile bootstrap fallback
    rng = np.random.default_rng(seed)
    boot_stats = np.array([
        statistic(rng.choice(arr, size=n, replace=True))
        for _ in range(n_resamples)
    ])
    alpha = (1.0 - ci) / 2.0
    lo = float(np.nanpercentile(boot_stats, 100.0 * alpha))
    hi = float(np.nanpercentile(boot_stats, 100.0 * (1.0 - alpha)))
    return lo, hi


def cohen_d_paired(a: List[float], b: List[float]) -> Optional[float]:
    """
    Cohen's d for paired observations (uses SD of differences).
    Measures effect size independent of sample size — the primary
    evidence at n=3 where p-values have low power.
    """
    if len(a) != len(b) or len(a) < 2:
        return None
    diffs = [x - y for x, y in zip(a, b)]
    mean_d = float(np.mean(diffs))
    std_d = float(np.std(diffs, ddof=1))
    return mean_d / std_d if std_d > 0 else None


def paired_t_test(a: List[float], b: List[float]) -> Tuple[Optional[float], Optional[float]]:
    """
    Paired t-test (df = n-1). For n=3, df=2 → conservative.
    Report but do NOT use as primary evidence (insufficient power).
    """
    try:
        from scipy.stats import ttest_rel
        t_stat, p_val = ttest_rel(a, b)
        return float(t_stat), float(p_val)
    except Exception:
        return None, None


# ---------------------------------------------------------------------------
# Aggregation helpers
# ---------------------------------------------------------------------------

def _group_metric(runs: List[Dict], key: str) -> Dict:
    """Extract values for `key` from all runs, compute mean±SD + bootstrap CI."""
    vals = [r[key] for r in runs if r.get(key) is not None and np.isfinite(r[key])]
    if not vals:
        return {"mean": None, "std": None, "ci_lo": None, "ci_hi": None, "n": 0}
    arr = np.array(vals)
    mean = float(np.mean(arr))
    std = float(np.std(arr, ddof=1)) if len(arr) > 1 else None
    lo, hi = bootstrap_ci(vals)
    return {"mean": mean, "std": std, "ci_lo": lo, "ci_hi": hi, "n": len(vals)}


# ---------------------------------------------------------------------------
# Power CSV loading
# ---------------------------------------------------------------------------

def load_power_data(power_csv: Optional[Path]) -> Dict[str, Dict]:
    """
    Load per-run power metrics from analyze_powerz_30min.py output.
    Aggressively hunts for column names to handle version mismatches.
    """
    if power_csv is None or not power_csv.exists():
        log.warning("Power CSV not found — power metrics will be N/A in output")
        return {}

    lookup: Dict[str, Dict] = {}
    try:
        with open(power_csv, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames or []
            
            # Dynamically identify columns
            run_col = next((c for c in headers if c.lower() in ["run", "run_dir", "condition"]), None)
            pwr_col = next((c for c in headers if "power" in c.lower()), None)
            jpf_col = next((c for c in headers if "j/frame" in c.lower() or "j_per_frame" in c.lower()), None)

            if not run_col:
                log.error("Could not find a valid run/condition column in power CSV.")
                return {}

            for row in reader:
                # Clean key: remove "(Ours)" and normalize spaces so "Proactive rep1" matches perfectly
                raw_key = row.get(run_col, "").replace("(Ours)", "").strip()
                key = " ".join(raw_key.split())
                
                if key:
                    lookup[key] = {
                        "mean_power_w": _to_float(row.get(pwr_col)) if pwr_col else None,
                        "j_per_frame": _to_float(row.get(jpf_col)) if jpf_col else None,
                    }
        log.info("Loaded power data for %d runs from %s", len(lookup), power_csv.name)
    except Exception as e:
        log.error("Could not read power CSV %s: %s", power_csv, e)

    return lookup


# ---------------------------------------------------------------------------
# CSV output writers
# ---------------------------------------------------------------------------

def write_run_stats(runs: List[Dict], path: Path) -> None:
    """Write per-run raw statistics (15 rows for 15 runs)."""
    if not runs:
        return

    # Define column order explicitly
    col_order = [
        "condition", "rep", "run_dir",
        "fps_mean", "fps_std", "fps_cv_pct", "frame_count",
        "T_plateau_c", "T_plateau_std_c",
        "throttle_count", "throttle_fraction", "total_thermal_samples",
        "mean_power_w", "j_per_frame",
        "time_at_S0_s", "time_at_S0_pct",
        "time_at_S1_s", "time_at_S1_pct",
        "time_at_S2_s", "time_at_S2_pct",
        "scheduler_mode",
    ]
    all_keys = list({k for r in runs for k in r.keys() if k != "meta" and k != "path"})
    ordered = [c for c in col_order if c in all_keys]
    ordered += sorted([c for c in all_keys if c not in ordered])

    sorted_runs = sorted(
        runs,
        key=lambda x: (
            PAPER_CONDITION_ORDER.index(x["condition"])
            if x["condition"] in PAPER_CONDITION_ORDER else 99,
            str(x.get("rep", "")),
        ),
    )

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=ordered, extrasaction="ignore")
        writer.writeheader()
        for r in sorted_runs:
            writer.writerow({
                k: (_fmt(v, 4) if isinstance(v, float) else v)
                for k, v in r.items()
                if k in ordered
            })
    log.info("Wrote %d rows → %s", len(sorted_runs), path)


def write_condition_stats(by_condition: Dict[str, List[Dict]], path: Path) -> None:
    """Write condition-level means ± SD with 95% bootstrap CI."""
    rows = []
    for condition in PAPER_CONDITION_ORDER:
        if condition not in by_condition:
            log.warning("Condition '%s' not found in run data", condition)
            continue
        runs = by_condition[condition]
        n = len(runs)

        fps = _group_metric(runs, "fps_mean")
        fps_cv = _group_metric(runs, "fps_cv_pct")
        t_plat = _group_metric(runs, "T_plateau_c")
        thr = _group_metric(runs, "throttle_count")
        pw = _group_metric(runs, "mean_power_w")
        jpf = _group_metric(runs, "j_per_frame")
        t_s0_pct = _group_metric(runs, "time_at_S0_pct")
        t_s1_pct = _group_metric(runs, "time_at_S1_pct")
        t_s2_pct = _group_metric(runs, "time_at_S2_pct")

        rows.append({
            "condition": condition,
            "n_reps": n,
            # FPS
            "fps_mean": _fmt(fps["mean"]),
            "fps_std": _fmt(fps["std"]),
            "fps_cv_pct": _fmt(fps_cv["mean"], 1),
            "fps_95ci": _ci_str(fps["ci_lo"], fps["ci_hi"]),
            # Temperature
            "T_plateau_mean_c": _fmt(t_plat["mean"], 1),
            "T_plateau_std_c": _fmt(t_plat["std"], 1),
            "T_plateau_95ci": _ci_str(t_plat["ci_lo"], t_plat["ci_hi"], 1),
            # Throttle
            "throttle_mean": _fmt(thr["mean"], 0) if thr["mean"] is not None else "N/A",
            "throttle_std": _fmt(thr["std"], 0) if thr["std"] is not None else "N/A",
            "throttle_95ci": _ci_str(thr["ci_lo"], thr["ci_hi"], 0),
            # Power
            "mean_power_w": _fmt(pw["mean"]),
            "power_std_w": _fmt(pw["std"]),
            "j_per_frame": _fmt(jpf["mean"], 4) if jpf["mean"] is not None else "N/A",
            "jpf_95ci": _ci_str(jpf["ci_lo"], jpf["ci_hi"], 4),
            # Time at state (dynamic only)
            "time_at_S0_pct": _fmt(t_s0_pct["mean"], 1) if t_s0_pct["mean"] is not None else "N/A",
            "time_at_S1_pct": _fmt(t_s1_pct["mean"], 1) if t_s1_pct["mean"] is not None else "N/A",
            "time_at_S2_pct": _fmt(t_s2_pct["mean"], 1) if t_s2_pct["mean"] is not None else "N/A",
        })

    if not rows:
        log.error("No condition data to write")
        return

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    log.info("Wrote %d conditions → %s", len(rows), path)


def write_pairwise_comparisons(by_condition: Dict[str, List[Dict]], path: Path) -> None:
    """
    Proactive vs each baseline: delta (absolute + %), 95% bootstrap CI of delta,
    Cohen's d (primary effect size), and paired t-test (supplementary).

    For n=3: Cohen's d is more interpretable than p-value.
    Interpretation: |d| > 0.8 = large, 0.5-0.8 = medium, < 0.5 = small.
    """
    if "Proactive" not in by_condition:
        log.error("No Proactive runs — cannot write comparisons")
        return

    p_runs = by_condition["Proactive"]

    def _vals(runs, key):
        return [r[key] for r in runs if r.get(key) is not None]

    p_fps = _vals(p_runs, "fps_mean")
    p_jpf = _vals(p_runs, "j_per_frame")
    p_thr = _vals(p_runs, "throttle_count")
    p_T = _vals(p_runs, "T_plateau_c")

    rows = []
    for baseline in [c for c in PAPER_CONDITION_ORDER if c != "Proactive"]:
        if baseline not in by_condition:
            continue
        b_runs = by_condition[baseline]
        b_fps = _vals(b_runs, "fps_mean")
        b_jpf = _vals(b_runs, "j_per_frame")
        b_thr = _vals(b_runs, "throttle_count")
        b_T = _vals(b_runs, "T_plateau_c")

        row: Dict = {"comparison": f"Proactive vs {baseline}"}

        # FPS comparison
        if p_fps and b_fps and len(p_fps) == len(b_fps):
            diffs = [a - b for a, b in zip(p_fps, b_fps)]
            delta_m = float(np.mean(diffs))
            delta_pct = 100.0 * delta_m / float(np.mean(b_fps))
            lo, hi = bootstrap_ci(diffs)
            t_stat, p_val = paired_t_test(p_fps, b_fps)
            d = cohen_d_paired(p_fps, b_fps)
            row.update({
                "fps_delta": _fmt(delta_m),
                "fps_delta_pct": _fmt(delta_pct, 1),
                "fps_delta_95ci": _ci_str(lo, hi),
                "fps_cohen_d": _fmt(d),
                "fps_t_stat": _fmt(t_stat),
                "fps_p_value": _fmt(p_val, 4),
                "fps_df": len(p_fps) - 1,
            })

        # J/frame comparison
        if p_jpf and b_jpf and len(p_jpf) == len(b_jpf):
            diffs = [a - b for a, b in zip(p_jpf, b_jpf)]
            delta_m = float(np.mean(diffs))
            delta_pct = 100.0 * delta_m / float(np.mean(b_jpf))
            lo, hi = bootstrap_ci(diffs)
            d = cohen_d_paired(p_jpf, b_jpf)
            row.update({
                "jpf_delta": _fmt(delta_m, 4),
                "jpf_delta_pct": _fmt(delta_pct, 1),
                "jpf_delta_95ci": _ci_str(lo, hi, 4),
                "jpf_cohen_d": _fmt(d),
            })

        # Throttle count comparison
        if p_thr and b_thr and len(p_thr) == len(b_thr):
            diffs = [a - b for a, b in zip(p_thr, b_thr)]
            delta_m = float(np.mean(diffs))
            row["throttle_delta_mean"] = _fmt(delta_m, 0)

        # Temperature comparison
        if p_T and b_T and len(p_T) == len(b_T):
            diffs = [a - b for a, b in zip(p_T, b_T)]
            delta_m = float(np.mean(diffs))
            lo, hi = bootstrap_ci(diffs)
            row.update({
                "T_delta_c": _fmt(delta_m, 1),
                "T_delta_95ci": _ci_str(lo, hi, 1),
            })

        rows.append(row)

    if not rows:
        return

    all_keys: List[str] = []
    for r in rows:
        for k in r:
            if k not in all_keys:
                all_keys.append(k)

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=all_keys, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    log.info("Wrote %d comparisons → %s", len(rows), path)


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _to_float(val) -> Optional[float]:
    if val is None:
        return None
    s = str(val).strip()
    if s in ("", "None", "nan", "N/A", "null"):
        return None
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


def _fmt(val, decimals: int = 3) -> str:
    if val is None:
        return "N/A"
    if not np.isfinite(val):
        return "N/A"
    return f"{val:.{decimals}f}"


def _ci_str(lo, hi, decimals: int = 3) -> str:
    if lo is None or hi is None:
        return "N/A"
    return f"[{_fmt(lo, decimals)}, {_fmt(hi, decimals)}]"


# ---------------------------------------------------------------------------
# Summary printer
# ---------------------------------------------------------------------------

def print_summary(by_condition: Dict[str, List[Dict]], by_cond_agg: Dict) -> None:
    """Print human-readable summary matching paper Table IV structure."""
    SEP = "=" * 90
    print(f"\n{SEP}")
    print("PAPER TABLE IV — CONDITION SUMMARY (95% Bootstrap CI,  n=3 per condition)")
    print(SEP)
    hdr = (f"{'Condition':<22} {'FPS mean':>10} {'FPS std':>9} {'CV%':>6} "
           f"{'T_plateau':>11} {'Throttle':>10} {'J/frame':>10}")
    print(hdr)
    print("-" * 90)
    for condition in PAPER_CONDITION_ORDER:
        if condition not in by_condition:
            continue
        runs = by_condition[condition]
        fps_m = _to_float(_fmt(by_cond_agg[condition]["fps"]["mean"]))
        fps_s = _to_float(_fmt(by_cond_agg[condition]["fps"]["std"]))
        fps_ci_lo = by_cond_agg[condition]["fps"]["ci_lo"]
        fps_ci_hi = by_cond_agg[condition]["fps"]["ci_hi"]
        t_m = by_cond_agg[condition]["T_plateau"]["mean"]
        thr_m = by_cond_agg[condition]["throttle"]["mean"]
        jpf_m = by_cond_agg[condition]["jpf"]["mean"]
        cv_m = by_cond_agg[condition]["fps_cv"]["mean"]

        fps_str = f"{fps_m:.3f}" if fps_m is not None else "N/A"
        fps_std_str = f"{fps_s:.3f}" if fps_s is not None else "N/A"
        cv_str = f"{cv_m:.1f}" if cv_m is not None else "N/A"
        t_str = f"{t_m:.1f}°C" if t_m is not None else "N/A"
        thr_str = f"{thr_m:.0f}" if thr_m is not None else "N/A"
        jpf_str = f"{jpf_m:.4f}" if jpf_m is not None else "N/A"
        ci_str = (f"[{fps_ci_lo:.3f},{fps_ci_hi:.3f}]"
                  if fps_ci_lo is not None and fps_ci_hi is not None else "")

        print(f"{condition:<22} {fps_str:>10} {fps_std_str:>9} {cv_str:>6} "
              f"{t_str:>11} {thr_str:>10} {jpf_str:>10}  {ci_str}")

    print(f"{SEP}\n")
    print("PAIRWISE: Proactive vs baselines")
    print("-" * 60)
    p_runs = by_condition.get("Proactive", [])
    if not p_runs:
        return
    p_fps_mean = float(np.mean([r["fps_mean"] for r in p_runs if r.get("fps_mean")]))
    p_jpf_mean = float(np.mean([r["j_per_frame"] for r in p_runs
                                 if r.get("j_per_frame") is not None]))
    for baseline in [c for c in PAPER_CONDITION_ORDER if c != "Proactive"]:
        if baseline not in by_condition:
            continue
        b_runs = by_condition[baseline]
        b_fps = [r["fps_mean"] for r in b_runs if r.get("fps_mean") is not None]
        b_jpf = [r["j_per_frame"] for r in b_runs if r.get("j_per_frame") is not None]
        if b_fps:
            d_fps_pct = 100.0 * (p_fps_mean - np.mean(b_fps)) / np.mean(b_fps)
            print(f"  vs {baseline:<22}  ΔFPS = {d_fps_pct:+.1f}%", end="")
        if b_jpf:
            d_jpf_pct = 100.0 * (p_jpf_mean - np.mean(b_jpf)) / np.mean(b_jpf)
            print(f"   ΔJ/frame = {d_jpf_pct:+.1f}%", end="")
        print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(runs_dir: Path, power_csv: Optional[Path], output_dir: Path) -> None:
    log.info("Runs directory : %s", runs_dir.resolve())
    log.info("Power CSV      : %s", power_csv or "not provided")
    log.info("Output dir     : %s", output_dir.resolve())
    log.info("Analysis window: skip=%.0fs  plateau_start=%.0fs  total=%.0fs",
             SKIP_S, PLATEAU_START_S, TOTAL_DURATION_S)

    output_dir.mkdir(parents=True, exist_ok=True)

    # Discover all run directories
    run_dirs = sorted(d for d in runs_dir.iterdir() if d.is_dir())
    log.info("Found %d directories in %s", len(run_dirs), runs_dir)

    # Parse and compute stats per run
    all_runs: List[Dict] = []
    for d in run_dirs:
        info = parse_run_directory(d)
        if info is None:
            continue

        stats: Dict = {
            "condition": info["condition"],
            "rep": info["rep"],
            "run_dir": d.name,
            "scheduler_mode": info["scheduler_mode"],
        }

        infer = compute_inference_stats(d)
        if infer:
            stats.update(infer)

        therm = compute_thermal_stats(d)
        if therm:
            stats.update(therm)

        state_t = compute_time_at_state(d)
        if state_t:
            stats.update(state_t)

        all_runs.append(stats)
        log.info(
            "[%-22s rep%s]  FPS=%.3f±%.3f  T_plat=%.1f°C  throttle=%s",
            info["condition"],
            info["rep"],
            infer["fps_mean"] if infer else float("nan"),
            infer["fps_std"] if infer else float("nan"),
            therm["T_plateau_c"] if (therm and therm.get("T_plateau_c")) else float("nan"),
            therm["throttle_count"] if therm else "?",
        )

    log.info("Parsed %d valid paper runs", len(all_runs))
    if len(all_runs) != 15:
        log.warning(
            "Expected 15 paper runs (5 conditions × 3 reps), found %d. "
            "Check run directory names and run_metadata.json fields.",
            len(all_runs)
        )

    # Merge power data
    power_lookup = load_power_data(power_csv)
    for r in all_runs:
        # Try to match the exact folder name first, then fallback to "Condition repX" format
        alt_key = f"{r['condition']} rep{r['rep']}"
        pw = power_lookup.get(r["run_dir"]) or power_lookup.get(alt_key, {})
        r["mean_power_w"] = pw.get("mean_power_w")
        r["j_per_frame"] = pw.get("j_per_frame")

    # Write per-run CSV
    write_run_stats(all_runs, output_dir / "run_stats.csv")

    # Group by condition
    by_condition: Dict[str, List[Dict]] = defaultdict(list)
    for r in all_runs:
        by_condition[r["condition"]].append(r)

    # Build aggregated stats for summary (separate from CSV to avoid duplication)
    by_cond_agg: Dict = {}
    for condition, runs in by_condition.items():
        by_cond_agg[condition] = {
            "fps": _group_metric(runs, "fps_mean"),
            "fps_cv": _group_metric(runs, "fps_cv_pct"),
            "T_plateau": _group_metric(runs, "T_plateau_c"),
            "throttle": _group_metric(runs, "throttle_count"),
            "power": _group_metric(runs, "mean_power_w"),
            "jpf": _group_metric(runs, "j_per_frame"),
        }

    write_condition_stats(by_condition, output_dir / "condition_stats.csv")
    write_pairwise_comparisons(by_condition, output_dir / "pairwise_comparisons.csv")

    # Human-readable summary
    print_summary(by_condition, by_cond_agg)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Task 24: Bootstrap CI statistics for paper Table IV",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Outputs:\n"
            "  run_stats.csv           — raw per-run stats (15 rows)\n"
            "  condition_stats.csv     — mean ± SD + 95% CI per condition\n"
            "  pairwise_comparisons.csv — Proactive vs each baseline\n"
        ),
    )
    parser.add_argument(
        "--runs-dir",
        type=Path,
        default=Path("05_results/runs"),
        help="Directory containing run subdirectories (default: 05_results/runs)",
    )
    parser.add_argument(
        "--power-csv",
        type=Path,
        default=Path("05_results/power_analysis_30min.csv"),
        help="Power analysis CSV from analyze_powerz_30min.py (optional)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("05_results"),
        help="Output directory for statistics CSVs (default: 05_results)",
    )
    args = parser.parse_args()

    if not args.runs_dir.exists():
        log.error("Runs directory does not exist: %s", args.runs_dir.resolve())
        raise SystemExit(1)

    main(
        runs_dir=args.runs_dir,
        power_csv=args.power_csv if args.power_csv.exists() else None,
        output_dir=args.output_dir,
    )