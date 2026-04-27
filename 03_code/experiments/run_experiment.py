"""
run_experiment.py
=================
Full experiment harness: runs YOLOv8n inference + telemetry in parallel.

Usage:
  python run_experiment.py \\
    --model ../../02_models/openvino/yolov8n_fp32 \\
    --video ../../04_workload/videos/test_traffic.mp4 \\
    --duration 60 \\
    --ambient-temp-c 23.0 \\
    --cooling passive \\
    --dht11-pin 4 \\
    --tags '{"workload":"yolov8n_fp32","phase":"D_baseline"}'

Outputs (all written to a timestamped run directory in 05_results/runs/):
  - telemetry_raw.csv (from telemetry_pipeline.py)
  - inference_log.csv (from inference_worker.py)
  - run_metadata.json (combined experiment metadata)

Integration with PowerZ (manual workflow):
  1. Start PowerZ recording before running this script
  2. Run this script
  3. Stop PowerZ recording after script completes
  4. PowerZ .db file name should match the run directory timestamp
  5. Add power_recording field to --tags JSON, e.g.:
     --tags '{"power_recording":"2026-04-26_run1.db"}'
"""
from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional

# Path bootstrap
_THIS = Path(__file__).resolve()
_CODE_ROOT = _THIS.parent.parent  # 03_code/
sys.path.insert(0, str(_CODE_ROOT))

from inference.inference_worker import inference_worker_main


def run_telemetry(
    duration: float,
    ambient_temp_c: float,
    cooling: str,
    dht11_pin: Optional[int],
    tags: Dict[str, Any],
    run_dir: Path,
    shared_start_monotonic: float,
) -> subprocess.Popen:
    """
    Launch telemetry_pipeline.py as a subprocess.

    Returns the Popen object so the parent can wait for clean shutdown.
    """
    telemetry_script = _CODE_ROOT / "telemetry" / "telemetry_pipeline.py"
    
    cmd = [
        sys.executable,
        str(telemetry_script),
        "--duration", str(duration),
        "--ambient-temp-c", str(ambient_temp_c),
        "--cooling", cooling,
        "--tags", json.dumps(tags),
        "--run-dir", str(run_dir),
    ]
    
    if dht11_pin is not None:
        cmd.extend(["--dht11-pin", str(dht11_pin)])

    return subprocess.Popen(cmd)


def main():
    parser = argparse.ArgumentParser(description="Full inference + telemetry experiment")
    parser.add_argument("--model", required=True, help="Path to OpenVINO model directory")
    parser.add_argument("--video", required=True, help="Path to workload video")
    parser.add_argument("--duration", type=float, required=True, help="Experiment duration (seconds)")
    parser.add_argument("--ambient-temp-c", type=float, required=True, help="Ambient temperature (°C)")
    parser.add_argument("--cooling", required=True, choices=["passive", "active"], help="Cooling strategy")
    parser.add_argument("--dht11-pin", type=int, default=None, help="DHT11 GPIO pin (BCM numbering)")
    parser.add_argument("--tags", type=str, required=True, help="JSON tags dict for metadata")
    args = parser.parse_args()

    model_path = Path(args.model)
    video_path = Path(args.video)

    if not model_path.exists():
        raise FileNotFoundError(f"Model not found: {model_path}")
    if not video_path.exists():
        raise FileNotFoundError(f"Video not found: {video_path}")

    tags = json.loads(args.tags)

    # Create run directory
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")
    workload_tag = tags.get("workload", "unknown")
    run_name = f"{timestamp}_{workload_tag}"
    run_dir = Path("../../05_results/runs") / run_name
    run_dir = run_dir.resolve()
    run_dir.mkdir(parents=True, exist_ok=True)

    print(f"Run directory: {run_dir}")
    print(f"Duration: {args.duration} s")
    print(f"Model: {model_path}")
    print(f"Video: {video_path}")
    print(f"Tags: {tags}")
    print()

    # Shared start time for both workers
    shared_start_monotonic = time.monotonic()

    # Start telemetry subprocess
    print("Starting telemetry...")
    telemetry_proc = run_telemetry(
        duration=args.duration,
        ambient_temp_c=args.ambient_temp_c,
        cooling=args.cooling,
        dht11_pin=args.dht11_pin,
        tags=tags,
        run_dir=run_dir,
        shared_start_monotonic=shared_start_monotonic,
    )

    # Start inference worker process
    print("Starting inference...")
    stop_event = mp.Event()
    inference_csv = run_dir / "inference_log.csv"
    
    inference_proc = mp.Process(
        target=inference_worker_main,
        args=(
            str(model_path),
            str(video_path),
            str(inference_csv),
            stop_event,
            shared_start_monotonic,
        ),
    )
    inference_proc.start()

    # Wait for duration
    time.sleep(args.duration)

    # Signal inference worker to stop
    print("\nStopping inference worker...")
    stop_event.set()
    inference_proc.join(timeout=5.0)
    if inference_proc.is_alive():
        print("WARNING: Inference worker did not stop cleanly, terminating...")
        inference_proc.terminate()
        inference_proc.join()

    # Wait for telemetry subprocess to finish
    print("Waiting for telemetry to finish...")
    telemetry_proc.wait()

    print(f"\nExperiment complete. Results in {run_dir}")
    print(f"  - telemetry_raw.csv")
    print(f"  - inference_log.csv")
    print(f"  - run_metadata.json")


if __name__ == "__main__":
    mp.set_start_method("spawn", force=True)  # Required for cross-platform compatibility
    main()