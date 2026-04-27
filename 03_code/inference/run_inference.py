"""
run_inference.py
================
Minimal YOLOv8n inference loop via OpenVINO runtime.

Usage:
  python run_inference.py --model <path_to_openvino_model> --video <path_to_video> [--frames N]

Example:
  python run_inference.py \
    --model ../../02_models/openvino/yolov8n_fp32 \
    --video ../../04_workload/videos/test_traffic.mp4 \
    --frames 100

Logs per-frame latency and reports average FPS at the end.
"""
import argparse
import time
from pathlib import Path

import cv2
import numpy as np
import openvino as ov


def preprocess_frame(frame: np.ndarray, input_shape: tuple) -> np.ndarray:
    """
    Resize and normalize frame to match YOLOv8 input requirements.
    
    YOLOv8 expects:
      - Input shape: (1, 3, 640, 640) = NCHW format
      - Pixel values: [0, 1] float32
      - RGB channel order
    """
    h, w = input_shape[2], input_shape[3]
    resized = cv2.resize(frame, (w, h))
    rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
    normalized = rgb.astype(np.float32) / 255.0
    transposed = np.transpose(normalized, (2, 0, 1))  # HWC -> CHW
    batched = np.expand_dims(transposed, axis=0)      # CHW -> NCHW
    return batched


def main():
    parser = argparse.ArgumentParser(description="YOLOv8n OpenVINO inference")
    parser.add_argument("--model", required=True, help="Path to OpenVINO model directory")
    parser.add_argument("--video", required=True, help="Path to input video file")
    parser.add_argument("--frames", type=int, default=None, help="Max frames to process (default: all)")
    args = parser.parse_args()

    model_path = Path(args.model)
    video_path = Path(args.video)

    if not model_path.exists():
        raise FileNotFoundError(f"Model not found: {model_path}")
    if not video_path.exists():
        raise FileNotFoundError(f"Video not found: {video_path}")

    # Load OpenVINO model
    print(f"Loading model from {model_path}...")
    core = ov.Core()
    model_xml = model_path / f"{model_path.name}.xml"
    if not model_xml.exists():
        # Fallback: try yolov8n.xml if directory name doesn't match
        model_xml = model_path / "yolov8n.xml"
    model = core.read_model(model_xml)
    compiled_model = core.compile_model(model, "CPU")
    infer_request = compiled_model.create_infer_request()

    # Get input/output layer info
    input_layer = compiled_model.input(0)
    output_layer = compiled_model.output(0)
    input_shape = input_layer.shape
    print(f"Model loaded. Input shape: {input_shape}, Output shape: {output_layer.shape}")

    # Open video
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video: {video_path}")

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    print(f"Video: {total_frames} frames @ {fps:.2f} FPS")

    max_frames = args.frames if args.frames else total_frames
    latencies = []
    frame_idx = 0

    print(f"\nProcessing up to {max_frames} frames...")
    while frame_idx < max_frames:
        ret, frame = cap.read()
        if not ret:
            break

        # Preprocess
        input_tensor = preprocess_frame(frame, input_shape)

        # Inference
        start = time.perf_counter()
        infer_request.infer({input_layer: input_tensor})
        elapsed = time.perf_counter() - start

        # Get output (we don't post-process detections yet, just measure latency)
        output = infer_request.get_output_tensor(0).data

        latencies.append(elapsed)
        frame_idx += 1

        if frame_idx % 10 == 0:
            avg_lat = np.mean(latencies[-10:]) * 1000
            print(f"Frame {frame_idx}/{max_frames}: avg latency {avg_lat:.1f} ms (last 10 frames)")

    cap.release()

    # Report
    if latencies:
        avg_latency = np.mean(latencies) * 1000  # ms
        avg_fps = 1.0 / np.mean(latencies)
        print(f"\n=== Results ===")
        print(f"Frames processed: {len(latencies)}")
        print(f"Avg latency:      {avg_latency:.2f} ms")
        print(f"Avg FPS:          {avg_fps:.2f}")
    else:
        print("No frames processed.")


if __name__ == "__main__":
    main()
