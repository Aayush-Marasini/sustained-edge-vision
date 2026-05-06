#!/usr/bin/env python3
"""
run_high_ambient.py
===================
High-ambient robustness demonstration run (paper §X Discussion).

Runs EITHER Static-S1 OR Proactive scheduler for 30 minutes at elevated
ambient temperature (~27°C). Adds "high_ambient" label to directory name
and run_metadata.json for analysis separation.

This is a SINGLE-REP demonstration run (n=1 per condition). Paper framing:
"In a single illustrative trial at T_amb ≈ 27°C, Static-S1 incurred N
throttle events, while the Proactive scheduler adapted to S2 and maintained
zero throttle events."

Usage
-----
  # Terminal 1: verify ambient ≥ 27°C with DHT11, then run S1 static
  sudo /home/raspberrypi/yolov8_env/bin/python \
      03_code/experiments/run_high_ambient.py --mode static_s1

  # After S1 run + cool-down to < 50°C, run proactive
  sudo /home/raspberrypi/yolov8_env/bin/python \
      03_code/experiments/run_high_ambient.py --mode proactive

Pre-run checklist (MANDATORY — same as normal runs)
----------------------------------------------------
  sudo rfkill block wifi
  rfkill list                    # verify: Soft blocked: yes
  python3 03_code/telemetry/dht11_smoketest.py   # must read ≥ 27°C
  cat /sys/class/thermal/thermal_zone0/temp       # must be < 65000 (high ambient: idle ~55-60°C is normal)

Target ambient: 27°C (±1°C).
DO NOT run at 29°C+ — S2 plateau at 29°C ≈ 79.2°C, < 1°C from throttle onset.
At 27°C: S1 plateau ≈ 83.8°C (definitely throttles), S2 plateau ≈ 77.2°C (safe).

Post-run
--------
  sudo chown -R raspberrypi:raspberrypi ~/sustained-edge-vision/05_results/runs/
  # Wait until temp < 65000 before next run (watch -n 15 'cat /sys/class/thermal/...')

PowerZ
------
  Start PowerZ BEFORE running this script.
  Name the recording: high_ambient_{mode}_rep1.db
  Stop when "HIGH AMBIENT RUN COMPLETE" prints.
"""
from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import os
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Path bootstrap — works from repo root or 03_code/experiments/
_THIS = Path(__file__).resolve()
for _candidate in [_THIS.parent.parent, _THIS.parent.parent.parent / "03_code"]:
    if (_candidate / "scheduler").exists():
        sys.path.insert(0, str(_candidate))
        break

from scheduler.dvfs_control import set_state_by_name, restore_max, DvfsError  # type: ignore
from telemetry.telemetry_pipeline import run_telemetry_pipeline               # type: ignore
from inference.inference_worker import inference_worker_main                   # type: ignore

# For proactive mode
try:
    from scheduler.scheduler_runtime import run_scheduler_runtime              # type: ignore
    from scheduler.reactive_threshold_scheduler import (                       # type: ignore
        DEFAULT_REACTIVE_CONFIG,
    )
    _SCHEDULER_AVAILABLE = True
except ImportError:
    _SCHEDULER_AVAILABLE = False

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REPO_ROOT = _THIS.parent.parent.parent  # sustained-edge-vision/
RESULTS_DIR = REPO_ROOT / "05_results" / "runs"
MODEL_PATH = REPO_ROOT / "02_models" / "openvino" / "yolov8n_fp32"
VIDEO_PATH = REPO_ROOT / "04_workload" / "videos" / "thermal_benchmark_30fps.mp4"
DHT11_GPIO_PIN = 4

DURATION_S = 1800          # 30 minutes
HIGH_AMBIENT_LABEL = "high_ambient"

STATIC_FREQ_MHZ = {
    "static_s1": 1800,
    "static_s2": 1500,  # included for optional S2 sanity check
    "static_s0": 2400,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def verify_prerequisites(model_path: Path, video_path: Path) -> None:
    """Abort with clear error if any required artifact is missing."""
    if not model_path.exists():
        raise FileNotFoundError(
            f"Model not found: {model_path}\n"
            "Expected yolov8n.xml + yolov8n.bin in that directory."
        )
    if not video_path.exists():
        raise FileNotFoundError(f"Benchmark video not found: {video_path}")

    # SHA256 check for benchmark video
    EXPECTED_VIDEO_SHA = "67fb8f1f06b21c693e74c140040f76e6f33a8b02062910c9384c704df0f8dab2"
    import hashlib
    sha = hashlib.sha256(video_path.read_bytes()).hexdigest()
    if sha != EXPECTED_VIDEO_SHA:
        raise RuntimeError(
            f"Benchmark video SHA256 mismatch!\n"
            f"  Expected: {EXPECTED_VIDEO_SHA}\n"
            f"  Got:      {sha}\n"
            "Do not run with wrong video."
        )

    temp_raw = Path("/sys/class/thermal/thermal_zone0/temp")
    if temp_raw.exists():
        t = int(temp_raw.read_text().strip()) / 1000.0
        if t >= 65.0:
            raise RuntimeError(
                f"Pi is too hot to start ({t:.1f}°C). "
                f"At high ambient, idle temp is 55-60°C — wait for cool-down below 65°C."
            )
        print(f"  SoC temperature: {t:.1f}°C ✓")

    wifi_blocked = _check_wifi_blocked()
    if not wifi_blocked:
        print("  WARNING: WiFi may not be blocked. Run: sudo rfkill block wifi")
        print("  Continuing anyway — verify rfkill list output.")


def _check_wifi_blocked() -> bool:
    try:
        import subprocess
        result = subprocess.run(
            ["rfkill", "list"], capture_output=True, text=True, timeout=5
        )
        return "Soft blocked: yes" in result.stdout
    except Exception:
        return False


def read_dht11_ambient(pin: int) -> float:
    """Read DHT11 ambient temperature. Returns 25.0°C as fallback on error."""
    try:
        import adafruit_dht
        import board
        dht = adafruit_dht.DHT11(board.D4)
        for _ in range(5):
            try:
                temp = dht.temperature
                if temp is not None:
                    return float(temp)
            except Exception:
                time.sleep(0.5)
        return 25.0
    except ImportError:
        # adafruit_dht not available — return fallback
        print("  WARNING: adafruit_dht not available, ambient recorded as 25.0°C")
        return 25.0


def make_run_directory(mode: str) -> Path:
    """Create timestamped run directory with high_ambient label."""
    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    if mode in STATIC_FREQ_MHZ:
        dir_name = f"{ts}_thermalval_{mode.upper().replace('STATIC_', '')}_{HIGH_AMBIENT_LABEL}"
    else:  # proactive
        dir_name = f"{ts}_scheduled_proactive_{HIGH_AMBIENT_LABEL}_rep1"

    run_dir = RESULTS_DIR / dir_name
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def write_metadata(
    run_dir: Path,
    mode: str,
    ambient_c: float,
    git_sha: str,
    start_time_utc: str,
) -> None:
    meta = {
        "run_id": run_dir.name,
        "start_time_utc": start_time_utc,
        "label": HIGH_AMBIENT_LABEL,
        "mode": mode,
        "scheduler_mode": "proactive" if mode == "proactive" else "static",
        "dvfs_state": STATIC_FREQ_MHZ.get(mode, "dynamic"),
        "duration_s": DURATION_S,
        "ambient_dht11_start": {"temperature_c": ambient_c},
        "git_sha": git_sha,
        "model_path": str(MODEL_PATH),
        "video_path": str(VIDEO_PATH),
        "rep": 1,
        "notes": (
            f"High-ambient robustness demonstration. "
            f"Target ambient ≥ 27°C. Mode: {mode}. "
            f"Framing: single illustrative trial for paper §X Discussion."
        ),
        "thermal_targets": {
            "ambient_target_c": 27.0,
            "static_s1_expected_plateau_c": 83.8,
            "s2_expected_plateau_c": 77.2,
            "throttle_onset_c": 80.0,
        },
    }
    path = run_dir / "run_metadata.json"
    path.write_text(json.dumps(meta, indent=2))


def get_git_sha() -> str:
    try:
        import subprocess
        r = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, cwd=str(REPO_ROOT)
        )
        return r.stdout.strip()[:12]
    except Exception:
        return "unknown"


# ---------------------------------------------------------------------------
# Static-S1 run
# ---------------------------------------------------------------------------

def run_static_s1(run_dir: Path, ambient_c: float) -> None:
    """
    Run Static-S1 (1800 MHz cap) for DURATION_S seconds.
    Mirrors run_thermal_validation.py logic for S1.
    """
    print(f"\n  Mode       : Static-S1 (1800 MHz cap)")
    print(f"  Ambient    : {ambient_c:.1f}°C")
    print(f"  Duration   : {DURATION_S}s")
    print(f"  Output dir : {run_dir}")

    # Apply S1 frequency cap
    try:
        set_state_by_name("S1")
        print("  DVFS       : S1 (1800 MHz) — applied ✓")
    except DvfsError as e:
        raise RuntimeError(f"Failed to set S1 frequency: {e}")

    start_monotonic = time.monotonic()
    start_utc = datetime.now(timezone.utc).isoformat()

    write_metadata(run_dir, "static_s1", ambient_c, get_git_sha(), start_utc)

    stop_event = mp.Event()

    # Launch telemetry process
    telem_proc = mp.Process(
        target=run_telemetry_pipeline,
        kwargs={
            "output_dir": str(run_dir),
            "duration_s": DURATION_S,
            "sampling_rate_hz": 2.0,
            "dht11_gpio_pin": DHT11_GPIO_PIN,
            "shared_start_monotonic": start_monotonic,
            "stop_event": stop_event,
        },
        daemon=True,
    )
    telem_proc.start()

    # Launch inference process
    inf_proc = mp.Process(
        target=inference_worker_main,
        args=(
            str(MODEL_PATH),
            str(VIDEO_PATH),
            str(run_dir / "inference_log.csv"),
            stop_event,
            start_monotonic,
        ),
        daemon=True,
    )
    inf_proc.start()

    try:
        print(f"\n  HIGH AMBIENT STATIC-S1 RUN STARTED — running {DURATION_S}s ...")
        _countdown(DURATION_S)
    finally:
        stop_event.set()
        inf_proc.join(timeout=10.0)
        if inf_proc.is_alive():
            inf_proc.terminate()
        telem_proc.join(timeout=10.0)
        if telem_proc.is_alive():
            telem_proc.terminate()
        # ALWAYS restore S0 on exit
        restore_max()

    # Finalize metadata with end time
    meta_path = run_dir / "run_metadata.json"
    meta = json.loads(meta_path.read_text())
    meta["end_time_utc"] = datetime.now(timezone.utc).isoformat()
    meta_path.write_text(json.dumps(meta, indent=2))

    print(f"\n  HIGH AMBIENT RUN COMPLETE — results in {run_dir}")


# ---------------------------------------------------------------------------
# Proactive run
# ---------------------------------------------------------------------------

def run_proactive(run_dir: Path, ambient_c: float) -> None:
    """
    Run Proactive scheduler for DURATION_S seconds at elevated ambient.
    Uses same scheduler config as main paper runs (DEFAULT_SCHEDULER_CONFIG).
    """
    if not _SCHEDULER_AVAILABLE:
        raise ImportError(
            "Scheduler modules not importable. Check sys.path and venv."
        )

    print(f"\n  Mode       : Proactive Scheduler")
    print(f"  Ambient    : {ambient_c:.1f}°C")
    print(f"  Duration   : {DURATION_S}s")
    print(f"  Output dir : {run_dir}")

    start_monotonic = time.monotonic()
    start_utc = datetime.now(timezone.utc).isoformat()

    write_metadata(run_dir, "proactive", ambient_c, get_git_sha(), start_utc)

    stop_event = mp.Event()
    telemetry_queue = mp.Queue(maxsize=100)

    # Launch telemetry process
    telem_proc = mp.Process(
        target=run_telemetry_pipeline,
        kwargs={
            "output_dir": str(run_dir),
            "duration_s": DURATION_S,
            "sampling_rate_hz": 2.0,
            "dht11_gpio_pin": DHT11_GPIO_PIN,
            "shared_start_monotonic": start_monotonic,
            "stop_event": stop_event,
            "output_queue": telemetry_queue,
        },
        daemon=True,
    )
    telem_proc.start()

    # Launch scheduler process
    sched_proc = mp.Process(
        target=run_scheduler_runtime,
        kwargs={
            "telemetry_queue": telemetry_queue,
            "output_dir": str(run_dir),
            "scheduler_mode": "proactive",
            "shared_start_monotonic": start_monotonic,
            "stop_event": stop_event,
        },
        daemon=True,
    )
    sched_proc.start()

    # Launch inference process
    inf_proc = mp.Process(
        target=inference_worker_main,
        args=(
            str(MODEL_PATH),
            str(VIDEO_PATH),
            str(run_dir / "inference_log.csv"),
            stop_event,
            start_monotonic,
        ),
        daemon=True,
    )
    inf_proc.start()

    try:
        print(f"\n  HIGH AMBIENT PROACTIVE RUN STARTED — running {DURATION_S}s ...")
        _countdown(DURATION_S)
    finally:
        stop_event.set()
        # Shutdown order: inference → scheduler → telemetry
        inf_proc.join(timeout=10.0)
        if inf_proc.is_alive():
            inf_proc.terminate()
        sched_proc.join(timeout=10.0)
        if sched_proc.is_alive():
            sched_proc.terminate()
        telem_proc.join(timeout=10.0)
        if telem_proc.is_alive():
            telem_proc.terminate()
        restore_max()

    meta_path = run_dir / "run_metadata.json"
    meta = json.loads(meta_path.read_text())
    meta["end_time_utc"] = datetime.now(timezone.utc).isoformat()
    meta_path.write_text(json.dumps(meta, indent=2))

    print(f"\n  HIGH AMBIENT RUN COMPLETE — results in {run_dir}")


# ---------------------------------------------------------------------------
# Countdown helper
# ---------------------------------------------------------------------------

def _countdown(total_s: int) -> None:
    """Print progress every 5 minutes."""
    interval = 300  # 5 min
    elapsed = 0
    while elapsed < total_s:
        sleep_chunk = min(interval, total_s - elapsed)
        time.sleep(sleep_chunk)
        elapsed += sleep_chunk
        remaining = total_s - elapsed
        mins_done = elapsed // 60
        mins_left = remaining // 60
        temp_raw = Path("/sys/class/thermal/thermal_zone0/temp")
        t_str = ""
        if temp_raw.exists():
            t = int(temp_raw.read_text().strip()) / 1000.0
            t_str = f"  SoC={t:.1f}°C"
        print(f"  [{mins_done:02d}/{total_s//60:02d} min]{t_str}  remaining={mins_left}min")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="High-ambient robustness run (paper §X Discussion, n=1 illustrative trial)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Modes:
  static_s1  — Cap at 1800 MHz for 30 min. Expected result: heavy throttle at 27°C ambient.
  proactive  — Run proactive scheduler for 30 min. Expected: 0 throttle, adapts to S2.
  static_s2  — Optional sanity check: verify S2 does not throttle at target ambient.

Target ambient: 27°C (NOT 29°C+ — S2 margin becomes < 1°C at 29°C).
""",
    )
    parser.add_argument(
        "--mode",
        choices=["static_s1", "proactive", "static_s2"],
        required=True,
        help="Experiment mode",
    )
    parser.add_argument(
        "--skip-sha-check",
        action="store_true",
        help="Skip video SHA256 verification (use only if you know what you're doing)",
    )
    args = parser.parse_args()

    print("\n" + "=" * 60)
    print("  HIGH AMBIENT ROBUSTNESS EXPERIMENT")
    print(f"  Mode: {args.mode}")
    print("=" * 60)

    # Prerequisite checks
    if not args.skip_sha_check:
        verify_prerequisites(MODEL_PATH, VIDEO_PATH)
    else:
        print("  WARNING: SHA256 check skipped")

    # Read ambient
    print("\n  Reading DHT11 ambient temperature...")
    ambient_c = read_dht11_ambient(DHT11_GPIO_PIN)
    print(f"  Ambient: {ambient_c:.1f}°C")

    if ambient_c < 26.0:
        print(
            f"\n  WARNING: Ambient is only {ambient_c:.1f}°C — target is ≥ 27°C.\n"
            "  S1 may not throttle at low ambient. Wait for room to warm up.\n"
            "  Continue anyway? (ctrl-C to abort, Enter to continue)"
        )
        try:
            input()
        except KeyboardInterrupt:
            print("  Aborted.")
            sys.exit(0)

    if ambient_c > 29.0:
        print(
            f"\n  ERROR: Ambient is {ambient_c:.1f}°C — ABOVE safe limit (29°C).\n"
            "  At 29°C+, S2 plateau approaches throttle onset.\n"
            "  Proactive scheduler may also throttle. Aborting.\n"
            "  Target 27°C for safe margin."
        )
        sys.exit(1)

    # Create run directory
    run_dir = make_run_directory(args.mode)

    try:
        mp.set_start_method("fork", force=True)  # fork is faster on Pi Linux
    except RuntimeError:
        pass  # already set

    if args.mode == "static_s1":
        run_static_s1(run_dir, ambient_c)
    elif args.mode == "static_s2":
        # Reuse static_s1 logic but with S2
        print("  Running Static-S2 sanity check at elevated ambient...")
        # Set S2 directly
        set_state_by_name("S2")
        # (simplified — run_static_s1 with S2 freq for sanity check)
        # For a proper S2 sanity check, adapt run_static_s1 or call run_thermal_validation.py
        print("  Use run_thermal_validation.py --state S2 for full S2 sanity check.")
        restore_max()
        sys.exit(0)
    elif args.mode == "proactive":
        run_proactive(run_dir, ambient_c)


if __name__ == "__main__":
    main()