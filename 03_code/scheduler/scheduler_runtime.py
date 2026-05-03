"""
scheduler_runtime.py
====================
Scheduler runtime: drains telemetry queue, computes state vector,
runs Task 12 proactive thermal decision policy, applies DVFS, and
writes telemetry_derived.csv and scheduler_decisions.csv.

Grounding
---------
- WorkPlan Task 11 (§6.3): state vector s(t) via StateVectorBuilder.
- WorkPlan Task 12 (§6.4): decision policy with hysteresis and
  dwell-time safeguards — implemented in thermal_scheduler.py,
  wired here. Placeholder removed 2026-05-03.
- proposal_v2.pdf §4: state vector definition.
- proposal_v2.pdf §5: dynamic cost function basis for thresholds.

No Silent Changes Rule
----------------------
scheduler_decisions.csv column schema changed in v0.9.0:
  OLD: config_resolution, config_precision, config_fps_cap, reason
  NEW: dvfs_state, reason, T, T_dot, throttled_now
Any analysis script reading old columns must be updated before
running Task 21 pilot tests.
"""

from __future__ import annotations

import csv
import logging
import multiprocessing as mp
import queue as queue_mod
import signal
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

from scheduler.derivatives import StateVectorBuilder          # type: ignore
from scheduler.thermal_scheduler import (                     # type: ignore
    DEFAULT_SCHEDULER_CONFIG,
    DvfsState,
    SchedulerState,
    decide as thermal_decide,
)
from scheduler.reactive_threshold_scheduler import (   # type: ignore
    DEFAULT_REACTIVE_CONFIG,
    ReactiveThresholdState,
    decide_reactive,
)
from scheduler.dvfs_control import (                          # type: ignore
    DvfsError,
    set_state_by_name,
    restore_max,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# CSV column schemas — change here requires CHANGELOG entry
# ---------------------------------------------------------------------------

_DERIVED_FIELDNAMES = [
    "monotonic_offset_s",
    "utc_timestamp",
    "T", "T_dot",
    "U", "U_dot",
    "V", "V_dot",
    "f", "f_dot",
    "mem",
]

_DECISION_FIELDNAMES = [
    "monotonic_offset_s",
    "utc_timestamp",
    "dvfs_state",
    "reason",
    "T",
    "T_dot",
    "throttled_now",
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

class SchedulerRuntime:
    """
    Drains the telemetry queue, computes the state vector, runs the
    Task 12 thermal decision policy, applies DVFS via dvfs_control,
    and writes telemetry_derived.csv + scheduler_decisions.csv.
    """

    def __init__(
        self,
        run_dir: str,
        telemetry_queue: mp.Queue,
        flush_every_n_samples: int = 10,
        shared_start_monotonic: float = 0.0,
        scheduler_mode: str = "proactive",
    ):
        """
        Parameters
        ----------
        run_dir : str
            Directory where output CSVs are written (same as telemetry run_dir).
        telemetry_queue : mp.Queue
            Queue populated by TelemetryPipeline. Each item is a dict
            with keys matching telemetry_raw.csv columns plus
            'monotonic_offset_s' and 'utc_timestamp'.
        flush_every_n_samples : int
            How often to flush both output files to disk.
        shared_start_monotonic : float
            Monotonic-clock reference from TelemetryPipeline.
            All 'monotonic_offset_s' values in output CSVs are offsets
            from this anchor so all four per-run CSVs share one time base.
            Pass 0.0 only in unit tests (degraded mode).
        """
        self.run_dir = Path(run_dir)
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.telemetry_queue = telemetry_queue
        self.flush_every_n_samples = flush_every_n_samples
        self.shared_start_monotonic = shared_start_monotonic

        self.derived_csv_path   = self.run_dir / "telemetry_derived.csv"
        self.decisions_csv_path = self.run_dir / "scheduler_decisions.csv"

        self._process: Optional[mp.Process] = None
        self._stop_event: Optional[mp.Event] = None
        self.scheduler_mode = scheduler_mode

    def start(self) -> None:
        if self._process is not None:
            raise RuntimeError("SchedulerRuntime already started")
        self._stop_event = mp.Event()
        self._process = mp.Process(
            target=_scheduler_worker,
            args=(
                str(self.derived_csv_path),
                str(self.decisions_csv_path),
                self.telemetry_queue,
                self._stop_event,
                self.flush_every_n_samples,
                self.shared_start_monotonic,
                self.scheduler_mode,
            ),
            daemon=False,
            name="scheduler_runtime",
        )
        self._process.start()

    def stop(self, timeout: float = 5.0) -> None:
        if self._process is None:
            return
        self._stop_event.set()
        self._process.join(timeout=timeout)
        if self._process.is_alive():
            self._process.terminate()
            self._process.join(timeout=1.0)
        self._process = None


# ---------------------------------------------------------------------------
# Worker process
# ---------------------------------------------------------------------------

def _scheduler_worker(
    derived_csv_path_str: str,
    decisions_csv_path_str: str,
    telemetry_queue: mp.Queue,
    stop_event: mp.Event,
    flush_every_n_samples: int,
    shared_start_monotonic: float,
    scheduler_mode: str = "proactive",   # "proactive" or "reactive_threshold"
) -> None:
    """
    Worker entry point. Runs in a separate process.

    Responsibilities:
      1. Drain telemetry_queue sample by sample.
      2. Feed each sample to StateVectorBuilder → state vector s(t).
      3. Pass T, T_dot, throttled_now to thermal_decide().
      4. If decision differs from current DVFS state, call
         dvfs_control.set_state_by_name() to apply the cap.
      5. Write every sample to telemetry_derived.csv.
      6. Write every decision to scheduler_decisions.csv.

    DVFS restoration on exit:
      restore_max() is called in the finally block so the frequency cap
      is always reset to S0 (2400 MHz) even if the worker crashes.
      run_thermal_validation.py also calls restore_max() in its own
      finally block — double restoration is safe (idempotent write).
    """

    def _handle_signal(signum, frame):
        stop_event.set()

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT,  _handle_signal)

    derived_path   = Path(derived_csv_path_str)
    decisions_path = Path(decisions_csv_path_str)

    # State vector builder (EMA derivatives, DEFAULT_CONFIG_2HZ)
    builder = StateVectorBuilder()

    # Task 12 policy state — one instance per run, lives in this process
    if scheduler_mode == "reactive_threshold":
        policy_state       = ReactiveThresholdState()
        current_dvfs_state = "S0"
    else:
        policy_state       = SchedulerState()
        current_dvfs_state = DvfsState.S0.value

    derived_file   = open(derived_path,   "w", newline="", encoding="utf-8")
    decisions_file = open(decisions_path, "w", newline="", encoding="utf-8")
    derived_writer   = csv.DictWriter(derived_file,   fieldnames=_DERIVED_FIELDNAMES)
    decisions_writer = csv.DictWriter(decisions_file, fieldnames=_DECISION_FIELDNAMES)
    derived_writer.writeheader()
    decisions_writer.writeheader()

    # Write boot-state row so decisions CSV always has an entry near t=0
    if shared_start_monotonic > 0.0:
        boot_offset = round(time.monotonic() - shared_start_monotonic, 6)
    else:
        boot_offset = 0.0

    _write_decision(
        decisions_writer,
        monotonic_offset_s = boot_offset,
        utc_timestamp      = datetime.now(timezone.utc).isoformat(),
        dvfs_state         = DvfsState.S0.value,
        reason             = "runtime_start_default",
        T                  = None,
        T_dot              = None,
        throttled_now      = None,
    )
    decisions_file.flush()

    sample_count = 0

    try:
        while not stop_event.is_set():
            try:
                sample = telemetry_queue.get(timeout=0.5)
            except queue_mod.Empty:
                continue

            # ---- state vector -----------------------------------------------
            state = builder.update(sample)

            derived_row = {
                "monotonic_offset_s": sample.get("monotonic_offset_s"),
                "utc_timestamp":      sample.get("utc_timestamp"),
                **{k: _round_or_none(v) for k, v in state.items()},
            }
            derived_writer.writerow(derived_row)

            # ---- Task 12 decision -------------------------------------------
            T_val   = state.get("T")
            T_dot_v = state.get("T_dot")
            thr_now = sample.get("throttled_now")

            if scheduler_mode == "reactive_threshold":
                new_state, reason = decide_reactive(
                    T             = T_val,
                    throttled_now = (int(thr_now) if thr_now is not None else None),
                    sched_state   = policy_state,
                    config        = DEFAULT_REACTIVE_CONFIG,
                )
            else:
                new_state, reason = thermal_decide(
                    T             = T_val,
                    T_dot         = T_dot_v,
                    throttled_now = (int(thr_now) if thr_now is not None else None),
                    sched_state   = policy_state,
                    config        = DEFAULT_SCHEDULER_CONFIG,
                    now_monotonic = sample.get("monotonic_offset_s"),
                )

            # ---- Apply DVFS if state changed --------------------------------
            if new_state.value != current_dvfs_state:
                try:
                    prev_dvfs_state = current_dvfs_state
                    set_state_by_name(new_state.value)
                    current_dvfs_state = new_state.value
                    log.info(
                        "DVFS applied: %s → %s  T=%.1f°C  T_dot=%s°C/s",
                        prev_dvfs_state, new_state.value,
                        T_val if T_val is not None else float("nan"),
                        f"{T_dot_v:.3f}" if T_dot_v is not None else "None",
                    )
                except DvfsError as exc:
                    log.error(
                        "DVFS apply failed (%s) — holding %s",
                        exc, current_dvfs_state,
                    )

            # ---- Log decision -----------------------------------------------
            _write_decision(
                decisions_writer,
                monotonic_offset_s = sample.get("monotonic_offset_s"),
                utc_timestamp      = sample.get("utc_timestamp"),
                dvfs_state         = new_state.value,
                reason             = reason.value,
                T                  = T_val,
                T_dot              = T_dot_v,
                throttled_now      = thr_now,
            )

            sample_count += 1
            if sample_count % flush_every_n_samples == 0:
                derived_file.flush()
                decisions_file.flush()

    except Exception as exc:          # pragma: no cover — defensive
        log.exception("scheduler worker crashed: %s", exc)
    finally:
        derived_file.flush()
        derived_file.close()
        decisions_file.flush()
        decisions_file.close()
        # Restore DVFS cap to S0 on any exit path
        try:
            restore_max()
            log.info("DVFS restored to S0 (2400 MHz) on worker exit.")
        except DvfsError as exc:
            log.error(
                "DVFS restore FAILED on worker exit: %s — "
                "run `sudo python dvfs_control.py --restore` manually.", exc
            )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_decision(
    writer,
    monotonic_offset_s,
    utc_timestamp,
    dvfs_state,
    reason,
    T,
    T_dot,
    throttled_now,
) -> None:
    writer.writerow({
        "monotonic_offset_s": monotonic_offset_s,
        "utc_timestamp":      utc_timestamp,
        "dvfs_state":         dvfs_state,
        "reason":             reason,
        "T":                  _round_or_none(T, 3),
        "T_dot":              _round_or_none(T_dot, 4),
        "throttled_now":      throttled_now,
    })


def _round_or_none(v, digits: int = 4):
    if v is None:
        return None
    try:
        return round(v, digits)
    except (TypeError, ValueError):
        return None