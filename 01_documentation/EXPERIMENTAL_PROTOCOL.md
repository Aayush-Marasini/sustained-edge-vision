# Experimental Protocol

Locked decisions for all Task 22 long-horizon experiments. Changing
any of these after calibration runs begin requires a CHANGELOG entry
and invalidates prior runs.

## CPU Governor

**Decision:** `ondemand` (kernel default)

**Rationale:** The deployment target for this paper is a consumer-grade
Raspberry Pi 5 running stock Raspberry Pi OS. The `ondemand` governor
is the out-of-box default and represents realistic deployment
conditions. Switching to `performance` would produce cleaner thermal
trajectories but would not reflect how edge devices are actually
deployed in the field (WorkPlan §6.2 motivation, proposal_v2.pdf §1).

**Verification before each run:**
cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor
Expected output: `ondemand`

## Cooling

**Decision:** Passive (no fan, no active heatsink).

**Rationale:** Matches the Progress Report thermal benchmark setup and
proposal_v2.pdf §1 motivation ("edge platforms are constrained by
limited thermal dissipation").

## Ambient Temperature

**Decision:** Recorded per run via `--ambient-temp-c` flag. DHT11
sensor on BCM pin 4, averaged over 5 readings at run start and end.
Logged to `run_metadata.json` under `ambient_dht11_start` /
`ambient_dht11_end`. All paper-quality runs conducted at 23.0°C ±
0.5°C ambient (DHT11 resolution: 1°C; all readings stable at 23.0°C).

## Network

**Decision:** WiFi disabled during calibration and long-horizon runs
via `sudo rfkill block wifi`. SSH connection maintained over Ethernet.

**Rationale:** WiFi driver activity produces CPU load spikes that
contaminate the U(t) signal and its derivative. This is out of scope
for this paper.

## DVFS Control (added 2026-05-01)

The proposed scheduler controls thermal load via `scaling_max_freq`
caps on the `ondemand` governor. This preserves the deployment
scenario (governor unchanged) while giving the scheduler a real
hardware actuator.

**Mechanism:**
echo <freq_khz> | sudo tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_max_freq

**Configuration space (Pi 5) — empirically validated, Task 20:**

| State | scaling_max_freq | FPS_mean | Power (W) | J/frame | T_plateau (°C) | throttled_now |
|-------|-----------------|----------|-----------|---------|----------------|---------------|
| S0    | 2400000         | 14.58    | 8.15      | 0.559   | 84.9           | True (53%)    |
| S1    | 1800000         | 12.43    | 5.99      | 0.482   | 81.3           | False (0%)    |
| S2    | 1500000         | 11.01    | 5.33      | 0.484   | 73.1           | False (0%)    |

All values: FP32 model, thermal_benchmark_30fps.mp4, passive cooling,
23.0°C ambient, 30-min runs (Task 20, 2026-05-03).

**Restoration:** At end of every paper-quality run, scheduler MUST
reset cap to 2400000 (max). Enforced by `run_thermal_validation.py`
try/finally block. Verified via `dvfs_control.py --status`.

**Why not switch governor to userspace?** Switching governor breaks
the deployment scenario described in proposal_v2.pdf §1. The paper's
claim is "scheduler controls a consumer Pi 5 with stock OS" —
manually locking frequency would invalidate this.

**Why not change voltage directly?** Pi 5 voltage is governed
internally by the SoC and cannot be directly written via standard
sysfs interface. Frequency cap is the most invasive control
available without firmware modifications.

## Frequency State Selection Rationale (added 2026-05-03)

The Pi 5 exposes 10 factory-validated P-states via cpufreq:
1500, 1600, 1700, 1800, 1900, 2000, 2100, 2200, 2300, 2400 MHz.
We select {S0, S1, S2} = {2400, 1800, 1500} MHz for three reasons:

**1. Distinct thermal outcomes (empirical).**
S0→S1 eliminates kernel throttle events entirely (1910 → 0 over 30
min). The S1/S2 plateau gap is 8.2°C, providing meaningful thermal
separation. Intermediate states (1600–1700 MHz) would produce
T_plateau values between S1 and S2 with no qualitatively distinct
operating regime and no additional throttle protection.

**2. Hysteresis stability (control theory) — σ_T governs bands.**
Scheduler hysteresis bands ΔT_hyst are in absolute °C. The stability
condition requires:

    ΔT_hyst > 3·σ_T

where σ_T is the absolute temperature sensor noise, measured from the
Phase B idle calibration run (2026-04-25, stable window t > 120s):

    σ_T = 0.5835°C  →  3·σ_T = 1.75°C  (minimum hysteresis floor)

The S1/S2 plateau gap of 8.2°C is 4.7× above this floor.
Adding intermediate states would compress inter-state gaps to ~3–4°C,
reducing the hysteresis margin ratio from 4.7× to ~1.7–2.3×.
While technically above the floor, this leaves insufficient margin
for ambient temperature variation across deployment environments.

**IMPORTANT distinction — two separate noise quantities:**
- σ_T = 0.5835°C (absolute temperature noise) → governs ΔT_hyst
- σ_{T_dot} = 0.0759°C/s (derivative noise, DEFAULT_CONFIG_2HZ EMA)
  → governs the minimum proactive trigger magnitude in the scheduler
  decision policy (proposal §5). These are dimensionally distinct
  and must not be conflated.

**3. Deployment robustness (ambient generalization).**
S2 at 73.1°C under 23°C ambient provides 6.9°C margin before the
~80°C throttle onset. This accommodates ≥6°C ambient variation
(e.g., 23°C lab → 29°C summer warehouse), consistent with the
realistic IoT edge deployment environments described in proposal §1.

## Throttle Detection

**Decision:** `throttled_now` (bit 0 of vcgencmd get_throttled bitmask)
is the sole signal used for active-throttle detection.

**Rationale:** `throttle_raw` accumulates historical events and is
never auto-cleared by the kernel. `throttled_now` (bit 0 = 0x00001)
reflects the instantaneous hardware state. All throttle event counts
in paper tables use `throttled_now` exclusively.

**Disclosure:** S1 and S2 runs show `throttle_raw = 0xE0000` at t=0
due to sticky historical flags (bits 17–19) set during the preceding
S0 run. `throttled_now = 0` for 100% of S1 and S2 samples, confirming
no active throttle occurred during those runs.

