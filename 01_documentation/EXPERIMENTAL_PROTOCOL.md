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

**Decision:** Recorded per run via `--ambient-temp-c` flag. Measured
with [INSERT THERMOMETER MODEL] placed [INSERT LOCATION] within 1 m
of the Pi, at Pi-surface height. Recorded to 0.5 °C resolution.

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
hardware action.

**Mechanism:**
    echo <freq_khz> | sudo tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_max_freq

**Configuration space (Pi 5):**

| State | scaling_max_freq | Expected FPS | Purpose |
|-------|------------------|--------------|---------|
| S0    | 2400000          | ~15.6        | Max performance (default) |
| S1    | 1800000          | ~13.2        | Moderate cooling |
| S2    | 1500000          | ~11.6        | Aggressive cooling (min) |

**Restoration:** At end of every paper-quality run, scheduler MUST 
reset cap to 2400000 (max). Verified via:

    cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_max_freq

**Why not switch governor to userspace?** Switching governor breaks 
the deployment scenario described in proposal_v2.pdf §1. The paper's 
claim is "scheduler controls a consumer Pi 5 with stock OS" — manually 
locking frequency would invalidate this.

**Why not change voltage directly?** Pi 5 voltage is governed 
internally by the SoC and cannot be directly written via standard 
sysfs interface. Frequency cap is the most invasive control 
available without firmware modifications.