

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

### 2026-05-01
- **S2.1 complete**: INT8 model deployed to Pi (SHA256 74ca338c, hash verified).
- **Anomaly documented**: INT8 8.69 FPS vs FP32 14.93 FPS (42% slower on Pi 5 ARM).
  Documented as paper finding — INT8 win must be measured in J/frame, not FPS.
- **Created MODELS_DEPLOYED.md** to track deployed model provenance.
- **Next**: S2.2 configuration switcher (DVFS + model swap mechanism).

### 2026-05-01 (continued)
- **INT8 baseline VERIFIED (n=3)**: mean=8.312 FPS, std=0.019, 43% slower than FP32.
- **Diagnostic complete**: INT8 model has only 6.7% I8 port utilization
  (64/948 ports). 842 FP32 ports vs 379 in FP32 model = 2.22× more FP32 work.
- **Paper finding documented**: precision choice on Pi 5 ARM is non-trivial,
  motivates scheduler's dynamic precision selection (proposal §3).
- **Standing TODO**: setup Git LFS for inference_log.csv + telemetry_raw.csv
  tracking. Defer to next hygiene pass.
- **Next**: S2.2 configuration switcher (DVFS via cpufreq-set + model swap).

### 2026-05-01 (Continued)
- **Energy analysis complete**: INT8 draws only 3.4% less power than FP32.
  INT8 NOT thermally viable on Pi 5 + OpenVINO 2026.0 ARM.
- **Architecture pivot**: DVFS (CPU freq scaling) replaces INT8 as primary
  thermal relief mechanism in Task 12 scheduler design.
- **INT8 retained as ablation**: Documents ARM quantization limitation.
  Strengthens paper empirical rigor.
- **Pareto figure deferred**: Need DVFS power measurements to populate all
  operating points before meaningful Pareto plot.
- **Next session**: Verify DVFS control on Pi, measure power at each freq
  step, then build S2.2 config switcher.

  ### 2026-05-01 (continued)
- **J/frame unit bug fixed**: was using cumulative ENERGY column with
  unknown scaling factor; now computes as P_avg / FPS. Correct values:
  FP32 = 0.559 J/frame, INT8 = 0.947 J/frame.
- **DVFS profile (200-frame quick test, FP32)**:
  2400 MHz → 15.64 FPS, 1800 MHz → 13.17 FPS, 1500 MHz → 11.58 FPS.
  Near-linear scaling confirms compute-bound workload.
- **Architecture pivot complete**: scheduler uses `scaling_max_freq` cap
  on `ondemand` governor (preserves deployment scenario per protocol).
- **HCC redesign**: original INT8↔FP32 cascade is energy-inverted on this
  hardware. New HCC operates on DVFS: low-freq to high-freq escalation on
  low-confidence detections.
- **Preliminary Pareto figure created**: `05_results/plots/pareto_fp32_int8_baselines.png`
- **Next session**: 3-rep PowerZ runs at each DVFS cap (S1: 1800 MHz,
  S2: 1500 MHz) to populate scheduler action space.

### 2026-05-02
- **DVFS power profiling complete (n=3 each, 5-min runs, passive cooling)**:
  S1@1800MHz: 12.43 FPS, 5.99W, 0.482 J/frame (−26% power, −14% J/frame vs S0)
  S2@1500MHz: 11.01 FPS, 5.33W, 0.484 J/frame (−35% power, −13% J/frame vs S0)
- **Paper flagship result confirmed**: DVFS is Pareto-dominant over INT8.
  DVFS reduces BOTH power AND energy-per-frame. INT8 reduces neither.
- **Scheduler action space locked**: {S0, S1, S2} — DVFS via scaling_max_freq.
- **Pareto figure updated**: pareto_all_configs.png with all 4 configs.
- **CHANGELOG v0.7.11** filed.
- **Next**: S2.2 config switcher code, then Task 18 baselines,
  then Task 12 scheduler decision policy.

  ### 2026-05-03
- **Thermal validation COMPLETE**: S0/S1/S2 × 30-min × n=1. Perfect data
  quality (completeness=1.0003, 0 sensor failures all runs).
- **H1 CONFIRMED**: S0 hits 87.0°C, 1910/3600 samples throttled_now=1.
- **H2 FAILED**: S1 plateaus at 81.3°C (> 80°C threshold) but
  throttled_now=0 for ALL 3600 S1 samples. Kernel never engaged throttle.
- **H3 CONFIRMED**: S2 plateaus at 73.1°C < S1's 81.3°C.
- **Paper framing revised**: primary metric is throttle event count + FPS CV,
  not temperature threshold. S0 CV=12%, S1 CV=3.4%, S2 CV=3.0%.
  Eliminating kernel throttle events IS the scheduler's value proposition.
- **FPS stability gap**: S0 std=1.576, S1 std=0.429 — 3.7× improvement.
  This maps directly to "sustained" in the paper title.
- **Figure produced**: thermal_validation_trajectories.png
- **Analysis script committed**: analyze_thermal_validation.py
- **.gitignore fixed**: run CSVs and metadata now LFS-tracked properly.
- **Next**: Task 12 scheduler decision policy implementation.
  Design point: scheduler must keep system OUT of S0 once T_dot indicates
  trajectory toward throttle. S1/S2 selection driven by T_dot magnitude.

  ### 2026-05-03 (continued)
- **σ_T measured**: 0.5835°C (idle calibration, stable window).
  3·σ_T = 1.75°C. S1/S2 gap = 8.2°C = 4.7× hysteresis floor.
- **Dimensional error corrected**: previous rationale cited σ_{T_dot}
  (°C/s) for hysteresis band (°C). Fixed in EXPERIMENTAL_PROTOCOL.md.
- **EXPERIMENTAL_PROTOCOL.md finalized**: DHT11 spec filled, Task 20
  table added, frequency selection rationale complete, throttle_raw
  sticky-flag disclosure added.
- **All 22 historical run dirs now tracked in git** via gitignore fix.
- **Repository is now clean**: no untracked paper-quality data.
- **Next**: Task 12 — scheduler decision policy implementation.

### 2026-05-03 (Continued)
- **Task 12 COMPLETE**: thermal_scheduler.py — core paper contribution.
  10/10 unit tests passing. All thresholds empirically grounded in Task 20
  data (T_plateau, rise rates) and Phase B calibration (σ_T, σ_{T_dot}).
- **scheduler_runtime.py wired**: placeholder removed, thermal_decide()
  + dvfs_control.set_state_by_name() integrated. Decisions logged with
  T, T_dot, reason for Task 28 ablation analysis.
- **Next session**: Task 21 pilot test (5-15 min run with scheduler active).
  Pull on Pi, run with sudo, verify scheduler_decisions.csv shows actual
  state transitions. Check DVFS cap changes in real time via dvfs_control.
  Then Task 18 baselines (Static-Max, Static-Min, reactive threshold).

  ### 2026-05-03 (Continued)
- **Task 21 COMPLETE**: first real scheduler decision on Pi 5 hardware.
  S0→S1 at T=75.189°C, t=167.5s. N_confirm and dwell both worked correctly.
  No throttle events. All 4 CSVs clean. DVFS restored on exit.
- **Next**: Task 18 baselines (Static-S0, Static-S1, Static-S2,
  Reactive-Threshold) × n=3 reps × 30 min = 12 runs (~6 bench hours).
  These are the comparison baselines for the main paper result.
  Then Task 22 (30-min scheduler run × n=3).