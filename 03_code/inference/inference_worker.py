"""
inference_worker.py
===================
Subprocess worker that runs YOLOv8n inference in parallel with telemetry.

This module is called by run_experiment.py via multiprocessing. It runs
in a separate process to avoid GIL contention with the telemetry worker.

The worker:
1. Loads an OpenVINO model (FP32 or INT8)
2. Reads frames from a video file (looping if needed)
3. Runs inference on each frame
4. Logs per-frame latency to a CSV file
5. Terminates when the parent process signals stop via multiprocessing.Event

Design rationale (for paper §III.C):
- Separate process isolates inference CPU load from telemetry sampling
- Video loops to sustain 30-minute runs (real workload is 15-60s clips)
- No frame skipping: every frame is processed sequentially
- Latency logged per-frame for post-hoc FPS stability analysis
"""
from __future__ import annotations

import csv
import math
import sys
import time
from multiprocessing import Event
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
import openvino as ov


def preprocess_frame(frame: np.ndarray, input_shape: tuple) -> np.ndarray:
    """Resize and normalize frame to YOLOv8 input format (NCHW, [0,1] float32, RGB)."""
    h, w = input_shape[2], input_shape[3]
    resized = cv2.resize(frame, (w, h))
    rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
    normalized = rgb.astype(np.float32) / 255.0
    transposed = np.transpose(normalized, (2, 0, 1))  # HWC -> CHW
    batched = np.expand_dims(transposed, axis=0)      # CHW -> NCHW
    return batched


def inference_worker_main(
    model_path: str,
    video_path: str,
    output_csv: str,
    stop_event: Event,
    shared_start_monotonic: Optional[float] = None,
) -> None:
    """
    Main entry point for the inference subprocess.

    Parameters
    ----------
    model_path : str
        Path to OpenVINO model directory (contains .xml and .bin).
    video_path : str
        Path to input video file. If video is shorter than run duration,
        it will loop.
    output_csv : str
        Path to write inference_log.csv (frame_index, monotonic_time,
        latency_ms, model_precision).
    stop_event : multiprocessing.Event
        Parent process sets this to signal clean shutdown.
    shared_start_monotonic : float, optional
        Monotonic timestamp when the experiment started. If provided,
        monotonic_time in the CSV is offset from this value so telemetry
        and inference logs share a common time base.
    """
    model_path = Path(model_path)
    video_path = Path(video_path)
    output_csv = Path(output_csv)

    # Load OpenVINO model
    core = ov.Core()
    model_xml = model_path / "yolov8n.xml"
    if not model_xml.exists():
        raise FileNotFoundError(f"Model XML not found: {model_xml}")
    
    model = core.read_model(model_xml)
    compiled_model = core.compile_model(model, "CPU")
    infer_request = compiled_model.create_infer_request()

    input_layer = compiled_model.input(0)
    input_shape = input_layer.shape

    # Infer precision from model path (fp32 or int8)
    precision = "FP32" if "fp32" in str(model_path).lower() else "INT8"

    # Open video
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video: {video_path}")

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    video_fps = cap.get(cv2.CAP_PROP_FPS)

    # Create output CSV
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    csvfile = open(output_csv, "w", newline="", encoding="utf-8")
    writer = csv.writer(csvfile)
    writer.writerow(["frame_index", "monotonic_time_s", "latency_ms", "model_precision"])

    frame_index = 0
    video_loop_count = 0

    try:
        while not stop_event.is_set():
            ret, frame = cap.read()
            if not ret:
                # End of video, loop back to start
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                video_loop_count += 1
                continue

            # Preprocess
            input_tensor = preprocess_frame(frame, input_shape)

            # Inference
            start = time.perf_counter()
            infer_request.infer({input_layer: input_tensor})
            elapsed = time.perf_counter() - start

            # Log
            monotonic_now = time.monotonic()
            if shared_start_monotonic is not None:
                monotonic_offset = monotonic_now - shared_start_monotonic
            else:
                monotonic_offset = monotonic_now

            writer.writerow([
                frame_index,
                f"{monotonic_offset:.6f}",
                f"{elapsed * 1000:.2f}",
                precision,
            ])
            csvfile.flush()

            frame_index += 1

    except KeyboardInterrupt:
        pass
    finally:
        cap.release()
        csvfile.close()

    print(f"Inference worker: processed {frame_index} frames ({video_loop_count} video loops)")