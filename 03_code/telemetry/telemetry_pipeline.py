"""
telemetry_pipeline.py
=====================
Synchronized telemetry logger for sustained edge inference experiments.

Grounding
---------
- WorkPlan_marked.pdf, Task 10 (§6.2): unified 5 Hz pipeline collecting
  T(t), U(t), V(t), cpu_freq, mem_util, throttle. Per-signal documentation
  of data source, sampling rate, smoothing method, inference sync method.
- proposal_v2.pdf §4: state vector s(t) = [T, T_dot, U, U_dot, V, V_dot].
  Raw signals land here; derivatives are computed downstream by
  03_code/scheduler/derivatives.py.
- WorkPlan_marked.pdf §1.1 Reproducibility Rule: session metadata
  (git SHA, hardware, software, seed, ambient, cooling) is written at
  start as metadata.partial.json and finalized at clean shutdown.

Architecture
------------
One producer, two consumers:
  1. CSV writer (inline, same process)  -> telemetry_raw.csv
  2. Optional mp.Queue subscriber        -> scheduler runtime
Drop-on-full policy ensures a slow scheduler cannot block the sampler.

Signals collected
-----------------
  temp_soc_c       SoC temperature (deg C)       from /sys/class/hwmon
  volt_core_v      Core voltage (V)              from vcgencmd measure_volts core
  cpu_util_percent Aggregate CPU utilization (%) from psutil.cpu_percent
  mem_util_percent RAM utilization (%)           from psutil.virtual_memory
  cpu_freq_mhz     ARM clock (MHz)               from vcgencmd measure_clock arm
  throttle_raw     vcgencmd get_throttled word   from vcgencmd get_throttled
  throttled_now    Bit 2 of throttle_raw (currently throttled)
  undervolt_now    Bit 0 of throttle_raw (undervoltage detected)

Throttle bit layout (per Raspberry Pi documentation)
----------------------------------------------------
  bit 0  (0x1)    undervoltage detected NOW
  bit 1  (0x2)    arm frequency capped NOW
  bit 2  (0x4)    currently throttled NOW              <-- this is the
                                                          thermal event
  bit 3  (0x8)    soft temperature limit active NOW
  bits 16-19      sticky "has occurred since boot"

The raw word is logged so any bit can be reconstructed in post-processing
without a re-run.

Change log
----------
v0.2 (2026-04-19): Severity 1 fixes from PI review.
  - FIXED: throttle bit mask was 0x1 (undervoltage), corrected to 0x4.
           All earlier logs (if any) must be treated as invalid for any
           throttle-based metric.
  - FIXED: sensor-failure fallback was 0.0, now None (empty CSV cell) so
           downstream code sees the gap and does not produce spurious
           derivatives.
  - FIXED: drift-prone sleep() replaced with absolute-deadline sampler.
  - ADDED: psutil warmup call, per-signal failure counters, richer
           metadata, partial metadata at start, optional scheduler queue.

Usage
-----
    from telemetry_pipeline import TelemetryPipeline
    pipe = TelemetryPipeline(run_dir="05_results/runs/2026-04-19_smoke",
                             duration_sec=600)
    pipe.start()
    # ... do inference ...
    pipe.stop()

With a scheduler consumer:

    import multiprocessing as mp
    q = mp.Queue(maxsize=100)
    pipe = TelemetryPipeline(run_dir=..., scheduler_queue=q)
    pipe.start()
    # In scheduler process: q.get() yields sample dicts.
"""

from __future__ import annotations

import csv
import json
import logging
import multiprocessing as mp
import os
import queue as queue_mod
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

log = logging.getLogger(__name__)


# -- Public API ---------------------------------------------------------------


class TelemetryPipeline:
    """
    Non-blocking telemetry logger that runs in a subprocess.

    Writes telemetry_raw.csv and run_metadata.json into run_dir. Optionally
    publishes each sample onto scheduler_queue for live consumption.

    Parameters
    ----------
    run_dir : path
        Directory for CSV and metadata output. Created if it does not exist.
    sampling_rate_hz : float, default 5.0
        Target sampling rate. 5 Hz = 200 ms period, matches proposal_v2.pdf.
    duration_sec : float, optional
        If given, the worker stops automatically after this many seconds.
        If None, runs until stop() is called.
    ambient_temp_c : float, optional
        Ambient temperature in deg C, recorded in metadata. Required by
        Reproducibility Rule for cross-run thermal comparison.
    cooling_condition : str
        "passive" or "active_fan" etc. Free-form label for metadata.
    tags : dict, optional
        Arbitrary run-level metadata (workload name, operator initials, etc.).
    scheduler_queue : multiprocessing.Queue, optional
        If given, each sample dict is also pushed here via put_nowait. Full
        queue drops are counted and reported at shutdown.
    seed : int, optional
        Random seed in use for the session. Logged in metadata per §1.1.
    """

    def __init__(
        self,
        run_dir: str | os.PathLike,
        sampling_rate_hz: float = 5.0,
        duration_sec: Optional[float] = None,
        ambient_temp_c: Optional[float] = None,
        cooling_condition: str = "unknown",
        tags: Optional[Dict[str, Any]] = None,
        scheduler_queue: Optional[mp.Queue] = None,
        seed: Optional[int] = None,
    ):
        self.run_dir = Path(run_dir)
        self.run_dir.mkdir(parents=True, exist_ok=True)

        if sampling_rate_hz <= 0:
            raise ValueError(f"sampling_rate_hz must be positive, got {sampling_rate_hz}")
        self.sampling_rate_hz = float(sampling_rate_hz)
        self.duration_sec = duration_sec
        self.ambient_temp_c = ambient_temp_c
        self.cooling_condition = cooling_condition
        self.tags = dict(tags) if tags else {}
        self.scheduler_queue = scheduler_queue
        self.seed = seed

        self.csv_path = self.run_dir / "telemetry_raw.csv"
        self.metadata_path = self.run_dir / "run_metadata.json"
        self.partial_metadata_path = self.run_dir / "run_metadata.partial.json"

        self._process: Optional[mp.Process] = None
        self._stop_event: Optional[mp.Event] = None
        self._shared_start_monotonic: Optional[mp.Value] = None

    def start(self) -> float:
        """
        Spawn the telemetry subprocess. Returns the shared monotonic start
        time. Any other process on the same host that wants to log events
        on the same time base (e.g. the inference runtime) should read this
        value and write its own CSV using `time.monotonic() - start`.
        """
        if self._process is not None:
            raise RuntimeError("TelemetryPipeline already started")

        self._stop_event = mp.Event()
        # Shared float the parent can hand to other processes for clock
        # alignment. Written by the worker once it has captured its own
        # monotonic reference.
        self._shared_start_monotonic = mp.Value("d", 0.0)

        self._process = mp.Process(
            target=_telemetry_worker_entry,
            args=(
                str(self.csv_path),
                str(self.metadata_path),
                str(self.partial_metadata_path),
                self.sampling_rate_hz,
                self.duration_sec,
                self._stop_event,
                self._shared_start_monotonic,
                self.ambient_temp_c,
                self.cooling_condition,
                self.tags,
                self.scheduler_queue,
                self.seed,
            ),
            daemon=False,
            name="telemetry_worker",
        )
        self._process.start()

        # Wait briefly for the worker to publish its start time so callers
        # can synchronize against it.
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and self._shared_start_monotonic.value == 0.0:
            time.sleep(0.01)

        return float(self._shared_start_monotonic.value)

    def stop(self, timeout: float = 5.0) -> None:
        """Stop the telemetry subprocess gracefully."""
        if self._process is None:
            return

        self._stop_event.set()
        self._process.join(timeout=timeout)

        if self._process.is_alive():
            log.warning("telemetry worker did not exit cleanly, terminating")
            self._process.terminate()
            self._process.join(timeout=1.0)
            if self._process.is_alive():
                log.error("telemetry worker did not respond to SIGTERM, killing")
                self._process.kill()
                self._process.join()

        self._process = None

    @property
    def shared_start_monotonic(self) -> float:
        """
        Monotonic clock value (seconds) at which the first telemetry sample
        was recorded. Other processes use this to align their own event logs.
        Returns 0.0 if not yet started.
        """
        if self._shared_start_monotonic is None:
            return 0.0
        return float(self._shared_start_monotonic.value)


# -- Worker process -----------------------------------------------------------


# Columns in telemetry_raw.csv. Order is stable and must not change
# silently (No Silent Changes Rule).
_CSV_FIELDNAMES = [
    "monotonic_offset_s",
    "utc_timestamp",
    "temp_soc_c",
    "volt_core_v",
    "cpu_util_percent",
    "mem_util_percent",
    "cpu_freq_mhz",
    "throttle_raw",
    "throttled_now",
    "undervolt_now",
]


@dataclass
class _FailureCounters:
    """Per-signal cumulative failure counter for trace-quality reporting.
    Each field counts the total number of failed reads for that signal
    over the lifetime of the telemetry session (not consecutive).
    Used by _compute_trace_quality() to report sensor_failure_rate as
    total_failures / (samples_collected * n_signals)"""
    temp_soc: int = 0
    volt_core: int = 0
    cpu_util: int = 0
    mem_util: int = 0
    cpu_freq: int = 0
    throttled: int = 0
    scheduler_queue_drops: int = 0

    def as_dict(self) -> Dict[str, int]:
        return {
            "temp_soc": self.temp_soc,
            "volt_core": self.volt_core,
            "cpu_util": self.cpu_util,
            "mem_util": self.mem_util,
            "cpu_freq": self.cpu_freq,
            "throttled": self.throttled,
            "scheduler_queue_drops": self.scheduler_queue_drops,
        }


def _telemetry_worker_entry(
    csv_path_str: str,
    metadata_path_str: str,
    partial_metadata_path_str: str,
    sampling_rate_hz: float,
    duration_sec: Optional[float],
    stop_event: mp.Event,
    shared_start_monotonic: mp.Value,
    ambient_temp_c: Optional[float],
    cooling_condition: str,
    tags: Dict[str, Any],
    scheduler_queue: Optional[mp.Queue],
    seed: Optional[int],
) -> None:
    """Worker process entry point. Runs the sampling loop until stop."""

    def _handle_signal(signum, frame):
        stop_event.set()

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    csv_path = Path(csv_path_str)
    metadata_path = Path(metadata_path_str)
    partial_metadata_path = Path(partial_metadata_path_str)

    # Gather session metadata BEFORE sampling starts, write partial file
    # immediately so a crashed run still has context.
    session_meta = _gather_session_metadata(
        csv_path=csv_path,
        sampling_rate_hz=sampling_rate_hz,
        duration_sec=duration_sec,
        ambient_temp_c=ambient_temp_c,
        cooling_condition=cooling_condition,
        tags=tags,
        seed=seed,
    )
    _write_json_atomic(partial_metadata_path, session_meta)

    # psutil warmup: first cpu_percent(None) call returns 0.0 because
    # there is no prior reference. Fire a throwaway so the first real
    # sample is valid.
    try:
        import psutil  # imported here so the main process is not forced to have it
        psutil.cpu_percent(interval=None)
    except ImportError:
        log.warning("psutil not available; cpu_util and mem_util will be None")
        psutil = None  # type: ignore

    sample_interval = 1.0 / sampling_rate_hz
    failures = _FailureCounters()

    csv_file = open(csv_path, "w", newline="", encoding="utf-8")
    writer = csv.DictWriter(csv_file, fieldnames=_CSV_FIELDNAMES)
    writer.writeheader()
    csv_file.flush()

    # Record the start-of-sampling monotonic reference. Everything after
    # this uses absolute deadlines against this anchor, so sleep jitter
    # does not accumulate over long runs.
    start_monotonic = time.monotonic()
    shared_start_monotonic.value = start_monotonic

    sample_index = 0
    try:
        while not stop_event.is_set():
            target = start_monotonic + sample_index * sample_interval

            # Stop if we have reached the requested duration.
            if duration_sec is not None and (target - start_monotonic) >= duration_sec:
                break

            now = time.monotonic()
            if now < target:
                # Use a short timeout on the stop event so we remain
                # responsive to shutdown while waiting for the next tick.
                stop_event.wait(timeout=target - now)
                if stop_event.is_set():
                    break

            sample_monotonic = time.monotonic()
            sample = _read_all_signals(psutil, failures)
            row = {
                "monotonic_offset_s": round(sample_monotonic - start_monotonic, 6),
                "utc_timestamp": datetime.now(timezone.utc).isoformat(),
                **sample,
            }
            writer.writerow(row)

            if scheduler_queue is not None:
                try:
                    scheduler_queue.put_nowait(row)
                except queue_mod.Full:
                    failures.scheduler_queue_drops += 1

            sample_index += 1
            if sample_index % 10 == 0:  # flush every ~2 s at 5 Hz
                csv_file.flush()

    except Exception as exc:  # pragma: no cover - defensive
        log.exception("telemetry worker crashed: %s", exc)
        session_meta["crashed"] = True
        session_meta["crash_reason"] = repr(exc)
    finally:
        csv_file.flush()
        csv_file.close()

        session_meta["end_time_utc"] = datetime.now(timezone.utc).isoformat()
        session_meta["samples_collected"] = sample_index
        expected_samples = (
            int(duration_sec * sampling_rate_hz) if duration_sec is not None else None
        )
        session_meta["samples_expected"] = expected_samples
        session_meta["failure_counts"] = failures.as_dict()
        session_meta["trace_quality"] = _compute_trace_quality(
            csv_path=csv_path,
            sampling_rate_hz=sampling_rate_hz,
            samples_collected=sample_index,
            samples_expected=expected_samples,
            failures=failures,
        )

        _write_json_atomic(metadata_path, session_meta)
        try:
            partial_metadata_path.unlink()
        except FileNotFoundError:
            pass


# -- Signal readers -----------------------------------------------------------


# Primary thermal endpoint on Pi 5. Fallback to thermal_zone0 if hwmon is
# renumbered by a kernel update (this has happened historically on RPi).
_HWMON_TEMP_PATHS = (
    "/sys/class/hwmon/hwmon0/temp1_input",
    "/sys/class/thermal/thermal_zone0/temp",
)


def _read_all_signals(psutil_mod: Any, failures: _FailureCounters) -> Dict[str, Any]:
    """
    Read every signal exactly once. Any failure produces None (not 0.0)
    so downstream derivative computation sees a gap and skips that sample.

    Returns a dict keyed by _CSV_FIELDNAMES minus monotonic_offset_s and
    utc_timestamp (those are stamped by the caller).
    """
    return {
        "temp_soc_c": _read_temp(failures),
        "volt_core_v": _read_volt_core(failures),
        "cpu_util_percent": _read_cpu_util(psutil_mod, failures),
        "mem_util_percent": _read_mem_util(psutil_mod, failures),
        "cpu_freq_mhz": _read_cpu_freq(failures),
        **_read_throttle(failures),
    }


def _read_temp(failures: _FailureCounters) -> Optional[float]:
    for path in _HWMON_TEMP_PATHS:
        try:
            with open(path, encoding="utf-8") as f:
                milli = int(f.read().strip())
                return milli / 1000.0
        except (OSError, ValueError):
            continue
    failures.temp_soc += 1
    return None


def _read_volt_core(failures: _FailureCounters) -> Optional[float]:
    out = _run(["vcgencmd", "measure_volts", "core"])
    if out is None:
        failures.volt_core += 1
        return None
    try:
        # "volt=0.7500V"
        return float(out.split("=", 1)[1].rstrip("V"))
    except (IndexError, ValueError):
        failures.volt_core += 1
        return None


def _read_cpu_util(psutil_mod: Any, failures: _FailureCounters) -> Optional[float]:
    if psutil_mod is None:
        failures.cpu_util += 1
        return None
    try:
        return float(psutil_mod.cpu_percent(interval=None))
    except Exception:
        failures.cpu_util += 1
        return None


def _read_mem_util(psutil_mod: Any, failures: _FailureCounters) -> Optional[float]:
    if psutil_mod is None:
        failures.mem_util += 1
        return None
    try:
        return float(psutil_mod.virtual_memory().percent)
    except Exception:
        failures.mem_util += 1
        return None


def _read_cpu_freq(failures: _FailureCounters) -> Optional[float]:
    out = _run(["vcgencmd", "measure_clock", "arm"])
    if out is None:
        failures.cpu_freq += 1
        return None
    try:
        # "frequency(0)=1500019456"
        hz = int(out.split("=", 1)[1])
        return hz / 1.0e6  # -> MHz
    except (IndexError, ValueError):
        failures.cpu_freq += 1
        return None


def _read_throttle(failures: _FailureCounters) -> Dict[str, Optional[int]]:
    out = _run(["vcgencmd", "get_throttled"])
    if out is None:
        failures.throttled += 1
        return {"throttle_raw": None, "throttled_now": None, "undervolt_now": None}
    try:
        # "throttled=0x0"
        raw = int(out.split("=", 1)[1], 16)
    except (IndexError, ValueError):
        failures.throttled += 1
        return {"throttle_raw": None, "throttled_now": None, "undervolt_now": None}

    return {
        "throttle_raw": raw,
        "throttled_now": 1 if (raw & 0x4) else 0,   # bit 2: currently throttled
        "undervolt_now": 1 if (raw & 0x1) else 0,   # bit 0: undervoltage detected
    }


def _run(cmd, timeout: float = 0.5) -> Optional[str]:
    """
    Run a subprocess, returning stripped stdout or None on any failure.

    Default timeout is 500 ms -- well above typical vcgencmd response
    (~5 ms) but well below the 200 ms sampling period * 2 = 400 ms
    that would push the next sample's deadline. Metadata-collection
    callers (git, hostname, etc.) override with a longer timeout.
    """
    try:
        return subprocess.check_output(cmd, text=True, timeout=timeout).strip()
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        return None


# -- Session metadata ---------------------------------------------------------


def _gather_session_metadata(
    csv_path: Path,
    sampling_rate_hz: float,
    duration_sec: Optional[float],
    ambient_temp_c: Optional[float],
    cooling_condition: str,
    tags: Dict[str, Any],
    seed: Optional[int],
) -> Dict[str, Any]:
    """Collect reproducibility fields required by WorkPlan §1.1."""
    import platform

    return {
        "schema_version": "0.2",
        "start_time_utc": datetime.now(timezone.utc).isoformat(),
        "csv_path": str(csv_path),
        "sampling_rate_hz": sampling_rate_hz,
        "duration_sec": duration_sec,
        "ambient_temp_c": ambient_temp_c,
        "cooling_condition": cooling_condition,
        "seed": seed,
        "tags": tags,
        "git": {
            "sha": _run(["git", "rev-parse", "HEAD"], timeout=2.0),
            "branch": _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], timeout=2.0),
            "dirty": _git_dirty(),
        },
        "hardware": {
            "hostname": _run(["hostname"], timeout=2.0),
            "pi_model": _read_device_tree_model(),
            "firmware": _run(["vcgencmd", "version"], timeout=2.0),
            "kernel": _run(["uname", "-a"], timeout=2.0),
            "cpu_governor": _read_file("/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor"),
            "arm_freq_config": _run(["vcgencmd", "get_config", "arm_freq"], timeout=2.0),
        },
        "software": {
            "python_version": sys.version,
            "platform": platform.platform(),
            "psutil_version": _pkg_version("psutil"),
            "numpy_version": _pkg_version("numpy"),
        },
    }


def _git_dirty() -> Optional[bool]:
    out = _run(["git", "status", "--porcelain"], timeout=2.0)
    if out is None:
        return None
    return len(out) > 0


def _read_device_tree_model() -> Optional[str]:
    try:
        with open("/proc/device-tree/model", encoding="utf-8") as f:
            # device-tree strings are null-terminated
            return f.read().rstrip("\x00").strip()
    except OSError:
        return None


def _read_file(path: str) -> Optional[str]:
    try:
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return None


def _pkg_version(name: str) -> Optional[str]:
    try:
        from importlib.metadata import version, PackageNotFoundError
        try:
            return version(name)
        except PackageNotFoundError:
            return None
    except ImportError:
        return None


def _write_json_atomic(path: Path, data: Dict[str, Any]) -> None:
    """Write JSON via tmp + rename so partial writes are never visible."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _compute_trace_quality(
    csv_path: Path,
    sampling_rate_hz: float,
    samples_collected: int,
    samples_expected: Optional[int],
    failures: _FailureCounters,
) -> Dict[str, Any]:
    """Lightweight post-run stats for trace-quality assessment."""
    quality: Dict[str, Any] = {
        "samples_collected": samples_collected,
        "samples_expected": samples_expected,
    }
    if samples_expected and samples_expected > 0:
        quality["completeness"] = round(samples_collected / samples_expected, 4)

    total_failures = sum(
        v for k, v in failures.as_dict().items() if k != "scheduler_queue_drops"
    )
    if samples_collected > 0:
        quality["sensor_failure_rate"] = round(
            total_failures / (samples_collected * 6), 4  # 6 signals per sample
        )
    quality["scheduler_queue_drop_count"] = failures.scheduler_queue_drops
    return quality


# -- Smoke test ---------------------------------------------------------------


if __name__ == "__main__":
    import argparse
    import json as _json

    parser = argparse.ArgumentParser(
        description="Run the 5 Hz telemetry pipeline and write raw CSV + metadata."
    )
    parser.add_argument("--duration", type=float, default=30.0,
                        help="Sampling duration in seconds (default: 30)")
    parser.add_argument(
        "--run-dir",
        default=f"05_results/runs/{datetime.now().strftime('%Y-%m-%d_%H%M%S')}_smoketest",
        help="Directory for output CSV and metadata",
    )
    parser.add_argument("--ambient-temp-c", type=float, default=None,
                        help="Measured ambient temperature in °C "
                             "(required for paper-quality runs)")
    parser.add_argument("--cooling", default="passive",
                        choices=["passive", "active_fan", "active_heatsink", "unknown"],
                        help="Cooling condition label")
    parser.add_argument("--tags", default="{}",
                        help='JSON string of arbitrary tags, e.g. '
                             '\'{"workload":"idle","purpose":"calibration"}\'')
    parser.add_argument("--seed", type=int, default=42,
                        help="Seed passed through to metadata")
    parser.add_argument(
        "--sampling-rate-hz", type=float, default=5.0,
        help="Target sampling rate (default: 5 Hz per proposal §4)",
    )
    args = parser.parse_args()

    try:
        tags = _json.loads(args.tags)
    except _json.JSONDecodeError as e:
        parser.error(f"--tags must be valid JSON: {e}")

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")

    pipe = TelemetryPipeline(
        run_dir=args.run_dir,
        sampling_rate_hz=args.sampling_rate_hz,
        duration_sec=args.duration,
        ambient_temp_c=args.ambient_temp_c,
        cooling_condition=args.cooling,
        tags=tags,
        seed=args.seed,
    )
    shared_start = pipe.start()
    print(f"Pipeline started; shared monotonic start = {shared_start:.6f}")
    print(f"Run dir: {args.run_dir}")
    print(f"Sampling for {args.duration} s ...")
    time.sleep(args.duration + 1.0)
    pipe.stop()

    csv_file = Path(args.run_dir) / "telemetry_raw.csv"
    meta_file = Path(args.run_dir) / "run_metadata.json"

    if csv_file.exists():
        with open(csv_file, encoding="utf-8") as f:
            lines = f.readlines()
        print(f"\nCollected {len(lines) - 1} data rows at {csv_file}")
        for line in lines[: min(6, len(lines))]:
            print("  " + line.rstrip())

    if meta_file.exists():
        with open(meta_file, encoding="utf-8") as f:
            meta = _json.load(f)
        print("\nTrace quality:")
        print(_json.dumps(meta.get("trace_quality", {}), indent=2))
        print("\nFailure counts:")
        print(_json.dumps(meta.get("failure_counts", {}), indent=2))