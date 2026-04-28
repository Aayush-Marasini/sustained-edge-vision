"""
run_inference_timed.py
======================
Timed inference runner with video looping for overhead benchmarking.

Usage:
    python run_inference_timed.py \
        --model <path> \
        --video <path> \
        --duration <seconds> \
        --output <csv_path> \
        --ambient-temp-c <float>
"""
import argparse
import csv
import json
import sys
import time
import multiprocessing as mp
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))
from inference.inference_worker import inference_worker_main


def main():
    parser = argparse.ArgumentParser(description="Timed inference with video looping")
    parser.add_argument("--model", required=True, help="Path to OpenVINO model directory")
    parser.add_argument("--video", required=True, help="Path to video file")
    parser.add_argument("--duration", type=float, required=True, help="Duration in seconds")
    parser.add_argument("--output", required=True, help="Output CSV path")
    parser.add_argument("--ambient-temp-c", type=float, required=True, help="Ambient temperature")
    args = parser.parse_args()

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"Starting {args.duration}s inference run")
    print(f"  Model: {args.model}")
    print(f"  Video: {args.video}")
    print(f"  Output: {args.output}")
    print(f"  Ambient: {args.ambient_temp_c}°C")
    print()

    # Create stop event for the worker
    stop_event = mp.Event()

    # Timer thread to stop after duration
    import threading
    def stop_after_duration():
        time.sleep(args.duration)
        stop_event.set()
    
    timer = threading.Thread(target=stop_after_duration, daemon=True)
    timer.start()

    # Run inference worker (will loop video until stop_event is set)
    inference_worker_main(
        model_path=args.model,
        video_path=args.video,
        output_csv=args.output,
        stop_event=stop_event,
        shared_start_monotonic=None  # No sync needed for inference-only
    )

    # Write metadata
    metadata = {
        "ambient_temp_c": args.ambient_temp_c,
        "cooling": "passive",
        "duration_sec": args.duration,
        "purpose": "S1.1_overhead_benchmark_inferonly"
    }
    metadata_path = output_path.parent / "metadata.json"
    with open(metadata_path, "w") as f:
        json.dump(metadata, f, indent=2)

    print(f"\nMetadata saved to {metadata_path}")


if __name__ == "__main__":
    main()