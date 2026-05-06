#!/usr/bin/env python3
"""
run_high_ambient.py
===================
High-ambient robustness demonstration (paper §X Discussion, n=1).

Paper claim: "In a single illustrative trial at T_amb ≈ 31°C, Static-S1
incurred N throttle events. The proactive scheduler adapted to S2 and
incurred zero (or significantly fewer) throttle events — demonstrating
workload-agnostic thermal resilience under elevated ambient conditions."

Usage
-----
  # S1 static first (start PowerZ: name = high_ambient_S1_rep1.db)
  sudo /home/raspberrypi/yolov8_env/bin/python \
      03_code/experiments/run_high_ambient.py --mode static_s1

  # After cooldown, proactive (start PowerZ: name = high_ambient_proactive_rep1.db)
  sudo /home/raspberrypi/yolov8_env/bin/python \
      03_code/experiments/run_high_ambient.py --mode proactive

Pre-run checklist
-----------------
  sudo rfkill block wifi
  rfkill list                        # Soft blocked: yes
  python3 03_code/telemetry/dht11_smoketest.py
  cat /sys/class/thermal/thermal_zone0/temp   # < 65000 is fine at high ambient

Cooldown between runs
---------------------
  At 31 C ambient, idle SoC stabilises at 59-62 C. Do NOT wait for 50 C --
  it will never reach it at this ambient. Wait for the temperature reading to
  stop falling and hold steady for 60 consecutive seconds.

  watch -n 15 'echo "$(date +%H:%M:%S)  $(cat /sys/class/thermal/thermal_zone0/temp)"'

  After run completes:
  sudo chown -R raspberrypi:raspberrypi ~/sustained-edge-vision/05_results/runs/
"""
from __future__ import annotations

import argparse
import hashlib
import json
import multiprocessing as mp
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

# ---------------------------------------------------------------------------
# Path bootstrap
# ---------------------------------------------------------------------------
_THIS      = Path(__file__).resolve()
_CODE_ROOT = _THIS.parent.parent      # 03_code/
_REPO_ROOT = _CODE_ROOT.parent        # sustained-edge-vision/
sys.path.insert(0, str(_CODE_ROOT))

from telemetry.telemetry_pipeline import TelemetryPipeline          # type: ignore
from inference.inference_worker   import inference_worker_main       # type: ignore
from scheduler.scheduler_runtime  import SchedulerRuntime            # type: ignore
from scheduler.dvfs_control       import set_state_by_name, restore_max  # type: ignore

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
RESULTS_DIR       = _REPO_ROOT / "05_results" / "runs"
MODEL_PATH        = _REPO_ROOT / "02_models"  / "openvino" / "yolov8n_fp32"
VIDEO_PATH        = _REPO_ROOT / "04_workload" / "videos"  / "thermal_benchmark_30fps.mp4"
DHT11_PIN         = 4
DURATION_S        = 1800     # 30 minutes
LABEL             = "high_ambient"
MAX_START_TEMP_C  = 65.0     # idle SoC at 31 C ambient is ~59-62 C; 65 C is the safe ceiling

EXPECTED_VIDEO_SHA = "67fb8f1f06b21c693e74c140040f76e6f33a8b02062910c9384c704df0f8dab2"


# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------

def check_prerequisites(skip_sha: bool = False) -> None:
    if not (MODEL_PATH / "yolov8n.xml").exists():
        sys.exit(f"Model XML missing: {MODEL_PATH / 'yolov8n.xml'}")

    if not VIDEO_PATH.exists():
        sys.exit(f"Benchmark video missing: {VIDEO_PATH}")

    if not skip_sha:
        print("  Verifying video SHA256 ...", end=" ", flush=True)
        sha = hashlib.sha256(VIDEO_PATH.read_bytes()).hexdigest()
        if sha != EXPECTED_VIDEO_SHA:
            sys.exit(
                f"\nVideo SHA256 mismatch!\n"
                f"  Expected: {EXPECTED_VIDEO_SHA}\n"
                f"  Got:      {sha}"
            )
        print("OK")

    soc_c = int(Path("/sys/class/thermal/thermal_zone0/temp").read_text().strip()) / 1000.0
    print(f"  SoC temperature: {soc_c:.1f} C", end="")
    if soc_c >= MAX_START_TEMP_C:
        sys.exit(
            f"\n  SoC is {soc_c:.1f} C -- above {MAX_START_TEMP_C} C ceiling.\n"
            "  Wait for the Pi to cool down before starting."
        )
    print("  OK")

    try:
        out = subprocess.run(["rfkill", "list"], capture_output=True, text=True).stdout
        if "Soft blocked: yes" in out:
            print("  WiFi: Soft blocked OK")
        else:
            print("  WARNING: WiFi may not be blocked. Run: sudo rfkill block wifi")
    except Exception:
        print("  WARNING: Could not verify WiFi block status.")


def read_ambient() -> float:
    try:
        import adafruit_dht, board
        dht = adafruit_dht.DHT11(board.D4)
        for _ in range(5):
            try:
                t = dht.temperature
                if t is not None:
                    return float(t)
            except Exception:
                time.sleep(0.5)
    except ImportError:
        pass
    print("  WARNING: Could not read DHT11. Recording ambient as 25.0 C.")
    return 25.0


def make_run_dir(mode: str) -> Path:
    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    name = (
        f"{ts}_thermalval_S1_{LABEL}_rep1"
        if mode == "static_s1"
        else f"{ts}_scheduled_high_S0_{LABEL}_rep1"
    )
    d = RESULTS_DIR / name
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_git_sha() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, cwd=str(_REPO_ROOT),
        ).stdout.strip()[:12]
    except Exception:
        return "unknown"


def write_metadata(run_dir: Path, mode: str, ambient_c: float) -> None:
    meta: Dict[str, Any] = {
        "run_id":              run_dir.name,
        "start_time_utc":      datetime.now(timezone.utc).isoformat(),
        "label":               LABEL,
        "mode":                mode,
        "scheduler_mode":      "proactive" if mode == "proactive" else "static",
        "duration_s":          DURATION_S,
        "rep":                 1,
        "ambient_dht11_start": {"temperature_c": ambient_c},
        "git_sha":             get_git_sha(),
        "notes": (
            f"High-ambient robustness demo. Ambient={ambient_c:.1f} C. "
            f"Mode={mode}. Expected: S1 throttles; proactive adapts to S2."
        ),
    }
    (run_dir / "run_metadata.json").write_text(json.dumps(meta, indent=2))


def finalise_metadata(run_dir: Path) -> None:
    p = run_dir / "run_metadata.json"
    m = json.loads(p.read_text())
    m["end_time_utc"] = datetime.now(timezone.utc).isoformat()
    p.write_text(json.dumps(m, indent=2))


# ---------------------------------------------------------------------------
# Static-S1 run
# ---------------------------------------------------------------------------

def run_static_s1(ambient_c: float) -> None:
    run_dir = make_run_dir("static_s1")
    print(f"\n  Run dir : {run_dir}")
    print(f"  Ambient : {ambient_c:.1f} C")

    # Hard-cap CPUs at 1800 MHz (S1) before spawning anything
    set_state_by_name("S1")
    print("  DVFS    : S1 (1800 MHz) applied")

    write_metadata(run_dir, "static_s1", ambient_c)

    # TelemetryPipeline owns its own process internally.
    # duration_sec means it auto-stops; no scheduler_queue needed for static.
    telemetry = TelemetryPipeline(
        run_dir           = str(run_dir),
        sampling_rate_hz  = 2.0,
        duration_sec      = DURATION_S,
        ambient_temp_c    = ambient_c,
        cooling_condition = "passive",
        tags              = {"label": LABEL, "mode": "static_s1"},
        dht11_pin         = DHT11_PIN,
    )

    stop_inference = mp.Event()
    inf_proc = mp.Process(
        target = inference_worker_main,
        args   = (
            str(MODEL_PATH),
            str(VIDEO_PATH),
            str(run_dir / "inference_log.csv"),
            stop_inference,
            None,   # shared_start_monotonic: telemetry will provide it
        ),
        name = "inference_worker",
    )

    try:
        print("  Starting telemetry ...")
        shared_start = telemetry.start()   # <-- returns float, the monotonic anchor
        print(f"  shared_start_monotonic = {shared_start:.4f}")

        # Restart inference proc with correct shared_start now that we have it
        inf_proc = mp.Process(
            target = inference_worker_main,
            args   = (
                str(MODEL_PATH),
                str(VIDEO_PATH),
                str(run_dir / "inference_log.csv"),
                stop_inference,
                shared_start,
            ),
            name = "inference_worker",
        )
        print("  Starting inference ...")
        inf_proc.start()

        print(f"\n  *** HIGH AMBIENT STATIC-S1 RUN STARTED ***\n")
        _wait_with_progress(DURATION_S)

    finally:
        stop_inference.set()
        inf_proc.join(timeout=10.0)
        if inf_proc.is_alive():
            print("  WARNING: inference worker still alive -- terminating.")
            inf_proc.terminate()
            inf_proc.join()

        telemetry.stop()
        restore_max()
        print("  DVFS restored to S0 (2400 MHz)")

    finalise_metadata(run_dir)
    print(f"\n  *** HIGH AMBIENT RUN COMPLETE *** -> {run_dir}\n")


# ---------------------------------------------------------------------------
# Proactive run
# ---------------------------------------------------------------------------

def run_proactive(ambient_c: float) -> None:
    run_dir = make_run_dir("proactive")
    print(f"\n  Run dir : {run_dir}")
    print(f"  Ambient : {ambient_c:.1f} C")

    write_metadata(run_dir, "proactive", ambient_c)

    # Queue MUST be created in parent before any fork
    telemetry_queue: mp.Queue = mp.Queue(maxsize=200)

    telemetry = TelemetryPipeline(
        run_dir           = str(run_dir),
        sampling_rate_hz  = 2.0,
        duration_sec      = DURATION_S,
        ambient_temp_c    = ambient_c,
        cooling_condition = "passive",
        tags              = {"label": LABEL, "mode": "proactive"},
        scheduler_queue   = telemetry_queue,
        dht11_pin         = DHT11_PIN,
    )

    stop_inference = mp.Event()

    try:
        print("  Starting telemetry ...")
        shared_start = telemetry.start()
        print(f"  shared_start_monotonic = {shared_start:.4f}")

        # SchedulerRuntime uses shared_start_monotonic for time-base alignment
        scheduler = SchedulerRuntime(
            run_dir                = str(run_dir),
            telemetry_queue        = telemetry_queue,
            shared_start_monotonic = shared_start,
            scheduler_mode         = "proactive",
        )
        print("  Starting scheduler ...")
        scheduler.start()

        inf_proc = mp.Process(
            target = inference_worker_main,
            args   = (
                str(MODEL_PATH),
                str(VIDEO_PATH),
                str(run_dir / "inference_log.csv"),
                stop_inference,
                shared_start,
            ),
            name = "inference_worker",
        )
        print("  Starting inference ...")
        inf_proc.start()

        print(f"\n  *** HIGH AMBIENT PROACTIVE RUN STARTED ***\n")
        _wait_with_progress(DURATION_S)

    finally:
        # Shutdown order: inference -> scheduler -> telemetry (per HANDOFF.md)
        stop_inference.set()
        inf_proc.join(timeout=10.0)
        if inf_proc.is_alive():
            print("  WARNING: inference worker still alive -- terminating.")
            inf_proc.terminate()
            inf_proc.join()

        scheduler.stop(timeout=10.0)
        telemetry.stop()
        restore_max()
        print("  DVFS restored to S0 (2400 MHz)")

    finalise_metadata(run_dir)
    print(f"\n  *** HIGH AMBIENT RUN COMPLETE *** -> {run_dir}\n")


# ---------------------------------------------------------------------------
# Progress helper
# ---------------------------------------------------------------------------

def _wait_with_progress(total_s: int) -> None:
    """Sleep total_s, printing a status line every 5 minutes."""
    interval = 300
    elapsed  = 0
    while elapsed < total_s:
        chunk    = min(interval, total_s - elapsed)
        time.sleep(chunk)
        elapsed += chunk
        soc_c    = int(Path("/sys/class/thermal/thermal_zone0/temp").read_text()) / 1000.0
        print(
            f"  [{elapsed//60:02d}/{total_s//60}min]  "
            f"SoC={soc_c:.1f} C  "
            f"remaining={max(0, (total_s-elapsed)//60)}min"
        )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="High-ambient robustness demonstration run",
    )
    parser.add_argument(
        "--mode", required=True, choices=["static_s1", "proactive"],
        help="static_s1: 1800 MHz cap, no scheduler. proactive: full scheduler.",
    )
    parser.add_argument(
        "--skip-sha", action="store_true",
        help="Skip video SHA256 check.",
    )
    args = parser.parse_args()

    print("\n" + "=" * 60)
    print(f"  HIGH AMBIENT ROBUSTNESS EXPERIMENT  |  mode={args.mode}")
    print("=" * 60 + "\n")

    print("  Pre-flight:")
    check_prerequisites(skip_sha=args.skip_sha)

    print("\n  Reading DHT11 ambient ...")
    ambient_c = read_ambient()
    print(f"  Ambient: {ambient_c:.1f} C")

    if ambient_c > 35.0:
        print(
            f"\n  WARNING: Ambient {ambient_c:.1f} C is very high.\n"
            "  S2 plateau may reach throttle onset. Proactive might throttle too.\n"
            "  Press Enter to continue or Ctrl-C to abort."
        )
        try:
            input()
        except KeyboardInterrupt:
            sys.exit(0)

    try:
        mp.set_start_method("fork", force=True)
    except RuntimeError:
        pass

    if args.mode == "static_s1":
        run_static_s1(ambient_c)
    else:
        run_proactive(ambient_c)


if __name__ == "__main__":
    main()