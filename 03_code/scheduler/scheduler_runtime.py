"""
scheduler_runtime.py
====================
Minimal scheduler runtime showing how telemetry, derivatives, and
(future) policy logic connect.

Scope
-----
This file delivers the *consumer plumbing* for Task 10 -> Task 11
handoff: it drains the telemetry queue, runs the state-vector builder,
and writes telemetry_derived.csv and scheduler_decisions.csv. It does
NOT yet implement the full decision policy c*(t) = arg min (...) from
proposal_v2.pdf §5. That arrives in Task 12 and will replace the
placeholder _decide_config() below.

Grounding
---------
- WorkPlan_marked.pdf Task 11 (§6.3): implement the scheduler state
  representation; test signal stability under idle and stress.
- WorkPlan_marked.pdf Task 12 (§6.4): implement the decision policy
  with hysteresis and dwell-time safeguards. [PENDING]
- proposal_v2.pdf §4: state vector s(t).
- proposal_v2.pdf §5: dynamic cost function. [PENDING - placeholder]

Usage (single-machine demo)
---------------------------
    import multiprocessing as mp
    from telemetry_pipeline import TelemetryPipeline
    from scheduler_runtime import SchedulerRuntime

    q = mp.Queue(maxsize=100)
    tel = TelemetryPipeline(run_dir="05_results/runs/foo", scheduler_queue=q)
    tel.start()

    sched = SchedulerRuntime(run_dir="05_results/runs/foo", telemetry_queue=q)
    sched.start()

    time.sleep(60)

    sched.stop()
    tel.stop()
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

from scheduler.derivatives import StateVectorBuilder  # type: ignore

log = logging.getLogger(__name__)


# Columns of telemetry_derived.csv. Stable; do not change silently.
_DERIVED_FIELDNAMES = [
    "monotonic_offset_s",
    "utc_timestamp",
    "T", "T_dot",
    "U", "U_dot",
    "V", "V_dot",
    "f", "f_dot",
    "mem",
]

# Columns of scheduler_decisions.csv. Stable; do not change silently.
_DECISION_FIELDNAMES = [
    "monotonic_offset_s",
    "utc_timestamp",
    "config_resolution",
    "config_precision",
    "config_fps_cap",
    "reason",
]


class SchedulerRuntime:
    """
    Drains the telemetry queue, computes the state vector, and writes
    two sibling CSVs (derived telemetry and scheduler decisions).
    """

    def __init__(
        self,
        run_dir: str,
        telemetry_queue: mp.Queue,
        flush_every_n_samples: int = 10,
        shared_start_monotonic: float = 0.0,
    ):
        """
        shared_start_monotonic : float
            The telemetry pipeline's monotonic-clock start reference
            (from TelemetryPipeline.shared_start_monotonic). All
            'monotonic_offset_s' values in scheduler_decisions.csv will
            be expressed relative to this anchor, so the four per-run
            CSVs (telemetry_raw, telemetry_derived, scheduler_decisions,
            inference_events) share a common time base. If 0.0, the
            scheduler will fall back to its own time origin (degraded;
            only acceptable for unit tests).
        """
        self.run_dir = Path(run_dir)
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.telemetry_queue = telemetry_queue
        self.flush_every_n_samples = flush_every_n_samples
        self.shared_start_monotonic = shared_start_monotonic

        self.derived_csv_path = self.run_dir / "telemetry_derived.csv"
        self.decisions_csv_path = self.run_dir / "scheduler_decisions.csv"

        self._process: Optional[mp.Process] = None
        self._stop_event: Optional[mp.Event] = None

    def start(self) -> None:
        if self._process is not None:
            raise RuntimeError("SchedulerRuntime already started")

        self._stop_event = mp.Event()
        self._process = mp.Process(
            target=_scheduler_worker_entry,
            args=(
                str(self.derived_csv_path),
                str(self.decisions_csv_path),
                self.telemetry_queue,
                self._stop_event,
                self.flush_every_n_samples,
                self.shared_start_monotonic,
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


# -- Worker process -----------------------------------------------------------


# Placeholder configuration (Task 12 will replace this entire mechanism).
_DEFAULT_CONFIG = {
    "config_resolution": 640,
    "config_precision": "int8",
    "config_fps_cap": 30,
}


def _scheduler_worker_entry(
    derived_csv_path_str: str,
    decisions_csv_path_str: str,
    telemetry_queue: mp.Queue,
    stop_event: mp.Event,
    flush_every_n_samples: int,
    shared_start_monotonic: float,
) -> None:
    """Worker entry point: drain queue, compute derivatives, log both files."""

    def _handle_signal(signum, frame):
        stop_event.set()

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    derived_path = Path(derived_csv_path_str)
    decisions_path = Path(decisions_csv_path_str)

    builder = StateVectorBuilder()

    derived_file = open(derived_path, "w", newline="", encoding="utf-8")
    derived_writer = csv.DictWriter(derived_file, fieldnames=_DERIVED_FIELDNAMES)
    derived_writer.writeheader()

    decisions_file = open(decisions_path, "w", newline="", encoding="utf-8")
    decisions_writer = csv.DictWriter(decisions_file, fieldnames=_DECISION_FIELDNAMES)
    decisions_writer.writeheader()

    # Log the initial (default) configuration so the decisions CSV always
    # has an entry near t=0. Use telemetry's shared monotonic reference
    # if provided, so this row aligns with telemetry_raw.csv. If the
    # caller did not supply one (degraded mode, e.g. unit tests), fall
    # back to a 0.0 offset and a UTC timestamp.
    if shared_start_monotonic > 0.0:
        boot_offset = round(time.monotonic() - shared_start_monotonic, 6)
    else:
        boot_offset = 0.0
    _write_decision(
        decisions_writer,
        monotonic_offset_s=boot_offset,
        utc_timestamp=datetime.now(timezone.utc).isoformat(),
        config=_DEFAULT_CONFIG,
        reason="runtime_start_default",
    )
    decisions_file.flush()

    current_config = dict(_DEFAULT_CONFIG)
    sample_count = 0

    try:
        while not stop_event.is_set():
            try:
                sample = telemetry_queue.get(timeout=0.5)
            except queue_mod.Empty:
                continue

            state = builder.update(sample)

            derived_row = {
                "monotonic_offset_s": sample.get("monotonic_offset_s"),
                "utc_timestamp": sample.get("utc_timestamp"),
                **{k: _round_or_none(v) for k, v in state.items()},
            }
            derived_writer.writerow(derived_row)

            # Placeholder decision logic. Task 12 will replace this with
            # the proposal §5 cost function, hysteresis, and dwell-time
            # safeguards.
            new_config, reason = _decide_config_placeholder(state, current_config)
            if new_config != current_config:
                _write_decision(
                    decisions_writer,
                    monotonic_offset_s=sample.get("monotonic_offset_s"),
                    utc_timestamp=sample.get("utc_timestamp"),
                    config=new_config,
                    reason=reason,
                )
                current_config = new_config

            sample_count += 1
            if sample_count % flush_every_n_samples == 0:
                derived_file.flush()
                decisions_file.flush()

    except Exception as exc:  # pragma: no cover - defensive
        log.exception("scheduler worker crashed: %s", exc)
    finally:
        derived_file.flush()
        derived_file.close()
        decisions_file.flush()
        decisions_file.close()


def _decide_config_placeholder(
    state: Dict[str, Optional[float]],
    current_config: Dict,
) -> tuple:
    """
    PLACEHOLDER for Task 12. Currently never changes configuration.
    Present only so the plumbing can be tested end-to-end before the
    real policy lands.
    """
    return current_config, "unchanged"


def _write_decision(writer, monotonic_offset_s, utc_timestamp, config, reason):
    writer.writerow({
        "monotonic_offset_s": monotonic_offset_s,
        "utc_timestamp": utc_timestamp,
        "config_resolution": config["config_resolution"],
        "config_precision": config["config_precision"],
        "config_fps_cap": config["config_fps_cap"],
        "reason": reason,
    })


def _round_or_none(v, digits: int = 4):
    if v is None:
        return None
    try:
        return round(v, digits)
    except (TypeError, ValueError):
        return None