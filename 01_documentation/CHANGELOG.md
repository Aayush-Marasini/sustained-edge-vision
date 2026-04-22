# Project Changelog

All notable changes to code, data, and experimental configuration.
Required by the No Silent Changes Rule.

Format: ## [YYYY-MM-DD] Short Title
Each entry includes: Added / Changed / Removed / Notes sections as needed.

---
## [2026-04-21] Document OpenVINO Export Process

### Added
- `03_code/data_preparation/convert_baseline_to_openvino.py` — Documentation
  of the exact export commands used to generate frozen FP32/FP16/INT8 models
  on April 1, 2026. Records Ultralytics 8.4.7, OpenVINO 2026.0.0, NNCF 3.0.0,
  Python 3.13.7, and full validation-set calibration for INT8.
- `03_code/data_preparation/test_openvino_equivalence.py` — Functional
  equivalence test (not part of frozen artifacts; local verification only).

### Notes
- Models were converted once on April 1, 2026 and frozen with SHA256 hashes.
  Script is documentation-only per Baseline Freeze Rule.
- INT8 calibration used full validation set (481 images, fraction=1.0) via
  NNCF post-training quantization.
- Satisfies WorkPlan §1.1 Reproducibility Rule for model export step.

## [2026-04-19] Refactor: Port data_preparation scripts to common.paths

### Changed
- `03_code/data_preparation/class_distribution.py`: replaced hardcoded
  LABEL_DIR with PROCESSED_YOLO_DIR from common.paths.
- `03_code/data_preparation/verify_annotations.py`: replaced hardcoded
  BASE_DIR with PROCESSED_YOLO_DIR and RESULTS_DIR from common.paths.
- `03_code/data_preparation/split_train_images.py`: replaced all four
  hardcoded path constants with RAW_DATASET_DIR, PROCESSED_YOLO_DIR,
  VIDEOS_DIR from common.paths.
- All three scripts: sys.path inserts parents[1] (03_code/) so the
  common package is resolvable from any working directory.

### Notes
- No Silent Changes Rule: no logic changes. RANDOM_SEED=42, split ratios
  (70/10/20), CLASSES list, and all file operations are identical.
  No data, weights, or metrics were modified.
- Smoke test: class_distribution.py confirmed correct output
  (D00=61.51%, D10=29.70%, D20=7.61%, D40=1.17%) matching Progress Report.
- Scripts now run on Windows (dev) and Linux/Pi (deploy) without
  modification. RESEARCH_PROJECT_ROOT env-var override also supported.
  
## [2026-04-18] Phase 2 Kickoff: Baseline Freeze and Restructure

### Added
- 00_frozen_artifacts/ directory containing:
  - yolov8n_baseline_seed42/weights/ (best.pt, last.pt, OpenVINO FP16/FP32/INT8)
  - yolov8n_baseline_seed42/args.yaml, data.yaml
  - yolov8n_baseline_seed42/training_outputs/ (curves, confusion matrices, batch images)
  - benchmark_workloads/thermal_benchmark_30fps.mp4
  - dataset_manifests/ (train, val, test partition SHA256 hashes)
  - SHA256SUMS.txt and MANIFEST.md
- 03_code/common/paths.py - cross-platform path management (single source of truth)
- 03_code/data_preparation/generate_partition_manifest.py
- 03_code/ subdirectories: telemetry/, scheduler/, experiments/,
  experiments/baselines/, analysis/, common/, data_preparation/
- __init__.py in every Python package directory
- 05_results/runs/README.md - experiment run directory naming convention
- .gitignore and .gitattributes (Git LFS for .pt, .bin, .xml, .mp4)

### Changed
- Moved frozen prep scripts (split_train_images.py, verify_annotations.py,
  class_distribution.py) from 03_code/baseline_scripts/ to 03_code/data_preparation/
- Moved run_experiment.py to 03_code/experiments/
- Renamed old log_telemetry.py to log_telemetry_DEPRECATED.py (moved to 03_code/telemetry/)
- Moved stray pretrained checkpoints (yolov8n.pt, yolo26n.pt) to archive/
  (these were Ultralytics auto-downloaded pretrained weights, not the baseline model)
- Moved yolo_usa_split.zip (284 MB dataset backup) to archive/

### Removed
- 03_code/baseline_scripts/ (contents redistributed by role)
- 03_code/scheduler_logic/ (redundant with scheduler/)
- Stray data.yaml at project root (leftover from a miscopied command)
- 01_documentation/proposal/paper (AutoRecovered).docx (Word crash-recovery file)

### Notes
- Read-only attributes set on all files in 00_frozen_artifacts/ via attrib +R /S
- Baseline model identity verified by SHA256 hashes (see 00_frozen_artifacts/SHA256SUMS.txt)
- Initial Git repository created with LFS enabled for large binaries
- paths.py tested on Windows; Linux/Pi logic present but untested until deployment
- 9 binary files totaling ~110 MB tracked via LFS, not native git storage


## [2026-04-19] Task 10: Telemetry Pipeline v0.2

### Added
- `03_code/telemetry/telemetry_pipeline.py` — 5 Hz synchronized
  telemetry logger. Single producer, two consumers (inline CSV writer
  + optional `multiprocessing.Queue` for live scheduler consumption).
  Writes `telemetry_raw.csv` and `run_metadata.json` per run directory.
- `03_code/telemetry/TELEMETRY.md` — per-signal source documentation
  required by WorkPlan §6.2, including full Raspberry Pi throttle bit
  layout reference.
- `03_code/scheduler/derivatives.py` — `SignalEstimator` (causal EMA +
  stride-k backward finite difference) and `StateVectorBuilder`
  producing the formal state vector s(t) from proposal_v2.pdf §4.
  Per-signal defaults for 5 Hz sampling; tunable via `DEFAULT_CONFIG_5HZ`.
- `03_code/scheduler/scheduler_runtime.py` — consumer plumbing that
  drains the telemetry queue, computes the state vector, and writes
  `telemetry_derived.csv` + `scheduler_decisions.csv`. Decision logic
  is currently a no-op placeholder; Task 12 will implement the real
  policy.
- `tests/test_derivatives.py` — 8 unit tests for the estimator
  (EMA convergence, linear-ramp derivative correctness, None/NaN
  handling, invalid-alpha guards, state-vector shape). All passing.
- `tests/test_scheduler_e2e.py` — end-to-end integration test using
  mock telemetry, verifies both output CSVs are produced and T_dot
  tracks a known-positive thermal ramp.

### Fixed
- **Throttle bit mask (SEVERITY 1 BUG).** Previous draft used `0x1`
  (under-voltage) and labeled it as "currently throttled". Corrected
  to `0x4` (bit 2) which is the actual thermal-throttling flag per
  Raspberry Pi documentation. `throttle_raw` is now logged as an
  integer so any bit can be reconstructed in post-processing. Any
  throttle-based metric computed from logs predating this fix is
  invalid. No such logs are known to exist in the repository.
- Sensor-failure fallback changed from `0.0` to `None` (empty CSV
  cell). Previously, a failed thermal read wrote `0.0` which would
  produce a spurious ~60 °C drop and a large negative `T_dot` in
  Task 11. `None` propagates through the derivative estimator
  correctly (carries forward last smoothed value, does not poison EMA).
- Sampling loop replaced drift-prone `sleep(interval - elapsed)` with
  absolute-deadline wait against `start_monotonic + i * interval`.
  Over a 90-minute run at 5 Hz, the previous loop could lose tens of
  samples to accumulated drift.
- `except:` replaced with `except Exception:` so Ctrl-C and process
  termination work normally.
- `psutil.cpu_percent(interval=None)` warm-up call added before the
  main loop so the first sample is not spuriously 0.

### Changed
- `run_metadata.json` schema version bumped to `"0.2"`. Now includes
  hardware (Pi model, firmware, kernel, cpu_governor, arm_freq_config),
  software (Python, platform, package versions), git (sha, branch,
  dirty flag), seed, and post-run trace quality metrics
  (completeness, sensor_failure_rate, queue_drop_count).
- Metadata now written at run start as `run_metadata.partial.json` and
  atomically renamed at clean shutdown, so a crashed run still has
  session context.
- CSV columns expanded from 8 to 10: added `throttle_raw` (int),
  renamed `throttled` to `throttled_now`, added `undervolt_now`.

### Removed
- `03_code/telemetry/log_telemetry_DEPRECATED.py` stays deprecated;
  no further changes needed.

### Notes
- All unit tests and the end-to-end integration test pass in the
  dev container (non-Pi host). On-Pi validation pending: a 30-second
  smoketest followed by the Task 10 calibration runs
  (30-minute idle + 30-minute stress) produces the traces that
  Task 11 will use to tune derivative alpha/stride.
- The scheduler decision logic in `scheduler_runtime.py` is a
  placeholder that never changes configuration. Task 12 (§6.4)
  replaces `_decide_config_placeholder()` with the proposal §5 cost
  function plus hysteresis and dwell-time safeguards.

---

## Template for Future Entries

## [YYYY-MM-DD] Title

### Added
- ...

### Changed
- ...

### Removed
- ...

### Notes
- ...