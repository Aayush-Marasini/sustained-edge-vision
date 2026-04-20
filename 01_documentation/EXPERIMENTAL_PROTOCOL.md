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