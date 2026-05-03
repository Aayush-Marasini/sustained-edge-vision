"""
run_scheduled_experiment.py
===========================
Full experiment harness WITH active scheduler.

Replaces run_experiment.py for all Task 21+ runs.
run_experiment.py still exists and still works for passive/baseline
runs that do NOT need live DVFS switching.

Architecture
------------
Parent process creates one multiprocessing.Queue. Both TelemetryPipeline
and SchedulerRuntime receive it at construction time, before either is
started. This guarantees the Queue handle is inherited via fork.

Data flow:
  TelemetryPipeline → Queue → SchedulerRuntime → dvfs_control → sysfs
                    ↓                          ↓
              telemetry_raw.csv    telemetry_derived.csv
                                   scheduler_decisions.csv
  inference_worker → inference_log.csv

WorkPlan grounding
------------------
- Task 21 (§8.2): pilot test — use this harness
- Task 22 (§8.3): 30-min long-horizon experiments — use this harness
- Task 18 (§7.2): baselines — use run_experiment.py (no scheduler)

Usage
-----
    sudo /home/raspberrypi/yolov8_env/bin/python \\
        03_code/experiments/run_scheduled_experiment.py \\
        --state S0 \\
        --duration 600 \\
        --ambient-temp-c 23.0 \\
        --dht11-pin 4 \\
        --workload high \\
        --rep 1

    # --state: starting DVFS state. Scheduler may change it during run.
    # For baselines that should NOT switch, use run_experiment.py instead.
"""
from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

_THIS      = Path(__file__).resolve()
_CODE_ROOT = _THIS.parent.parent          # 03_code/
_REPO_ROOT = _CODE_ROOT.parent            # repo root
sys.path.insert(0, str(_CODE_ROOT))

from inference.inference_worker import inference_worker_main          # type: ignore
from telemetry.telemetry_pipeline import TelemetryPipeline            # type: ignore
from scheduler.scheduler_runtime import SchedulerRuntime              # type: ignore
from scheduler.dvfs_control import (                                   # type: ignore
    DvfsError, STATES, restore_max, set_state_by_name,
)

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
DEFAULT_MODEL = _REPO_ROOT / "02_models" / "openvino" / "yolov8n_fp32"
DEFAULT_VIDEO = _REPO_ROOT / "04_workload" / "videos" / "thermal_benchmark_30fps.mp4"
PRECONDITION_MAX_START_TEMP_C = 50.0


def _read_soc_temp_c() -> float:
    raw = Path("/sys/class/thermal/thermal_zone0/temp").read_text(encoding="utf-8")
    return int(raw.strip()) / 1000.0


def _check_preconditions(args: argparse.Namespace) -> None:
    """Hard-fail on protocol violations before any process is started."""
    from scheduler.dvfs_control import get_governor
    gov = get_governor()
    if gov != "ondemand":
        sys.exit(f"PROTOCOL: governor='{gov}', expected 'ondemand'.")
    t = _read_soc_temp_c()
    if t > PRECONDITION_MAX_START_TEMP_C:
        sys.exit(
            f"THERMAL PRECONDITION: SoC={t:.1f}°C > {PRECONDITION_MAX_START_TEMP_C}°C. "
            f"Wait for cooldown."
        )
    print(f"[precond] governor=ondemand ✓  SoC={t:.1f}°C ✓")
    if not DEFAULT_VIDEO.exists():
        sys.exit(f"Video missing: {DEFAULT_VIDEO}")
    if not (DEFAULT_MODEL / "yolov8n.xml").exists():
        sys.exit(f"Model missing: {DEFAULT_MODEL}")


def main() -> int:
    p = argparse.ArgumentParser(description="Scheduled inference experiment.")
    p.add_argument("--state",          default="S0", choices=["S0","S1","S2"],
                   help="Initial DVFS state. Scheduler may change it.")
    p.add_argument("--duration",       type=float, default=600.0,
                   help="Run duration in seconds (default: 600 = 10 min).")
    p.add_argument("--ambient-temp-c", type=float, required=True)
    p.add_argument("--dht11-pin",      type=int, default=4)
    p.add_argument("--workload",       default="high",
                   choices=["high","medium","low"],
                   help="Workload descriptor for metadata tagging.")
    p.add_argument("--rep",            type=int, required=True)
    p.add_argument("--model",          type=Path, default=DEFAULT_MODEL)
    p.add_argument("--video",          type=Path, default=DEFAULT_VIDEO)
    p.add_argument("--sampling-rate-hz", type=float, default=2.0)
    args = p.parse_args()

    # ---- preflight ----------------------------------------------------------
    _check_preconditions(args)

    # ---- run directory ------------------------------------------------------
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")
    run_name = f"{ts}_scheduled_{args.workload}_S{args.state[1]}_rep{args.rep}"
    run_dir  = _REPO_ROOT / "05_results" / "runs" / run_name
    run_dir.mkdir(parents=True, exist_ok=True)
    print(f"Run directory: {run_dir}")

    # ---- set initial DVFS state before any process starts -------------------
    try:
        caps = set_state_by_name(args.state)
        print(f"[dvfs] Initial state {args.state}: {caps}")
    except DvfsError as e:
        sys.exit(f"DVFS setup failed: {e}")

    # ---- the Queue: created HERE, in parent, before any fork ----------------
    # This is why run_scheduled_experiment.py must be the parent.
    # Both TelemetryPipeline and SchedulerRuntime receive this handle
    # at construction; it is inherited when mp.Process forks.
    telemetry_queue: mp.Queue = mp.Queue(maxsize=200)

    tags: Dict[str, Any] = {
        "workload":           f"{args.workload}_stress",
        "phase":              "task21_pilot" if args.duration <= 700 else "task22_longrun",
        "dvfs_initial_state": args.state,
        "scheduler":          "proactive_thermal",
        "rep":                args.rep,
        "duration_min":       int(args.duration / 60),
    }

    # ---- build processes ----------------------------------------------------
    # IMPORTANT: all three are constructed before any is started.
    # This ensures shared_start_monotonic is passed consistently.
    # We use a mp.Value to share the exact start monotonic across processes.
    shared_start = mp.Value("d", 0.0)  # double, initially 0.0

    telemetry = TelemetryPipeline(
        run_dir          = str(run_dir),
        sampling_rate_hz = args.sampling_rate_hz,
        duration_sec     = args.duration,
        ambient_temp_c   = args.ambient_temp_c,
        cooling_condition= "passive",
        tags             = tags,
        scheduler_queue  = telemetry_queue,
        dht11_pin        = args.dht11_pin,
    )

    stop_inference = mp.Event()
    inference_csv  = run_dir / "inference_log.csv"
    inference_proc = mp.Process(
        target = inference_worker_main,
        args   = (
            str(args.model),
            str(args.video),
            str(inference_csv),
            stop_inference,
            0.0,   # shared_start_monotonic placeholder; overwritten below
        ),
        name = "inference_worker",
    )

    # ---- start telemetry first, get its monotonic reference -----------------
    print("Starting telemetry...")
    shared_start_monotonic = telemetry.start()   # returns float (monotonic)
    print(f"Shared start monotonic: {shared_start_monotonic:.6f}")

    # ---- start scheduler with same time reference ---------------------------
    scheduler = SchedulerRuntime(
        run_dir                = str(run_dir),
        telemetry_queue        = telemetry_queue,
        shared_start_monotonic = shared_start_monotonic,
    )
    print("Starting scheduler...")
    scheduler.start()

    # ---- start inference ----------------------------------------------------
    print("Starting inference...")
    inference_proc = mp.Process(
        target = inference_worker_main,
        args   = (
            str(args.model),
            str(args.video),
            str(inference_csv),
            stop_inference,
            shared_start_monotonic,
        ),
        name = "inference_worker",
    )
    inference_proc.start()

    print(f"Pipeline running for {args.duration}s. All three workers active.")
    print("─" * 60)

    # ---- wait ---------------------------------------------------------------
    try:
        time.sleep(args.duration)
    except KeyboardInterrupt:
        print("\nKeyboardInterrupt — shutting down gracefully...")

    # ---- shutdown sequence --------------------------------------------------
    print("\nStopping inference...")
    stop_inference.set()
    inference_proc.join(timeout=5.0)
    if inference_proc.is_alive():
        print("WARNING: inference worker did not stop cleanly — terminating.")
        inference_proc.terminate()
        inference_proc.join(timeout=2.0)

    print("Stopping scheduler...")
    scheduler.stop(timeout=10.0)    # scheduler's finally block restores DVFS

    print("Stopping telemetry...")
    telemetry.stop()

    # ---- verify DVFS restored -----------------------------------------------
    try:
        from scheduler.dvfs_control import get_current_cap_khz
        caps = get_current_cap_khz()
        all_restored = all(v == 2_400_000 for v in caps.values())
        if all_restored:
            print("[dvfs] Cap verified restored to S0 (2400000 kHz) ✓")
        else:
            print(f"[dvfs] WARNING: cap not fully restored: {caps}")
            print("[dvfs] Run: sudo python 03_code/scheduler/dvfs_control.py --restore")
    except Exception as e:
        print(f"[dvfs] Restore verification failed: {e}")

    # ---- post-run ownership fix (prevents git pull permission errors) --------
    import subprocess
    subprocess.run(
        ["sudo", "chown", "-R", "raspberrypi:raspberrypi", str(run_dir)],
        check=False
    )

    print("=" * 60)
    print(f"EXPERIMENT COMPLETE. Results in: {run_dir}")
    print(f"  telemetry_raw.csv")
    print(f"  telemetry_derived.csv")
    print(f"  scheduler_decisions.csv")
    print(f"  inference_log.csv")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    mp.set_start_method("spawn", force=True)
    sys.exit(main())