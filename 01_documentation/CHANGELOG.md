# Project Changelog

All notable changes to code, data, and experimental configuration.
Required by the No Silent Changes Rule.

Format: ## [YYYY-MM-DD] Short Title
Each entry includes: Added / Changed / Removed / Notes sections as needed.

---
## v0.11.0 — 2026-05-24
- ADDED: Active-cooling oracle baseline (Static-S0 with Pi 5 official fan, n=3)
  - FPS: 14.52±0.01, throttle events: 0, cooling_condition: active_fan
  - run_metadata.json cooling_condition corrected from "passive" to "active_fan"
  - Paper use: upper-bound oracle for scheduler efficiency comparison
  

## [v0.9.7] — 2026-05-06

### Task 19 COMPLETE: Deployed OpenVINO mAP50 measured

**Result:** mAP50 = 0.538 (deployed) vs 0.533 (Ultralytics training)
Delta = +0.005 — within measurement noise. Export validated.

**Method:** 481 val images, Pi 5, OpenVINO 2026.0.0, FP32.
NMS applied (IoU threshold=0.45) before PR curve computation.
11-point interpolated AP per class.

**Per-class:** D00=0.662, D10=0.639, D20=0.593, D40=0.258

**Bug fixed:** measure_deployed_map.py was missing NMS, causing
0.192 mAP on first run (duplicate detections inflating FP count).
Fixed by adding per-class NMS before GT matching.

**Paper implication:** mAP50=0.533 (training) is conservative.
Deployed model achieves 0.538. Paper will cite 0.538 as the
deployed model metric. Model output is frequency-invariant —
one measurement applies to all scheduler conditions.


## [v0.9.6] — 2026-05-06

### Task 23 COMPLETE: Full results analysis — all 15 paper runs

**All baseline campaign runs complete and analyzed.**

#### Telemetry results (analyze_all_conditions.py)

| Condition          | N | FPS mean | FPS std | FPS CV | Throttle/30min | T_plateau (°C) |
|--------------------|---|----------|---------|--------|----------------|----------------|
| Static-S0          | 3 | 13.211   | 1.567   | 11.9%  | 1823±81        | 84.8±0.0       |
| Static-S1          | 3 | 12.820   | 0.431   |  3.4%  | 0±0            | 79.8±0.7       |
| Static-S2          | 3 | 11.338   | 0.353   |  3.1%  | 0±0            | 73.2±0.3       |
| Reactive-Threshold | 3 | 11.818   | 1.442   | 12.2%  | 0±0            | 73.7±0.6       |
| Proactive (Ours)   | 3 | 12.588   | 1.285   | 10.2%  | 0±0            | 74.5±1.1       |

Proactive time-at-state: S0=174s (9.7%), S1=970s (53.9%), S2=656s (36.4%)
Reactive time-at-state: S0=193s (10.7%), S1=0s (0%), S2=1606s (89.3%)

#### PowerZ energy results (analyze_powerz_30min.py)

| Condition          | Power (W)      | J/frame        | FPS    |
|--------------------|----------------|----------------|--------|
| Static-S0          | 8.241±0.024    | 0.633±0.005    | 13.024 |
| Static-S1          | 6.035±0.050    | 0.471±0.005    | 12.804 |
| Static-S2          | 5.377±0.028    | 0.475±0.003    | 11.326 |
| Reactive-Threshold | 6.957±0.077    | 0.596±0.007    | 11.674 |
| Proactive (Ours)   | 7.052±0.035    | 0.566±0.005    | 12.464 |

PowerZ alignment: end-time anchoring used (Windows clock offset ~3600-4100s
from Pi UTC). Verified correct via power step detection (idle→inference
transition visible at window boundary). 300,000 samples per 300s window.

#### Key results for paper

- Proactive vs Reactive: +6.8% FPS, -5.1% J/frame — strict dominance
- Proactive vs Static-S0: zero throttle events vs 1823/run, -10.6% J/frame
- Proactive vs Static-S1: +2.8% FPS, +20.2% J/frame — throughput/energy tradeoff
- Reactive permanently locked in S2 (89.3% of run); proactive used S1 53.9%
- FPS CV for dynamic schedulers reflects state transitions, not instability

#### Figures generated
- 05_results/plots/pareto_frontier.png
- 05_results/plots/int8_vs_fp32_comparison.png
- 05_results/plots/scheduler_decision_timeline.png
- 05_results/plots/thermal_validation_trajectories.png (existing)

#### Framing decision (No Silent Changes Rule)
Paper claim revised from "proactive dominates" to "proactive strictly
dominates reactive baseline; does not claim global optimality vs static
configurations." Honest framing: scheduler unlocks intermediate DVFS
states unavailable to reactive control, yielding superior operating
point among thermally safe dynamic policies.

#### Pending before submission
- Task 19: mAP measurement on deployed OpenVINO model (val set, 481 images)
- LaTeX Table IV: populate all cells from results above
- Paper writing: Introduction, Related Work, Results prose
- Figure 5 (scheduler decision timeline): use proactive rep1 not pilot run

## [v0.9.5] — 2026-05-06

### Task 22 Session 4: Proactive scheduler n=3 COMPLETE

**B11:** 2026-05-06_011427_scheduled_high_S0_rep1 — 23.4°C ambient
  Decisions: S0→S1 t=183s (T=75.3°C), S1→S2 t=909s (T=79.0°C),
             S2→S1 recovery t=1681s (T=71.0°C)

**B12:** 2026-05-06_031811_scheduled_high_S0_rep2 — 23.8°C ambient
  Decisions: S0→S1 t=165s (T=75.4°C), S1→S2 t=1110s (T=79.1°C)

**B13:** 2026-05-06_035911_scheduled_high_S0_rep3 — 23.8°C ambient
  Decisions: S0→S1 t=174s (T=75.1°C), S1→S2 t=1293s (T=79.1°C)

All: 3601 samples, completeness=1.0003, 0 throttle events, WiFi blocked,
DVFS restored S0 on exit.

**Directory rename:** 2026-05-06_031811 was mislabeled rep1 at run time.
Renamed to rep2. run_metadata.json rep field corrected. No data affected.
Documented per No Silent Changes Rule.

**PowerZ files:** 2026-05-05_proactive_rep{1,2,3}.db confirmed in power_data/

**Core result confirmed:** Proactive scheduler used S1 in all 3 reps
before escalating to S2. Time at S1 per rep: 726s, 945s, 1119s.
Reactive baseline: 0s at S1, permanently in S2 from t~190s.

**ALL BASELINE CAMPAIGN RUNS COMPLETE.**
Static S0/S1/S2 n=3, Reactive-Threshold n=3, Proactive n=3 = 15 runs total.
Next: PowerZ analysis, full results table, paper writing.

## [v0.9.3] — 2026-05-05

### Task 18 Session 2: Static baselines complete — S1 n=3, S2 n=3

**B5:** 2026-05-05_171318_thermalval_S1 — 22.3°C ambient
**B6:** 2026-05-05_180734_thermalval_S2 — 23.0°C ambient
**B7:** 2026-05-05_200514_thermalval_S2 — 23.4°C ambient
All: 1800s, passive, WiFi blocked, 2Hz, completeness=1.0003.

Note: B5 (S1 rep3) shows throttle_raw=0 at t=0 — clean start,
no preceding S0 run in this session. throttled_now=0 throughout
as expected. throttle_raw sticky flag status is irrelevant to
paper metrics (throttled_now is the sole active-throttle signal).

**All static baselines now complete: S0 n=3, S1 n=3, S2 n=3.**
Full multi-rep analysis pending (paste from analyze_thermal_validation.py).
Next: Session 3 (Reactive-Threshold x3), Session 4 (Proactive x3).

## [v0.9.2] — 2026-05-04

### Task 18 Session 1: Static baselines S0 (n=3 complete), S1 (n=2/3)

**B2:** 2026-05-04_203732_thermalval_S0 — 23.0°C ambient
**B3:** 2026-05-05_011931_thermalval_S0 — 23.8°C ambient
**B4:** 2026-05-05_015938_thermalval_S1 — 24.1°C ambient
All: 1800s, passive, WiFi blocked, 2Hz, completeness=1.0003.

**Multi-rep consistency check (S0 n=3):**
  T_peak: 86.8 ± 0.2°C — excellent consistency
  T_plateau: 84.8 ± 0.0°C — essentially identical across reps
  N_throttle: 1823 mean — consistent with rep1 (1910)
  FPS_mean: 13.211, FPS_std: 1.567, CV: 11.9%

**Multi-rep consistency check (S1 n=2):**
  T_plateau: 80.4 ± 0.9°C — acceptable, within  variance
  N_throttle: 0 both reps
  FPS_mean: 12.828, FPS_std: 0.426, CV: 3.3%

**Aborted run:** 2026-05-04_212600_thermalval_S0 deleted. No damage.
**Remaining:** S1 rep3, S2 reps 2+3, Reactive x3, Proactive x3.

## [v0.9.1] — 2026-05-03

### Task 21 COMPLETE: Pilot scheduled run

**Run:** 2026-05-03_195826_scheduled_high_S0_rep1
**Duration:** 600s (10 min pilot)
**Workload:** high-stress (thermal_benchmark_30fps.mp4)
**Cooling:** passive, 22.7°C ambient

**First real scheduler decision on hardware:**
- t=167.5s: S0→S1, reason=escalate_reactive_T, T=75.189°C, T_dot=0.243°C/s
- N_confirm correctly held at t=165.5s when T_dot briefly went negative
- Dwell held S1 for 20s while T fell from 75.2→72°C
- End-of-run: T=77.65°C at S1, throttled_now=0 for entire run

**FPS analysis:**
- ~167s at S0 (~14.58 FPS) + ~432s at S1 (~12.43 FPS) = ~13.0 FPS avg
- Measured: 7602 frames / 600s = 12.67 FPS (matches prediction ✓)

**System behavior confirmed:**
- All 4 CSVs written (telemetry_raw, telemetry_derived, scheduler_decisions,
  inference_log)
- DVFS cap restored to S0 (2400000 kHz) on clean exit ✓
- chown applied post-run (no git pull permission errors)

**Note:** T=77.65°C at t=600s is not the S1 plateau.
Full 30-min Task 22 runs will show true S1 plateau (~81.3°C).

### Bug fixes in this version
- thermal_scheduler.py: last_switch_monotonic=0.0 (was time.monotonic())
- thermal_scheduler.py: now_monotonic fallback raises ValueError
- run_scheduled_experiment.py: new harness with Queue created in parent

### Protocol deviation — pilot run 2026-05-03_195826_scheduled_high_S0_rep1
WiFi was not blocked (rfkill block wifi omitted before run).
This is a Task 21 pilot run only — not used in any paper table or figure.
Scientific conclusion of Task 21 (end-to-end wiring verification) is
unaffected: all 4 CSVs written, first real DVFS decision confirmed at
T=75.189°C t=167.5s, DVFS restored on exit.
All Task 22 paper-quality runs will enforce WiFi block per protocol.

## [v0.9.0] — 2026-05-03

### Task 12 COMPLETE: Proactive thermal scheduler decision policy

**Added:** `03_code/scheduler/thermal_scheduler.py`
Core paper contribution. Implements the proactive, state-aware DVFS
scheduler replacing `_decide_config_placeholder()`.

**Policy design (all values empirically grounded):**

| Parameter | Value | Derivation |
|-----------|-------|------------|
| T_escalate_S0→S1 | 75.0°C | S0 T_plateau=84.9°C − 9.9°C headroom (>τ_thermal at 5.83°C/min rise) |
| T_escalate_S1→S2 | 79.0°C | S1 T_plateau=81.3°C − 2.3°C headroom (~40s at 3.39°C/min rise) |
| T_recover_S2→S1 | 71.0°C | Gap from T_esc_S1S2 = 8.0°C = 13.7×σ_T |
| T_recover_S1→S0 | 68.0°C | Gap from T_esc_S0S1 = 7.0°C = 12.0×σ_T |
| T_dot_proactive | 0.5°C/s | 6.6×σ_{T_dot}=0.0759°C/s — strong rising signal only |
| T_dot_concern_floor | 65.0°C | Below this, T_dot cannot reach threshold within τ_thermal |
| dwell_time_s | 20.0s | 2×τ_thermal=10s — heatsink response margin |
| n_confirm | 3 samples | 1.5s at 2 Hz — rejects sub-second transients |

**Safety invariants (never violated):**
1. ΔT_hyst > 3·σ_T = 1.75°C for all threshold pairs ✓
2. dwell_time_s = 20s ≥ 2·τ_thermal ✓
3. N_confirm = 3 before any escalation ✓
4. One step at a time: S0→S1→S2, never skip ✓
5. Recovery also requires N_confirm (no premature step-up) ✓

**Key distinction (σ_T vs σ_{T_dot}):**
- σ_T = 0.5835°C governs hysteresis band width (absolute °C)
- σ_{T_dot} = 0.0759°C/s governs proactive trigger threshold (°C/s)
These are dimensionally distinct; mixing them is a measurement error.

**Tests:** 10/10 passing (`tests/test_thermal_scheduler.py`)

**scheduler_runtime.py:** wired to thermal_scheduler.decide() + dvfs_control.
_decide_config_placeholder() removed. scheduler_decisions.csv schema updated:
{dvfs_state, reason, T, T_dot, throttled_now} replaces {config_resolution,
config_precision, config_fps_cap}.

**No Silent Changes Rule:** scheduler_decisions.csv column schema changed.
Any analysis script reading old columns will break — update before running
Task 21 pilot tests. Old placeholder runs have no paper-quality decision data.

## [v0.8.2] — 2026-05-03

### Corrected frequency selection rationale and EXPERIMENTAL_PROTOCOL.md update

**Correction (No Silent Changes Rule):** Previous draft of frequency
selection rationale (generated during v0.8.1 session) contained a
dimensional error: cited σ_{T_dot} = 0.0759°C/s (derivative noise,
units °C/s) to justify hysteresis band width (units °C). These are
dimensionally distinct quantities with distinct roles in the control law.

**Corrected values (measured from Phase B calibration):**
- σ_T = 0.5835°C (absolute temperature sensor noise, idle run,
  stable window t > 120s, 2026-04-25_234547_calib_idle_passive_run1)
- 3·σ_T = 1.75°C (minimum hysteresis band floor)
- S1/S2 plateau gap = 8.2°C = 4.7× above floor ✓
- σ_{T_dot} = 0.0759°C/s (derivative noise) → governs proactive
  trigger threshold only, not hysteresis width

**Note on stress run σ_T:** σ_T computed from stress run = 5.1492°C.
This is NOT sensor noise — it is thermal signal variance from a
rising temperature trajectory. The correct noise baseline is the
idle run stable window (σ_T = 0.5835°C).

**EXPERIMENTAL_PROTOCOL.md changes:**
- Replaced [INSERT THERMOMETER MODEL] placeholder with DHT11 spec
- Added empirical Task 20 data to configuration space table
- Added "Frequency State Selection Rationale" section with corrected
  σ_T-based hysteresis argument
- Added "Throttle Detection" section documenting throttle_raw vs
  throttled_now distinction and sticky-flag disclosure
- No changes to any experimental decisions — documentation only

## [v0.8.1] — 2026-05-03

### S2.3: 30-min thermal validation COMPLETE — Task 20 configuration profiling

**Protocol:** FP32, thermal_benchmark_30fps.mp4, passive cooling, ondemand,
2 Hz telemetry, 23.0°C ambient (DHT11 5/5 reads), PowerZ concurrent.
All runs: completeness=1.0003, sensor_failure_rate=0.0.

**Results:**

| State | T_start | T_peak | T_plateau | throttled_now | N_throttle | Rise°C/min | FPS_mean | FPS_std | FPS_CV |
|-------|---------|--------|-----------|---------------|------------|------------|----------|---------|--------|
| S0 | 48.4°C | 87.0°C | 84.9°C | **True** | 1910 | 5.827 | 13.152 | 1.576 | 12.0% |
| S1 | 49.5°C | 82.6°C | 81.3°C | False | 0 | 3.390 | 12.780 | 0.429 | 3.4% |
| S2 | 46.2°C | 74.3°C | 73.1°C | False | 0 | 2.785 | 11.358 | 0.339 | 3.0% |

**PowerZ files:** 2026-05-03_thermalval_S{0,1,2}_rep1.db (not in LFS)

**Hypothesis verdicts:**
- H1 (S0 throttles): CONFIRMED — T_peak=87.0°C, 1910/3600 samples throttled_now=1
- H2 (S1 plateaus < 80°C): FAILED — T_plateau=81.3°C (above 80°C threshold)
- H3 (S2 plateau < S1): CONFIRMED — T_plateau=73.1°C < 81.3°C

**Design decision — H2 failure resolution (No Silent Changes Rule):**
Paper framing revised from temperature-threshold-based to
throttle-event-and-stability-based. Rationale:
- S1 `throttled_now=0` for 100% of samples: kernel never engaged throttle.
- S0 `throttled_now=1` for 53% of samples (1910/3600): severe instability.
- FPS CV: S0=12.0%, S1=3.4%, S2=3.0% — stability gap is the real result.
- BCM2712 ARM trip point is ~85°C; Pi 5 throttle manifests as FPS jitter
  before `throttled_now` engages. S1 at 81.3°C is in the danger zone but
  not over the kernel trip point.
- New primary metric: throttle event count + FPS coefficient of variation.
- New scheduler objective: prevent `throttled_now=1` events (0 in S1/S2
  vs 1910 in S0), not maintain T < 80°C.
- S1 reclassified as "thermal caution zone": acceptable for operation,
  but T_dot signal should escalate to S2 if trajectory continues rising.
- This framing is more honest and stronger: the stability improvement
  (CV 12%→3.4%) is a direct consequence of eliminating throttle events.

**throttle_raw sticky flag disclosure:**
S1/S2 t=0 throttle_raw=0xE0000 (bits 17-19 set) is a historical flag
from S0 run. throttled_now (bit 0) = 0 for all S1/S2 samples.
throttled_now is the sole active-throttle signal used in all analysis.

**Paper contributions locked:**
- §V.A Figure: T(t) + FPS(t) trajectories for S0/S1/S2 over 30 min
  → `05_results/plots/thermal_validation_trajectories.png`
- §V.A Table: T_plateau, throttle events, FPS_mean ± std per state
- §V.B: FPS CV as primary stability metric
- §VI scheduler objective: minimize throttle events, not minimize temperature

## [v0.7.11] — 2026-05-02

### S2.2: DVFS power profiling COMPLETE — paper flagship result

**Method:** 3-rep × 5-min inference-only runs per configuration.
FP32 model, thermal_benchmark_30fps.mp4, passive cooling.
DVFS via scaling_max_freq cap on ondemand governor.

| Config         | FPS          | Power (W)    | J/frame      | vs S0 power | vs S0 J/frame |
|----------------|--------------|--------------|--------------|-------------|---------------|
| S0 FP32@2400   | 14.582±0.019 | 8.149±0.053  | 0.559±0.004  | 1.000×      | 1.000×        |
| INT8@2400      | 8.315±0.019  | 7.872±0.017  | 0.947±0.001  | 0.966×      | 1.694×        |
| S1 FP32@1800   | 12.432±0.015 | 5.996±0.056  | 0.482±0.004  | 0.736×      | 0.863×        |
| S2 FP32@1500   | 11.012±0.016 | 5.329±0.017  | 0.484±0.002  | 0.654×      | 0.866×        |

**Key findings:**
1. DVFS (S1, S2) is THERMALLY VIABLE — 26-35% power reduction
2. DVFS (S1, S2) is ENERGY EFFICIENT — 13-14% better J/frame than S0
3. INT8 is NOT thermally viable — only 3.4% power reduction (within noise)
4. INT8 uses 69.4% MORE energy per frame than S0
5. S1 and S2 are PARETO IMPROVEMENTS over S0 (lower power AND better J/frame)

**Architecture confirmed:**
- Scheduler action space: {S0, S1, S2} — DVFS only, INT8 is ablation
- Mechanism: echo <freq> | sudo tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_max_freq
- Deployment scenario preserved: ondemand governor remains active

**Paper contribution (§V.B):**
FP32@1800MHz achieves 12.43 FPS while drawing only 5.99W — 26% less power
than the maximum-throughput configuration. This creates a viable thermal
management lever without INT8's catastrophic 43% throughput penalty.

**Paper contribution (§VI.C ablation):**
INT8 quantization on Pi 5/OpenVINO 2026.0/Cortex-A76 increases energy
per frame by 69.4% despite 43% slower inference. Root cause: 2.22× more
FP32 operations due to Convert/dequant overhead at quantized layer
boundaries (confirmed via IR graph analysis: 64 I8 ports vs 842 FP32
ports). This proves precision-cascade HCC as originally designed would
INCREASE energy burden on this hardware stack.

## [v0.7.10] — 2026-05-01

### S2.1 final: Energy verified, DVFS profiled, J/frame units corrected

**J/frame unit fix:** Original analysis used PowerZ ENERGY column directly,
which has scaling factor != Joules. Corrected to compute as P_avg / FPS.

| Model | FPS    | Power (W)     | J/frame |
|-------|--------|---------------|---------|
| FP32  | 14.582 | 8.149 ± 0.053 | 0.559   |
| INT8  | 8.315  | 7.872 ± 0.017 | 0.947   |
| Ratio | 0.570× | 0.966×        | 1.694×  |

**Critical finding (CONFIRMED):** INT8 not thermally viable.
- INT8 draws only 3.4% less power (within noise margin)
- INT8 uses 69.4% more energy per frame
- Root cause: 2.22× more FP32 ops in INT8 graph (Convert/dequant overhead)
- Power equation P ∝ C·V²·f: changing precision doesn't change V or f,
  so power stays constant

### DVFS frequency profiling (200-frame quick test, FP32, ondemand)

| Frequency | Latency  | FPS    | FPS/freq linearity |
|-----------|----------|--------|--------------------|
| 2400 MHz  | 63.94 ms | 15.64  | 1.000× (baseline)  |
| 1800 MHz  | 75.93 ms | 13.17  | 0.842× (ratio 0.75)|
| 1500 MHz  | 86.32 ms | 11.58  | 0.740× (ratio 0.625)|

FPS scales near-linearly with frequency → workload is compute-bound.
This is a CONTINUOUS control knob (vs INT8's discrete cliff).

### Architecture decision

**DVFS is the primary thermal control mechanism.** Scheduler implementation
uses `scaling_max_freq` to cap `ondemand` governor (preserves deployment
scenario per EXPERIMENTAL_PROTOCOL.md).

Configuration space:
- S0 (Max): cap 2400 MHz, ~15.6 FPS, max thermal
- S1 (Med): cap 1800 MHz, ~13.2 FPS, moderate thermal
- S2 (Low): cap 1500 MHz, ~11.6 FPS, minimum thermal

INT8 retained as ablation in §V demonstrating ARM quantization limitation.

### HCC mechanism implication

Per proposal §6, HCC was designed to escalate INT8 → FP32 on low-confidence
detections, with bounded cost ΔE_HCC = N_HCC(E_high - E_low).

**Energy data inverts the inequality:** E_INT8 (0.947 J/frame) > E_FP32
(0.559 J/frame). HCC as originally designed would stack the two MOST
expensive operations.

**Resolution:** HCC reframed in §VI.C as ablation showing why precision-
cascade is a parasitic cost on unaccelerated edge CPUs. New HCC mechanism
operates on DVFS instead: temporarily boost from low-freq to high-freq
when low-confidence detection occurs.

## [v0.7.9] — 2026-05-01

### S2.1 ENERGY ANALYSIS COMPLETE — Critical finding for Task 12

**Method:** PowerZ 1kSPS recordings aligned to inference window
(skip 10s model load, use exact 300s inference window).

| Model | FPS    | Power (W)      | J/frame   |
|-------|--------|----------------|-----------|
| FP32  | 14.582 | 8.149 ± 0.053  | 0.000156  |
| INT8  | 8.315  | 7.872 ± 0.017  | 0.000263  |
| Ratio | 0.570× | 0.966×         | 1.694×    |

**Critical finding: INT8 is NOT thermally viable on Pi 5 + OpenVINO 2026.0.**
- INT8 draws only 3.4% less power than FP32 (within noise margin)
- INT8 uses 69.4% more energy per frame
- Root cause: 2.22× more FP32 ops in INT8 graph (Convert/dequant ops dominate)

**Architecture implication:**
- INT8 CANNOT serve as thermal relief valve (original Task 12 design)
- DVFS (CPU frequency scaling) becomes primary cooling mechanism
- INT8 retained as ablation study documenting ARM quantization limitations

**Paper strengthening:** This negative result is more publishable than a
trivial "INT8 = faster + cheaper" finding. It demonstrates deep understanding
of hardware-software interaction on edge ARM platforms.

## [v0.7.8] — 2026-05-01

### S2.1 verified: INT8 baseline FPS confirmed at 8.312 (43% slower than FP32)

**Method:** 3-rep paired benchmark, 5-min runs, passive cooling, ambient 22.5-23.6°C,
no telemetry overhead, thermal_benchmark_30fps.mp4 worst-case workload.

| Model | mean FPS | std | latency | INT8 ratio |
|-------|----------|-----|---------|------------|
| FP32 | 14.579 | 0.019 | 68.59 ms/frame | 1.000× |
| INT8 | 8.312 | 0.019 | 120.31 ms/frame | 0.570× |

**Both std=0.019 → pipeline is deterministic. INT8 slowdown is real, not an artifact.**

### Root cause analysis (OpenVINO IR graph diagnostic)

| Model | FP32 ports | I8 ports | I8 utilization |
|-------|-----------|----------|----------------|
| FP32 | 379 | 0 | 0% |
| INT8 | 842 | 64 | 6.7% |

The INT8 model has **2.22× MORE FP32 ports** than the unquantized FP32 model.
NNCF inserts Convert (dequant→requant) ops at every quantized-layer boundary
to bridge between INT8 conv layers and FP32 activations/normalization.

For YOLOv8n (~6M params, many small layers), Convert overhead dominates the
INT8 compute savings on Pi 5 / Cortex-A76 / OpenVINO 2026.0.

### Paper implication (§V Pareto)

INT8 cannot win on FPS — must win on energy (J/frame) via PowerZ data.
The scheduler's role is precisely this: choose precision based on observed
runtime cost (not naive "INT8 always faster" assumption). This finding
strengthens motivation for the proposed dynamic precision selection.

### Required follow-up
- mAP delta (INT8 vs FP32) measurement deferred to Task 19
- J/frame comparison via PowerZ deferred to Phase D.4 baseline matrix
- Re-quantization with `preset=PERFORMANCE` not pursued: frozen artifact
  is hash-locked, current behavior representative of standard NNCF deployment

## [v0.7.7] — 2026-05-01

### S2.1: INT8 model deployed to Pi

**Source:** Frozen artifact `00_frozen_artifacts/yolov8n_baseline_seed42/weights/openvino_int8/`
- Calibration: NNCF 3.0.0 PTQ, 481 validation images (full split)
- Exported: 2026-04-01 via `model.export(format='openvino', int8=True, data='rdd2022.yaml', fraction=1.0)`
- SHA256 (best.bin): `74ca338c4a866cb803bb68bf39f5f798b78cd110c45f1e4c2f3a77582833df51`

**Deployment:**
- SCP'd from Windows frozen artifacts to Pi `~/sustained-edge-vision/02_models/openvino/yolov8n_int8/`
- Renamed best.{bin,xml} → yolov8n.{bin,xml} per Pi convention
- Hash verified post-deployment ✓

**Initial verification (200 frames, passive cooling, no telemetry):**
- Output shape: [1,8,8400] ✓ (4 RDD classes confirmed)
- **FPS: 8.69** (latency 115.12 ms)

### Anomaly: INT8 slower than FP32 (paper finding, not a bug)

| Model | FPS | Latency | Notes |
|-------|-----|---------|-------|
| FP32 | 14.579 | 68.6 ms | n=3 paired benchmark, 2026-04-30 |
| INT8 | 8.69 | 115.1 ms | 200-frame test, 2026-05-01 |

INT8 is **42% slower** than FP32 on Pi 5 / OpenVINO 2026.0 / Cortex-A76.
Root cause: OpenVINO ARM runtime does not effectively use SDOT/UDOT
instructions; dequantize/quantize ops at layer boundaries dominate for
small models. This is a documented OpenVINO ARM characteristic.

**Paper implication:** The FP32 ↔ INT8 trade-off is non-trivial — INT8
is NOT pure speedup. Selection must be based on energy/inference (J/frame)
rather than FPS alone. This motivates the scheduler's dynamic precision
selection (proposal §3) precisely because the choice is non-obvious.

**Required follow-up:**
- Phase D.4 baseline matrix must include both FP32 and INT8 cells
- Energy data via PowerZ will reveal whether INT8 wins on J/frame
- mAP delta vs FP32 measurement deferred to Task 19 metric definitions

`01_documentation/MODELS_DEPLOYED.md` created to track deployed model
provenance and verification commands.

## [v0.7.6] — 2026-04-30

### CRITICAL: Re-verified overhead with correct model AND correct workload

**Context:** v0.7.5 identified that all 2026-04-28 FPS benchmarks used the wrong
COCO pretrained model. Today's work replaced the COCO model with the frozen
RDD baseline (SHA256: 0de2334a...) AND switched workload from test_traffic.mp4
(temporal redundancy, hardware-optimizable) to thermal_benchmark_30fps.mp4
(961 disjoint frames, worst-case workload per Progress Report §IV.G).

### Verified (Pi 5, passive cooling, ambient 22.9-23.7°C, 2 Hz telemetry)

**5-min paired benchmark (n=3 each):**
- Inference-only:      mean = 14.579 FPS, std = 0.019
- Inference+telemetry: mean = 14.302 FPS, std = 0.067
- **Relative overhead: 1.90%** (target <3%, 37% margin)
- **Absolute overhead: 1.33 ms/frame** (decoupled from compute load)

### Comparison: Wrong vs Correct model (sanity check)
- Wrong COCO model FPS:    12.396 (slower — 80 classes, more post-processing)
- Correct RDD model FPS:   14.579 (~17% faster — 4 classes)
- Overhead in both cases <2%, confirming pipeline-level cost (1.21-1.33 ms/frame)
  is independent of model — exactly as predicted by IPC architecture analysis.

**Conclusion:** Phase D.2 telemetry overhead milestone REACHED with correct
model + correct worst-case workload. Foundation locked for Phase D.4 30-min
baseline matrix runs.

**PowerZ data:** 6× .db files in 05_results/power_data/ (3 inferonly + 3 withtel,
all 2026-04-30, FP32, passive, thermal_benchmark workload).

## [v0.7.5] — 2026-04-29

### CRITICAL FIX: Wrong model deployed to Pi (model swap)

**Problem:** `02_models/openvino/yolov8n_fp32/` contained the COCO pretrained
YOLOv8n (80 classes, exported 2026-04-26T19:40) instead of the frozen baseline
road damage detector (4 classes: D00/D10/D20/D40).

**Root cause:** On 2026-04-26, model export ran against default pretrained weights
instead of `best.pt`. The resulting COCO model was deployed to Pi and used for
all inference runs since then.

**Impact:**
- ALL FPS measurements from 2026-04-28 overhead benchmark are INVALID
  (wrong model, wrong output shape [1,84,8400] vs correct [1,8,8400])
- Calibration runs (stress-ng, telemetry only) are UNAFFECTED
- EMA parameter tuning is UNAFFECTED
- Telemetry overhead % is still approximately valid (pipeline-level property)
  but must be re-verified with correct model

**Fix:**
- Deployed frozen artifact `openvino_fp32/best.bin` (SHA256: 0de2334a...)
  to `02_models/openvino/yolov8n_fp32/` on Pi
- Renamed best.bin → yolov8n.bin, best.xml → yolov8n.xml
- Verified: output shape [1,8,8400] ✓, D00/D10/D20/D40 ✓
- Wrong COCO model archived as `yolov8n_fp32_WRONG_COCO/` on Pi

**Required follow-up:**
- Re-run full 6-run paired overhead benchmark with correct model
- Update CHANGELOG v0.7.6 with new verified FPS numbers
- Update progress report with corrected baseline FPS

## [v0.7.4] — 2026-04-29

### S1.4: Absolute path fix for run_experiment.py
- `run_dir` now computed as `_CODE_ROOT.parent / "05_results" / "runs" / run_name`
  instead of `Path("../../05_results/runs")`.
- Script now works correctly when invoked from any CWD (repo root, 03_code/experiments,
  or anywhere else). Previously only worked from 03_code/experiments/.
- Fixed `--sampling-rate-hz` default from 5.0 → 2.0 to match v0.7.2 telemetry default.
- Verified: `--help` works cleanly from both repo root and 03_code/experiments.

## [v0.7.3] — 2026-04-29

### S1.5: EMA α/stride recalibration for 2 Hz sampling

**Problem:** v0.7.2 changed default sampling rate to 2 Hz (dt=0.5s) but
`derivatives.py` retained 5 Hz α/stride values, silently changing the
effective tau_smooth and rate_window for all signals.

**Fix:** Added `DEFAULT_CONFIG_2HZ` with analytically recalculated
parameters preserving tau_smooth and rate_window:

| Signal    | α (5Hz) | α (2Hz) | stride (5Hz) | stride (2Hz) | tau_smooth | rate_window |
|-----------|---------|---------|--------------|--------------|------------|-------------|
| temp_soc  | 0.10    | 0.2314  | 10           | 4            | 1.898 s    | 2.0 s       |
| cpu_util  | 0.10    | 0.2314  | 15           | 6            | 1.898 s    | 3.0 s       |
| volt_core | 0.30    | 0.5901  | 5            | 2            | 0.561 s    | 1.0 s       |
| cpu_freq  | 0.30    | 0.5901  | 5            | 2            | 0.561 s    | 1.0 s       |
| mem_util  | 0.20    | 0.5120  | 10           | 4            | 0.694 s    | 2.0 s       |

Formula: `alpha_new = 1 - exp(-dt_new / tau_smooth)`
         `stride_new = round(rate_window / dt_new)`

**Verified:**
- 9/9 unit tests pass
- Downsampled stress trace replay: std ratio = 1.085 (target 0.5-2.0)
- tau_smooth preservation confirmed analytically and empirically

**No re-calibration needed:** tau is a physical property of Pi 5 hardware,
independent of sampling rate. Existing Phase B calibration data remains valid.

`DEFAULT_CONFIG_5HZ` retained for backward compatibility and unit tests.
`StateVectorBuilder` now defaults to `DEFAULT_CONFIG` alias → `DEFAULT_CONFIG_2HZ`.

## [v0.7.2] — 2026-04-28

### Optimized
- **Default sampling rate reduced from 5.0 Hz → 2.0 Hz** for telemetry pipeline.
  - **Justification (Nyquist):** Scheduler thermal time constant τ ≈ 10s (proposal §4). 
    2 Hz sampling = 20× oversampled relative to Nyquist (0.1 Hz). Original 5 Hz was 
    50× oversampled with no scientific benefit.
  - **Limitation:** CPU utilization sampling now misses sub-500ms transients. Acceptable 
    because HCC scheduler reacts on thermal derivative (τ_EMA=2s), not CPU spikes.
  - **Effective rates:** fast signals=2 Hz, slow signals (vcgencmd)=0.4 Hz (decimation factor 5 retained).

### Verified (Pi 5, passive cooling, ambient 22.7-23.0°C)
- **5-min paired benchmark (n=3 inference-only + 3 inference+telemetry at 2 Hz):**
  - Inference-only:        mean = 12.396 FPS, std = 0.010
  - Inference+telemetry:   mean = 12.213 FPS, std = 0.026
  - **Relative overhead:   1.48%** (target <3%, achieved with 51% margin)
  - **Absolute overhead:   1.21 ms/frame** (decoupled from compute load)

### Required follow-up (S1.5)
- **EMA α recalibration:** All EMA filters in scheduler must use α = 1 - exp(-Δt/τ_smooth) with Δt=0.5s.
  Previous 5 Hz α values (Δt=0.2s) would slow scheduler response by 2.5×.
  - Example: For τ_smooth=2s, new α = 0.2212 (was 0.0952 at 5 Hz).

**Conclusion:** Phase D.2 telemetry overhead milestone **REACHED** with 1.21 ms/frame absolute 
penalty (1.48% relative). Reporting both metrics in paper §IV.B per WorkPlan Task 19.

**PowerZ data:** 3× inference-only + 3× inference+telemetry (2 Hz) + 3× inference+telemetry (5 Hz, deprecated) 
.db files in `05_results/power_data/`. Sync with telemetry via Unix epoch for energy/frame analysis.

## [v0.7] — 2026-04-27

### Summary
S1.1 fix: telemetry vcgencmd overhead reduced. Targets the 15% inference
slowdown observed in the v0.6 60s smoke test, blocking Phase D.4 baseline
runs. WorkPlan §6.2 Task 10; IoT-J reviewer-facing requirement #2
(overhead profiling).

### Changed
- `03_code/telemetry/telemetry_pipeline.py`:
  - `_read_cpu_freq()` now reads `/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq`
    (kHz, single file read, ~5 us). Falls back to `vcgencmd measure_clock arm`
    only if sysfs node is absent. Eliminates 1 of 3 vcgencmd subprocesses
    per sample.
  - New `_read_all_signals_decimated()` samples `volt_core_v`,
    `throttle_raw`, `throttled_now`, `undervolt_now` at 1 Hz (every 5th
    base sample), carrying values forward in between via a worker-local
    cache. Eliminates ~80% of remaining vcgencmd subprocess overhead.
  - Sampling-loop call site updated to use the decimated reader.

### CSV Semantics — No Silent Changes Rule disclosure
- `telemetry_raw.csv` columns `volt_core_v`, `throttle_raw`,
  `throttled_now`, `undervolt_now` now contain carry-forward (zero-order
  hold) values on 4 of every 5 rows. The (k*5)-th row is a fresh read.
- This is mathematically equivalent to a 1 Hz sampling regime for those
  signals, oversampled 10x relative to the scheduler's thermal time
  constant tau ~ 10s (proposal_v2.pdf §4).
- The `temp_soc_c`, `cpu_util_percent`, `mem_util_percent`, `cpu_freq_mhz`
  columns remain at the full 5 Hz fast rate.
- Limitation: sub-200 ms throttle bursts are not observable. Acceptable;
  Pi 5 thermal-throttle dwell is RC-determined in seconds.

### Metadata
- `run_metadata.json` (schema version unchanged) gains three additive
  fields:
  - `slow_signal_decimation_factor` (int, e.g. 5)
  - `effective_sampling_rate_hz` (dict: fast_signals, slow_signals)
  - `slow_signals` (list of CSV column names treated as slow)
- Old metadata readers are unaffected (additive only).

### Validity of prior logs
- The four v0.5 calibration runs (2x idle + 2x stress, 30 min each at
  ~22.7-23.6 C ambient) are NOT invalidated. They predate this change
  and ran at uniform 5 Hz across all signals; their EMA tuning
  (alpha=0.1, stride=10) is unaffected because the tuning used only
  temp_soc_c, which remains 5 Hz under the new regime.

### Verification (PENDING — to be appended in v0.7.1 after Pi runs)
- [ ] 60s smoke test with new pipeline: completeness >= 0.99,
      sensor_failure_rate == 0
- [ ] 5-min paired benchmark: inference-only vs inference+telemetry,
      n=3 reps each, target <3% mean-FPS delta. Hard numbers in next entry.

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
## v0.11.0 � 2026-05-24
- ADDED: Active-cooling oracle (Static-S0, official Pi 5 fan, n=3)
  - FPS: 14.52 FPS mean, 0 throttle events, plateau TBD pending plateau check
  - cooling_condition corrected to active_fan in run_metadata.json
  - Paper use: oracle upper bound for scheduler efficiency (�V, �VI)
