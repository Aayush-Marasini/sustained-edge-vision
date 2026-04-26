

Last Updated: April 19, 2026

## 1. What is already proven

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

## 2. What is partially implemented

- **Task 10 — Telemetry Pipeline (code landed, on-Pi validation pending).**
  `03_code/telemetry/telemetry_pipeline.py` v0.2 implements the 5 Hz
  sampler for T, V, CPU util, mem util, CPU freq, and throttle flags with
  correct bit masking. Signal source documentation in `TELEMETRY.md`.
  Still needed: 30-second on-Pi smoketest to confirm sensor access, then
  30-minute idle and 30-minute stress calibration traces.
- **Task 11 — State Representation (code landed, tuning pending).**
  `03_code/scheduler/derivatives.py` implements causal EMA + stride-k
  backward finite difference producing the proposal §4 state vector.
  Default parameters are defensible starting points; final alpha and
  stride values will be tuned against the Task 10 calibration traces
  and documented in the paper §III.B.
- **Scheduler runtime plumbing.** `scheduler_runtime.py` drains the
  telemetry queue and writes `telemetry_derived.csv` and
  `scheduler_decisions.csv`. Decision logic is a no-op placeholder.
- Conceptual design of the proactive state-aware scheduler utilizing
  multi-modal, derivative-based telemetry.
- Conceptual design and proposed trigger logic for the bounded-cost
  High-Confidence Confirmation (HCC) mechanism.
  - **[2026-04-26] Phase B: Calibration runs** — Next: two 30-minute runs at
  22 °C ambient (idle + stress-ng), passive cooling. Purpose: tune EMA alpha
  and derivative_stride for the scheduler state vector.

## 3. What is not yet validated

- Phase C: Workload video curation (moderate + realistic videos)
- Phase D: Baseline experiment runs (36-cell matrix × 3 repetitions)
- Inference runtime (run_experiment.py) — needed before baseline runs
- Scheduler logic implementation (Task 18 in WorkPlan)
- Analysis scripts and figure generation (Tasks 19/20)
- HCC mechanism implementation (proposal §4.3)

## Next action

Copy the three new Python modules and `TELEMETRY.md` to the Pi, run
`python -m telemetry.telemetry_pipeline --duration 30` as a smoketest,
and inspect the generated `run_metadata.json` for `trace_quality`.
If `completeness >= 0.99` and `sensor_failure_rate == 0`, proceed to
the 30-minute calibration runs. If not, triage the failing signal
before moving on.

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