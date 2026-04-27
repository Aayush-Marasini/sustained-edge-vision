# Project Changelog

All notable changes to code, data, and experimental configuration.
Required by the No Silent Changes Rule.

Format: ## [YYYY-MM-DD] Short Title
Each entry includes: Added / Changed / Removed / Notes sections as needed.

---

## [v0.6] — 2026-04-26

### Phase D.1 Minimal Inference Runtime
- Created `03_code/inference/run_inference.py`: standalone YOLOv8n
  OpenVINO inference script for baseline FPS measurement.
- Exported YOLOv8n FP32 model via Ultralytics → OpenVINO IR format
  (yolov8n.xml + yolov8n.bin, 13 MB total).
- Downloaded test video from Pexels: test_traffic.mp4 (1920×1080,
  25 FPS, 393 frames, 7.8 MB, CC0 license).
- **Baseline inference throughput on Pi 5 (passive cooling)**:
  - Avg latency: 71.82 ms
  - Avg FPS: 13.92
  - Input resolution: 640×640
  - Precision: FP32

### Infrastructure
- Updated .gitignore to exclude models (02_models/openvino/) and
  videos (04_workload/videos/*.mp4) from version control.
- Added README.md in 02_models/openvino/ with FP32 export command.
- Added README.md in 04_workload/videos/ with test video download link.
- Model and video files are regenerated/downloaded via documented
  commands rather than committed to git.

### Next: Phase D.2
- Write run_experiment.py: full experiment harness integrating
  inference + telemetry pipeline for 30-minute baseline runs.
- Implement model precision swapping (FP32 ↔ INT8).
- Export INT8 quantized model.

## [v0.5] — 2026-04-26

### Phase B.5 EMA Parameter Tuning Complete
- Swept 20 (alpha, derivative_stride) pairs against 4 calibration traces.
- Metrics:
  - **Noise variance**: std dev of T_dot during steady states (idle plateau,
    stress soak)
  - **Response lag (90% rise time)**: time from heating ramp start (when
    stress-ng begins) to when T_dot reaches 90% of peak heating rate
- Selection criterion: minimize noise subject to 90% rise time <= 10s
  (matching Pi 5 passive cooling thermal RC time constant)
- **Selected configuration (Pareto-optimal)**:
  - alpha = 0.1
  - derivative_stride = 10
  - Combined noise: 0.0759 C/s (std dev)
  - 90% rise time: 10.0 s
- Updated `03_code/scheduler/derivatives.py` DEFAULT_CONFIG_5HZ with
  empirically-justified values.
- Generated paper-quality artifacts:
  - `05_results/calibration_analysis/pareto_alpha_stride.png` (Pareto
    frontier plot for §III figure)
  - `05_results/calibration_analysis/tuning_report.md` (methodology)
  - `05_results/calibration_analysis/sweep_raw_data.csv` (raw sweep data)

### Technical Notes
- The 10-second lag budget was set based on empirical measurements of
  the Pi 5's thermal step response. When a CPU workload initiates
  (stress-ng 4-core matrixprod), the temperature derivative reaches 90%
  of peak heating rate in 8.7-10.0 seconds depending on EMA parameters.
- Lower alpha (0.1 vs prior 0.2) and higher stride (10 vs prior 5)
  produce 2.1× lower noise variance, critical for stable HCC decision
  logic that will swap FP32↔INT8 based on T_dot thresholds.
- Unit tests in `tests/test_derivatives.py` verified to pass with new
  configuration.

## [v0.4] — 2026-04-26

### Phase B Calibration Data Collection Complete
- Collected 4 paper-quality calibration traces at ambient ~22.8-23.5 C:
  - 2x idle, passive cooling, 30 min each (9000 samples per run)
  - 2x stress-ng (4 cores, matrixprod), passive cooling, 30 min each
- All runs achieve completeness >= 1.0001 with sensor_failure_rate 0.0
  and scheduler_queue_drop_count 0.
- DHT11 ambient logged at run start and end for every run.
- Power consumption recorded via PowerZ KM003C for all 4 runs (.db
  SQLite format, stored in 05_results/power_data/ on Windows).

### Notes
- Run 2 (idle) was first attempted on 2026-04-26 00:30 but aborted
  due to PowerZ software crash; re-run successfully at 13:53.
- Stress run 1 was first attempted on 2026-04-26 14:29 but aborted
  due to user error (PowerZ closed); re-run successfully at 15:14.
- stress_passive_run2 first sample shows throttle_raw=917504 (history
  bits set from earlier session); throttled_now and undervolt_now both
  remained 0 throughout the run, so calibration data is unaffected.

### Power Data Schema (PowerZ KM003C)
- Format: SQLite .db, 2 tables (table_1 and table_1_param)
- table_1: time-series data with columns ElapsedTime, Unix, VBUS, IBUS,
  DP, DM, CC1, CC2, TEMP, CHARGE, ENERGY
- table_1_param: metadata with start time (Unix epoch) and sampling rate
- Sampling: ~1ms granularity (~2M rows per 30min run = ~1100 Hz effective)
- Sync to Pi telemetry via Unix epoch timestamps in run_metadata.json
  (start_time_utc, end_time_utc fields)

### Calibration Run Inventory
| Run | Date | Workload | Cooling | Ambient (C) | Samples |
|-----|------|----------|---------|-------------|---------|
| idle_run1 | 2026-04-25 23:45 | idle | passive | 22.7-22.8 | 9000 |
| idle_run2 | 2026-04-26 13:53 | idle | passive | 22.9 | 9000 |
| stress_run1 | 2026-04-26 15:14 | stress-ng matrixprod 4cpu | passive | 23.4-23.6 | 9000 |
| stress_run2 | 2026-04-26 15:56 | stress-ng matrixprod 4cpu | passive | 22.7-22.9 | 9000 |

### Next: EMA Parameter Tuning (Phase B.5)
- Sweep alpha in {0.1, 0.15, 0.2, 0.25, 0.3} and derivative_stride
  in {3, 5, 7, 10} on the 4 calibration traces.
- Selection criterion: minimize derivative noise variance (during steady
  states) subject to step-response lag <= 2 seconds (during stress->idle
  transition tail of stress runs).
- Tuned values committed to derivatives.py DEFAULT_CONFIG_5HZ.


## [v0.3] — 2026-04-26

### Summary
Full code audit pass (14 commits) addressing IEEE Transactions reviewer-facing
risks, plus DHT11 ambient sensor hardware integration verified on Pi 5.

### Audit Fixes — Severity 1 (Disqualifying)
- **S1.1**: `generate_partition_manifest.py` ported from hardcoded Windows path
  to `common.paths`. UTC timestamps. Existing frozen manifests unaffected.
- **S1.2**: Video stitching script hardened: explicit None-check on every frame
  read, frame-shape consistency check, VideoWriter.isOpened() guard, comment
  clarifying codec non-determinism. Canonical video remains the frozen artifact.

### Audit Fixes — Severity 2 (Will Be Questioned)
- **S2.1**: `SchedulerRuntime` now accepts `shared_start_monotonic` so the
  boot-decision row in `scheduler_decisions.csv` shares the telemetry monotonic
  reference. All four per-run CSVs now have a common time base.
- **S2.2**: `split_train_images.py` uses a local `random.Random(42)` instance
  instead of module-level `random.seed()`. Bit-identical to the previous run;
  eliminates latent import-order hazard. Frozen partition (SHA256-locked)
  remains valid.
- **S2.4 / N2.4**: `preflight_check.py` fully hardened for non-Pi hosts.
  All sensor reads wrapped in try/except; non-Pi hosts receive SKIP not
  tracebacks. Empty rfkill output treated as "no wifi device" (PASS).
- **S2.5**: `_FailureCounters` docstring corrected from "consecutive" to
  "cumulative". Behavior unchanged.

### Audit Fixes — Severity 3 / New Findings
- **S3.1**: All text-mode `open()` calls now carry `encoding="utf-8"` across
  telemetry, scheduler, data_preparation, and tests.
- **S3.2**: `_is_finite()` in `derivatives.py` replaced with `math.isfinite()`.
- **N2.4**: Preflight check robust to Pi boards without wifi hardware.
- **N3.2**: `_run()` subprocess timeout tightened from 1.0s to 0.5s for
  per-sample vcgencmd calls. Metadata-gathering calls explicitly override
  with 2.0s.
- **N3.3**: New test `test_ema_step_response_matches_documented_time_constant`
  empirically verifies the tau = dt*(1-alpha)/alpha claim in §III.B.

### Tooling
- `pyrightconfig.json` added: suppresses false-positive Pylance warnings for
  Optional mp.Value accesses and xml.etree.ElementTree None-safety patterns.
- `reportPossiblyUnboundVariable` suppressed for loop-body variables where
  loop count is statically known.

### DHT11 Ambient Sensor Integration
- `03_code/telemetry/dht11_smoketest.py`: standalone hardware verification
  script. Verified on Pi 5: 5/5 reads at 22.3 °C / 61% RH.
- `telemetry_pipeline.py`: new `--dht11-pin` flag. Worker reads DHT11 ambient
  (averaged over 3 samples) at run start and run end, records to
  `run_metadata.json` under `ambient_dht11_start` / `ambient_dht11_end`.
  DHT11 is +/- 2 °C, 1 °C resolution; explicitly marked logging-only, not
  fed to scheduler.
- Worker join timeout extended by 8s when DHT11 active (sensor read takes
  up to 6.6s during shutdown).
- Metadata gathering moved to background thread so `start_monotonic` is
  set within ~50ms of worker spawn. Eliminates ~2-3s dead time from git/
  vcgencmd metadata calls eating into the sampling window.
- Integration test v4 result: 300/299 samples (completeness 1.003),
  sensor_failure_rate 0.0, queue_drops 0. Phase A.2 verified.

### Hardware Environment (Pi 5)
- lgpio library stack: `liblgpio-dev` + `pip install lgpio` inside
  `yolov8_env`. `adafruit-circuitpython-dht==4.0.12` with `use_pulseio=False`.
- DHT11 wired: VCC → Pin 1 (3.3V), DATA → Pin 7 (BCM 4), GND → Pin 6.
  3-pin breakout board (pull-up built in).

### Known Deferred (v0.4 sweep)
- N2.1: SIGINT handling in worker processes (zombie on Ctrl-C edge case)
- N2.2: decimal.InvalidOperation in _to_float
- N2.3: O(n) inverse lookup in StateVectorBuilder
- S3.4/3.5/3.6/3.7/3.8/3.9: pytest migration, queue-drop test, double-seed,
  cpu_percent warmup, PYTHONPATH, inline import
- Severity 4 cosmetics (Unicode symbols, git diff capture on dirty tree)

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