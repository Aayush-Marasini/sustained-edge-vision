

Last Updated: April 19, 2026

## 1. What is already proven
- **[v0.6] Phase D.1 minimal inference runtime working**: YOLOv8n
  FP32 via OpenVINO achieves 13.92 FPS on Pi 5 passive cooling
  (71.82 ms avg latency). Standalone inference script ready for
  integration with telemetry pipeline.

- **[v0.5] Phase B.5 EMA parameter tuning complete**: Swept 20 (alpha,
  derivative_stride) pairs on calibration traces. Selected Pareto-optimal
  configuration (alpha=0.1, stride=10) with lowest noise (0.0759 C/s std)
  subject to 10s lag budget. Updated derivatives.py with empirically-justified
  values. Generated paper-quality Pareto plot for §III.

- **[v0.4] Phase B calibration data collected**: 4 paper-quality 30-min
  runs at 22.7-23.6 C ambient (2x idle + 2x stress-ng matrixprod, all
  passive cooling). All achieve completeness >= 1.0001 with
  sensor_failure_rate 0.0. Power consumption recorded via PowerZ KM003C
  for all 4 runs. Total data: 36000 telemetry samples + ~8M power samples.
  Ready for EMA parameter tuning.
- Established a baseline reproducible training pipeline for the YOLOv8n model.
- Empirically demonstrated the thermal throttling problem on the Raspberry
  Pi 5 under passive cooling conditions.
- Git repository fully operational on Windows and Pi.
- All frozen artifacts verified (model loads successfully on Pi 5).
- Telemetry endpoints (`vcgencmd`, `/sys/class/hwmon/`) confirmed accessible
  on the Pi.
- Signal-estimator math verified: `tests/test_derivatives.py` (8/8 pass) and
  `tests/test_scheduler_e2e.py` (end-to-end state vector produced correctly
  from mock telemetry).
- Data preparation scripts (`verify_annotations.py`, `class_distribution.py`,
  `split_train_images.py`) ported from hardcoded Windows paths to `common.paths`.
  Verified cross-platform: smoke test output matches Progress Report Table II exactly.
  - **[2026-04-26] Telemetry pipeline completeness ≥ 0.99 on Pi 5**: Integration
  test v4 confirmed 300/300 samples (completeness 1.003) at 5 Hz over 60s with
  DHT11 active. Timing fix: metadata gathering moved to background thread,
  start_monotonic set within ~50ms of worker spawn.

- **[2026-04-26] DHT11 ambient sensor integrated and verified**: Sensor wired
  (BCM 4, 3.3V), library stack installed (liblgpio-dev + adafruit-circuitpython-
  dht 4.0.12), smoketest passed 5/5 reads at 22.3 °C / 61% RH. Ambient logged
  at run start/end in run_metadata.json for every paper-quality run.

- **[2026-04-26] Full audit pass complete**: 17 commits addressing all
  Severity 1/2/3 reviewer-facing risks identified in pre-submission code audit.
  Tests stable at 9/9 (derivatives) + e2e PASSED on both Windows and Pi.

### In Flight
- **Phase D.2**: Full experiment harness (run_experiment.py) integrating
  inference + telemetry for 30-min runs.
- **Phase D.2**: Model precision swapping (FP32 ↔ INT8).

### What Is NOT Yet Started
- **Phase D**: INT8 model export and quantization.
- **Phase D**: Baseline runs (36-cell strategic matrix, 3 reps each).
- **Phase D**: HCC mechanism implementation.
- **Phase D**: PowerZ SQLite reader script.
- **Phase D**: Analysis scripts and figure generation.
- **Phase D**: Overhead profiling, HCC stability proof.
- **Phase E**: Paper drafting against IoT-J template.

## Progress log

### 2026-04-19 evening
- Task 10 smoketest succeeded on Pi 5 (150/150 samples, 0 failures).
  run_metadata.json verified: git SHA 92b86a15, governor=ondemand,
  Pi 5 Model B Rev 1.1, Python 3.13.5, psutil 7.2.2.
- Added CLI flags and preflight check so calibration runs enforce
  protocol.
- Created EXPERIMENTAL_PROTOCOL.md documenting governor/cooling/ambient
  decisions.
- CALIBRATION RUNS BLOCKED pending acquisition of ambient thermometer.
  Do NOT run paper-quality traces without it.

  ### 2026-04-19 evening (final update)
- Practice 2-minute capture completed on Pi 5.
  - 600/600 samples collected (completeness=1.0, sensor_failure_rate=0.0)
  - All preflight checks passed (git clean, governor=ondemand, WiFi blocked,
    sensors nominal)
  - Verified CLI flags (--ambient-temp-c, --tags, --cooling) work correctly
  - Run metadata: commit c229f66, temp_idle ~42°C, Pi 5 Model B Rev 1.1

**Task 10 telemetry pipeline is CODE-COMPLETE and WORKFLOW-VALIDATED.**

**BLOCKING ITEM for calibration runs:** Acquisition of ambient thermometer.
  - Required accuracy: ±0.5°C
  - Placement: within 1m of Pi, at surface height

Once thermometer arrives:
  1. Run 30-min idle calibration
  2. Run 30-min stress calibration (YOLOv8n + thermal_benchmark_30fps.mp4)
  3. Commit both run_metadata.json files
  4. Proceed to Task 11 parameter tuning (EMA alpha, derivative stride)

### 2026-04-28 (continued)
- **S1.1 optimization**: Reduced telemetry sampling from 5 Hz → 2 Hz via Nyquist analysis (20× oversampled for τ=10s).
- **Final overhead verified**: 1.48% relative (1.21 ms/frame absolute) via 3+3 paired 5-min runs at 2 Hz.
- **Phase D.2 milestone REACHED**: Scheduler overhead <3% in both latency and energy (PowerZ recorded).
- **Next**: S1.5 (EMA α recalibration for Δt=0.5s), then S1.2/S1.3/S1.4 correctness fixes, then Phase D.4 baseline runs.

### 2026-04-29
- **S1.5 complete**: EMA α/stride recalibrated for 2 Hz (DEFAULT_CONFIG_2HZ).
  9/9 unit tests pass. std ratio=1.085 on downsampled stress trace. tau_smooth preserved.
  No re-calibration runs needed — τ is a physical hardware property, not a measurement artifact.
- **S1.4 complete**: run_experiment.py run_dir now uses absolute path from __file__.
  Works from any CWD. Fixed sampling-rate-hz default to 2.0.
- **Next**: S2.1 (INT8 model export via NNCF), then Task 12 (scheduler decision policy).

### 2026-04-30
- **Deployed correct RDD model to Pi**: SHA256 0de2334a (was wrong COCO model since 04-26).
- **Deployed correct workload video**: thermal_benchmark_30fps.mp4 (961 disjoint frames, worst-case).
- **Re-verified overhead**: 1.90% relative / 1.33 ms/frame absolute (n=3+3).
- **Phase D.2 milestone REACHED** with correct artifacts.
- **Next**: S2.1 INT8 deployment, then S2.2 config switcher, then Task 18 baselines.