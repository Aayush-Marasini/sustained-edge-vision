# Run Directory Manifest

Each subdirectory is one experimental run, named:
`{YYYY-MM-DD_HHMMSS}_{tag}/`

Per-run contents (whitelisted in .gitignore for tracking):
- `run_metadata.json` — config, git SHA + branch, ambient temp, hardware/software versions
- `telemetry_raw.csv` — 2 Hz raw signals from `telemetry_pipeline.py` (LFS)
- `telemetry_derived.csv` — EMA-smoothed signals and derivatives (LFS)
- `inference_log.csv` — per-frame inference outputs and latency (LFS)
- `scheduler_decisions.csv` — per-decision scheduler actions, when applicable (LFS)

Disambiguation note: directories named `scheduled_high_S0_*` are scheduled runs
whose specific scheduler (`reactive_threshold`, `proactive`, or proactive with
`dwell_seconds=0`) is recorded in `run_metadata.json` under `tags.scheduler` and
`git.branch`. Branch `ablation/no-dwell-2026-05-25` indicates the no-dwell ablation.

## Mapping to paper conditions

### Calibration (§4.5) — not in main results tables
| Directory | Purpose |
|---|---|
| `2026-04-25_234547_calib_idle_passive_run1` | Idle σ_T measurement (1 of 2) |
| `2026-04-26_135357_calib_idle_passive_run2` | Idle σ_T measurement (2 of 2) |
| `2026-04-26_151440_calib_stress_passive_run1` | Stress-step τ_thermal measurement (1 of 2) |
| `2026-04-26_155639_calib_stress_passive_run2` | Stress-step τ_thermal measurement (2 of 2) |

### Telemetry overhead (Table 2)
| Directory | Condition |
|---|---|
| `2026-04-30_192521_inferonly_fp32_rep1` | Inference-only (no telemetry) rep 1 |
| `2026-04-30_193137_inferonly_fp32_rep2` | Inference-only (no telemetry) rep 2 |
| `2026-04-30_195420_inferonly_fp32_rep3` | Inference-only (no telemetry) rep 3 |
| `2026-04-30_200412_yolov8n_fp32` | Inference + telemetry rep 1 |
| `2026-04-30_201418_yolov8n_fp32` | Inference + telemetry rep 2 |
| `2026-04-30_202222_yolov8n_fp32` | Inference + telemetry rep 3 |

### INT8 ablation (Table 1)
| Directory | Condition |
|---|---|
| `2026-05-01_201242_inferonly_int8_rep1` | INT8 rep 1 |
| `2026-05-01_201926_inferonly_int8_rep2` | INT8 rep 2 |
| `2026-05-01_203913_inferonly_int8_rep3` | INT8 rep 3 |

### DVFS profiling (Section 3.3) — 5-min profiling runs, n=3 per state
| Directory | State |
|---|---|
| `2026-05-02_020913_inferonly_fp32_1800mhz_rep1` | S1 (1800 MHz) rep 1 |
| `2026-05-02_055730_inferonly_fp32_1800mhz_rep2` | S1 rep 2 |
| `2026-05-02_060757_inferonly_fp32_1800mhz_rep3` | S1 rep 3 |
| `2026-05-02_061905_inferonly_fp32_1500mhz_rep1` | S2 (1500 MHz) rep 1 |
| `2026-05-02_062948_inferonly_fp32_1500mhz_rep2` | S2 rep 2 |
| `2026-05-02_063959_inferonly_fp32_1500mhz_rep3` | S2 rep 3 |

### Static thermal validation (Table 4, Table 5) — 30-min, n=3 per state
| Directory | Condition |
|---|---|
| `2026-05-03_012911_thermalval_S0` | Static-S0 rep 1 |
| `2026-05-04_203732_thermalval_S0` | Static-S0 rep 2 |
| `2026-05-05_011931_thermalval_S0` | Static-S0 rep 3 |
| `2026-05-03_021631_thermalval_S1` | Static-S1 rep 1 |
| `2026-05-05_015938_thermalval_S1` | Static-S1 rep 2 |
| `2026-05-05_171318_thermalval_S1` | Static-S1 rep 3 |
| `2026-05-03_053226_thermalval_S2` | Static-S2 rep 1 |
| `2026-05-05_180734_thermalval_S2` | Static-S2 rep 2 |
| `2026-05-05_200514_thermalval_S2` | Static-S2 rep 3 |

### Dynamic scheduler conditions (Table 5, Table 6) — 30-min, n=3
| Directory | Condition |
|---|---|
| `2026-05-05_213247_scheduled_high_S0_rep1` | Reactive-Threshold rep 1 |
| `2026-05-05_220944_scheduled_high_S0_rep2` | Reactive-Threshold rep 2 |
| `2026-05-05_224659_scheduled_high_S0_rep3` | Reactive-Threshold rep 3 |
| `2026-05-06_011427_scheduled_high_S0_rep1` | Proactive rep 1 |
| `2026-05-06_031811_scheduled_high_S0_rep2` | Proactive rep 2 |
| `2026-05-06_035911_scheduled_high_S0_rep3` | Proactive rep 3 |
| `2026-06-05_183203_scheduled_high_S0_rep1` | Proactive-No-Dwell rep 1 (Table 7) |
| `2026-06-05_190704_scheduled_high_S0_rep2` | Proactive-No-Dwell rep 2 |
| `2026-06-05_195204_scheduled_high_S0_rep3` | Proactive-No-Dwell rep 3 |

### Active-cooling reference (Table 5)
| Directory | Condition |
|---|---|
| `2026-05-24_182759_thermalval_S0_active_cooling` | Active-cooling reference rep 1 |
| `2026-05-24_190352_thermalval_S0_active_cooling` | Active-cooling reference rep 2 |
| `2026-05-24_193737_thermalval_S0_active_cooling` | Active-cooling reference rep 3 |

### Exploratory boundary probes (Table 10) — n=1 each
| Directory | Condition |
|---|---|
| `2026-05-06_095713_thermalval_S1_high_ambient_rep1` | Static-S1 at ~31 °C ambient |
| `2026-05-06_121351_scheduled_high_S0_high_ambient_rep1` | Proactive at ~31 °C ambient |
| `2026-05-06_150126_scheduled_high_S0_high_ambient_rep1` | Proactive at ~27 °C ambient |

### Superseded — not a paper source
| Directory | Notes |
|---|---|
| `2026-05-03_195826_scheduled_high_S0_rep1` | Pilot run for scheduler integration; uses older `proactive_thermal` config. Retained for provenance only. |