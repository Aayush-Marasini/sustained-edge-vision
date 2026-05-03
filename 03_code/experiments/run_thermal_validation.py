"""
run_thermal_validation.py
=========================
30-minute thermal validation run for one DVFS state, with guaranteed
cap restoration on exit.

Maps to:
- WorkPlan §8.1 Task 20: configuration profiling (temperature rise rate).
- WorkPlan §8.3 Task 22: long-horizon experiment skeleton (30-min duration).
- HANDOFF.md §10: prove S0 throttles, S1/S2 plateau.

Workflow
--------
1. Operator: start PowerZ recording with descriptor matching --rep tag.
2. Run this script under sudo from the Pi.
3. Operator: stop PowerZ recording when script prints "EXPERIMENT COMPLETE".
4. SCP run_dir + .db to Windows for analysis.

Example
-------
    sudo /home/raspberrypi/yolov8_env/bin/python \\
        03_code/experiments/run_thermal_validation.py \\
        --state S1 \\
        --duration 1800 \\
        --ambient-temp-c 23.5 \\
        --dht11-pin 4 \\
        --rep 1
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Path bootstrap so we can import scheduler.dvfs_control
_THIS = Path(__file__).resolve()
_CODE_ROOT = _THIS.parent.parent              # 03_code/
_REPO_ROOT = _CODE_ROOT.parent                # repo root
sys.path.insert(0, str(_CODE_ROOT))

from scheduler.dvfs_control import (         # noqa: E402
    DvfsError, STATES, get_current_cap_khz, get_governor,
    restore_max, set_state_by_name,
)

# -----------------------------------------------------------------------------
# Hard-coded paper-quality defaults (Task 20 / Task 22)
# -----------------------------------------------------------------------------
DEFAULT_MODEL = _REPO_ROOT / "02_models" / "openvino" / "yolov8n_fp32"
DEFAULT_VIDEO = _REPO_ROOT / "04_workload" / "videos" / "thermal_benchmark_30fps.mp4"
DEFAULT_DURATION_S = 1800.0  # 30 min, per WorkPlan §8.3

# Thermal precondition (start cool to ensure repeatable trajectory)
PRECONDITION_MAX_START_TEMP_C = 50.0


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
def _read_soc_temp_c() -> float:
    """Read Pi SoC thermal_zone0 temperature in °C."""
    raw = Path("/sys/class/thermal/thermal_zone0/temp").read_text(encoding="utf-8").strip()
    return int(raw) / 1000.0


def _check_governor_or_die() -> None:
    gov = get_governor()
    if gov != "ondemand":
        sys.exit(
            f"PROTOCOL VIOLATION: scaling_governor is '{gov}', "
            f"expected 'ondemand'. Aborting (EXPERIMENTAL_PROTOCOL.md)."
        )


def _check_thermal_precondition_or_die() -> None:
    t = _read_soc_temp_c()
    if t > PRECONDITION_MAX_START_TEMP_C:
        sys.exit(
            f"THERMAL PRECONDITION FAIL: SoC = {t:.1f} °C > "
            f"{PRECONDITION_MAX_START_TEMP_C} °C. Wait longer between runs."
        )
    print(f"[precond] SoC start temp: {t:.1f} °C  (OK)")


def _check_wifi_blocked_or_warn() -> None:
    try:
        out = subprocess.check_output(
            ["rfkill", "list", "wifi"], text=True, timeout=2.0
        )
        if "Soft blocked: yes" not in out:
            print("WARNING: WiFi may not be blocked. "
                  "Run `sudo rfkill block wifi` per protocol.")
    except (subprocess.SubprocessError, FileNotFoundError):
        print("WARNING: rfkill check failed. Verify WiFi block manually.")


def _verify_files_or_die(model: Path, video: Path) -> None:
    if not (model / "yolov8n.xml").exists():
        sys.exit(f"Model XML missing under {model}")
    if not video.exists():
        sys.exit(f"Workload video missing: {video}")


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------
def main() -> int:
    p = argparse.ArgumentParser(description="30-min thermal validation run.")
    p.add_argument("--state",          required=True, choices=list(STATES.keys()),
                   help="DVFS state to lock for the run (S0|S1|S2).")
    p.add_argument("--duration",       type=float, default=DEFAULT_DURATION_S,
                   help="Run duration in seconds (default: 1800 = 30 min).")
    p.add_argument("--ambient-temp-c", type=float, required=True,
                   help="Manually-measured ambient temperature (°C).")
    p.add_argument("--dht11-pin",      type=int, default=4,
                   help="DHT11 BCM pin for ambient logging (default: 4).")
    p.add_argument("--rep",            type=int, required=True,
                   help="Repetition number (1, 2, 3) for tagging.")
    p.add_argument("--model",          type=Path, default=DEFAULT_MODEL,
                   help="OpenVINO model dir (default: yolov8n_fp32).")
    p.add_argument("--video",          type=Path, default=DEFAULT_VIDEO,
                   help="Workload video (default: thermal_benchmark_30fps.mp4).")
    args = p.parse_args()

    # ---- preflight ----------------------------------------------------------
    print("=" * 60)
    print(f"THERMAL VALIDATION RUN: state={args.state}  rep={args.rep}")
    print("=" * 60)

    _check_governor_or_die()
    _check_wifi_blocked_or_warn()
    _verify_files_or_die(args.model, args.video)
    _check_thermal_precondition_or_die()

    # ---- DVFS state ---------------------------------------------------------
    print(f"[dvfs] Setting cap to state {args.state} "
          f"({STATES[args.state].cap_khz} kHz) ...")
    try:
        caps = set_state_by_name(args.state)
        print(f"[dvfs] Verified cap: {caps}")
    except DvfsError as e:
        sys.exit(f"DVFS setup failed: {e}")

    # ---- run experiment in try/finally so cap is ALWAYS restored ------------
    rc = 1
    try:
        tags = json.dumps({
            "workload":         f"thermalval_{args.state}",
            "phase":            "task20_config_profiling",
            "dvfs_state":       args.state,
            "dvfs_cap_khz":     STATES[args.state].cap_khz,
            "rep":              args.rep,
            "duration_min":     int(args.duration / 60),
            "purpose":          "30min_thermal_validation",
        })

        cmd = [
            sys.executable,
            str(_CODE_ROOT / "experiments" / "run_experiment.py"),
            "--model",          str(args.model),
            "--video",          str(args.video),
            "--duration",       str(args.duration),
            "--ambient-temp-c", str(args.ambient_temp_c),
            "--cooling",        "passive",
            "--dht11-pin",      str(args.dht11_pin),
            "--tags",           tags,
            "--sampling-rate-hz", "2.0",
        ]
        print(f"[exec] {' '.join(cmd)}")
        rc = subprocess.call(cmd)

    finally:
        # Restore is non-negotiable. Even if Python crashes here, the next
        # operator action should be `sudo dvfs_control.py --restore`.
        print("[dvfs] Restoring scaling_max_freq to S0 (2400000 kHz) ...")
        try:
            after = restore_max()
            print(f"[dvfs] Verified restore: {after}")
        except DvfsError as e:
            print(f"!!! DVFS RESTORE FAILED: {e}", file=sys.stderr)
            print("!!! MANUALLY RUN: sudo python 03_code/scheduler/dvfs_control.py --restore",
                  file=sys.stderr)
            return 4

    print("=" * 60)
    print("EXPERIMENT COMPLETE — stop PowerZ recording now.")
    print(f"Exit code from inner harness: {rc}")
    print("=" * 60)
    return rc


if __name__ == "__main__":
    sys.exit(main())