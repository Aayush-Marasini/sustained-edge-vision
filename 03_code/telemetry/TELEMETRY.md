# TELEMETRY.md — Signal Source Documentation

Per `WorkPlan_marked.pdf` §6.2 (Task 10), every signal in the telemetry
pipeline is documented with its data source, sampling rate, smoothing
method, and synchronization method. This file is the source of truth
for the telemetry section of the paper appendix.

## Pipeline summary

- **Sampling rate**: 5 Hz (200 ms period). Matches the rate implied by
  proposal_v2.pdf §4 for state-vector updates.
- **Clock**: `time.monotonic()` captured once at worker start. All
  sample timestamps are offsets from this reference. Absolute-deadline
  scheduler (not cumulative sleep) keeps the rate locked to the wall
  clock across long runs.
- **Output files**:
  - `telemetry_raw.csv` — one row per sample, 10 columns
  - `run_metadata.json` — session metadata, written at start as
    `.partial.json` and renamed at clean shutdown
- **Consumer model**: one producer, two consumers. The CSV writer is
  inline in the sampler process. An optional `multiprocessing.Queue`
  receives the same sample dicts for live scheduler consumption.
  Drop-on-full policy: a slow scheduler never blocks the sampler; the
  drop count is recorded in metadata.

## Per-signal reference

| CSV column | Unit | Source | Read method | Failure mode | Value on failure |
|---|---|---|---|---|---|
| `temp_soc_c` | °C | SoC thermal sensor | `/sys/class/hwmon/hwmon0/temp1_input` (milli-°C), fallback to `/sys/class/thermal/thermal_zone0/temp` | File read error, missing hwmon node | `None` (empty CSV cell) |
| `volt_core_v` | V | Broadcom firmware | `vcgencmd measure_volts core` | `vcgencmd` missing, subprocess timeout, parse error | `None` |
| `cpu_util_percent` | % | psutil | `psutil.cpu_percent(interval=None)` | psutil not installed | `None` |
| `mem_util_percent` | % | psutil | `psutil.virtual_memory().percent` | psutil not installed | `None` |
| `cpu_freq_mhz` | MHz | Broadcom firmware | `vcgencmd measure_clock arm` | `vcgencmd` missing or returns unexpected format | `None` |
| `throttle_raw` | integer | Broadcom firmware | `vcgencmd get_throttled` (hex parsed to int) | `vcgencmd` failure | `None` |
| `throttled_now` | 0/1 | Derived | Bit 2 (`0x4`) of `throttle_raw` | Upstream failure | `None` |
| `undervolt_now` | 0/1 | Derived | Bit 0 (`0x1`) of `throttle_raw` | Upstream failure | `None` |

### Throttle bit semantics (Raspberry Pi documentation)

| Bit | Mask | Meaning |
|---|---|---|
| 0 | `0x1` | Under-voltage detected **now** |
| 1 | `0x2` | ARM frequency capped **now** |
| 2 | `0x4` | Currently throttled **now** |
| 3 | `0x8` | Soft temperature limit active **now** |
| 16 | `0x10000` | Under-voltage has occurred since boot (sticky) |
| 17 | `0x20000` | ARM frequency capping has occurred (sticky) |
| 18 | `0x40000` | Throttling has occurred (sticky) |
| 19 | `0x80000` | Soft temperature limit has occurred (sticky) |

**The paper's thermal-throttling metric uses bit 2 (`0x4`), not bit 0.**
Logs produced by any earlier revision of `telemetry_pipeline.py` that
used the `0x1` mask are invalid for throttle-based metrics and must be
re-run. See `CHANGELOG.md` entry `[2026-04-19] Task 10: Telemetry
Pipeline v0.2`.

The raw integer is preserved in `throttle_raw` so any bit can be
reconstructed in post-processing without re-running.

## Smoothing and derivatives

Raw samples are **not** smoothed at the telemetry layer. Smoothing and
derivative computation happen downstream in
`03_code/scheduler/derivatives.py`, following the EMA + stride-k
backward finite difference design justified in that module's docstring.
This separation means:

1. `telemetry_raw.csv` is the unmodified ground truth — any future
   smoothing or filter choice can be re-applied without re-running
   experiments.
2. Derived values (`T`, `T_dot`, etc.) live in
   `telemetry_derived.csv`, written by the scheduler runtime.

## Synchronization with inference events

The telemetry worker publishes its `time.monotonic()` start reference
via a shared `multiprocessing.Value` (field
`TelemetryPipeline.shared_start_monotonic`). Any other process on the
same host — notably the inference runtime — reads this value at
startup and writes its own event log (`inference_events.csv`) using
`time.monotonic() - shared_start`. All four per-run CSVs
(`telemetry_raw`, `telemetry_derived`, `scheduler_decisions`,
`inference_events`) therefore share a common monotonic time base and
merge cleanly by nearest-timestamp join in post-processing.

## Known issues / limitations

- `vcgencmd` is a Broadcom-firmware-specific tool. The pipeline
  degrades gracefully on non-Pi hosts (all `vcgencmd` fields become
  `None`) but produces no useful thermal or voltage data there.
- CSV is flushed every 10 samples (~2 s). Up to 2 s of data can be
  lost if the host loses power abruptly. This is an acceptable
  trade-off vs. the I/O cost of flushing every sample.
- The `psutil` `cpu_percent(interval=None)` call requires a warm-up
  invocation; the pipeline handles this by firing one throwaway
  call before the main loop. The *very* first post-warmup sample can
  still read slightly low; subsequent samples are unaffected.
- `scheduler_queue` uses `put_nowait` with drop-on-full. The drop
  count is reported in `run_metadata.json` under
  `trace_quality.scheduler_queue_drop_count`. A non-zero drop count
  for any paper-quality run invalidates that run.

## Verification checklist before a paper-quality run

- [ ] `git status` is clean (or the dirty state is intentional and
      noted in `tags`).
- [ ] A 30-second smoketest run has been inspected; `trace_quality`
      shows `completeness >= 0.99` and `sensor_failure_rate == 0`.
- [ ] Ambient temperature measured and passed via `ambient_temp_c`.
- [ ] Cooling condition accurately labeled (`passive` /
      `active_fan` / etc.).
- [ ] Seed passed explicitly even if unused by telemetry itself
      (downstream modules may consume it).
- [ ] Run directory name follows the convention in
      `05_results/runs/README.md`.