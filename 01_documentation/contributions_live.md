

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

## 3. What is not yet validated

- **Task 10 on-Pi validation.** Smoketest + calibration traces.
- **Task 11 parameter tuning.** EMA alpha and derivative stride values
  against real Pi traces; stability under idle and stress per §6.3.
- **Task 9 — Configuration Space.** Resolution/precision/frame-rate
  options enumerated and verified stable on the Pi.
- **Task 12 — Decision Policy.** The proposal §5 cost function
  `c*(t) = arg min (alpha*E + beta*(1-A) + Phi)` with hysteresis and
  dwell-time safeguards.
- **Task 13 — HCC implementation.**
- **Task 14 — System overview figure.**
- A finalized, validated contribution statement (after scheduler experiments).
- The execution of long-horizon experimental evaluations on the
  Raspberry Pi 5.
- A full comparative evaluation of the proactive scheduler against
  static and reactive baselines (Static-Max, Static-Min, reactive
  thermal-threshold, utilization-based reactive).

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