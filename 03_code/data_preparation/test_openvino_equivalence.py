"""
test_openvino_equivalence.py
=============================
Verifies that reconverted OpenVINO models produce functionally identical
outputs to the frozen baseline models, even though SHA256 hashes differ
due to OpenVINO's non-deterministic graph optimization.

THIS IS A ONE-TIME SANITY CHECK. DO NOT commit reconverted models to Git.

Usage:
    python test_openvino_equivalence.py
"""

import sys
from pathlib import Path
import torch
from ultralytics import YOLO
import numpy as np

# Cross-platform paths
_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))
from common.paths import BASELINE_PT, BASELINE_MODEL_DIR, PROCESSED_YOLO_DIR

# Test image paths
VAL_IMG_DIR = PROCESSED_YOLO_DIR / "val" / "images"


def get_test_images(n=10):
    """Grab first N validation images for deterministic testing."""
    imgs = sorted(VAL_IMG_DIR.glob("*.jpg"))[:n]
    if len(imgs) < n:
        raise RuntimeError(f"Need at least {n} val images, found {len(imgs)}")
    return imgs


def run_inference(model_path, test_images):
    """Run inference and return detection boxes + confidences."""
    model = YOLO(str(model_path))
    results = []
    
    for img in test_images:
        r = model(str(img), verbose=False)[0]
        boxes = r.boxes.xyxy.cpu().numpy() if r.boxes else np.array([])
        confs = r.boxes.conf.cpu().numpy() if r.boxes else np.array([])
        results.append((boxes, confs))
    
    return results


def compare_results(frozen_results, reconverted_results, tolerance=1e-3):
    """
    Compare two sets of inference results.
    
    Returns (is_equivalent, max_diff)
    """
    max_diff = 0.0
    
    for i, ((f_boxes, f_confs), (r_boxes, r_confs)) in enumerate(
        zip(frozen_results, reconverted_results)
    ):
        # Check same number of detections
        if len(f_boxes) != len(r_boxes):
            print(f"  Image {i}: Detection count mismatch "
                  f"(frozen={len(f_boxes)}, reconverted={len(r_boxes)})")
            return False, float('inf')
        
        # Check box coordinates
        if len(f_boxes) > 0:
            box_diff = np.abs(f_boxes - r_boxes).max()
            conf_diff = np.abs(f_confs - r_confs).max()
            max_diff = max(max_diff, box_diff, conf_diff)
            
            if box_diff > tolerance:
                print(f"  Image {i}: Box diff {box_diff:.6f} exceeds tolerance")
                return False, max_diff
    
    return True, max_diff


def main():
    print("=" * 70)
    print("OpenVINO Model Equivalence Test")
    print("=" * 70)
    print("\nThis test verifies that reconverted models produce functionally")
    print("identical outputs to frozen baselines, even though binary hashes differ.\n")
    
    # Get test images
    test_images = get_test_images(n=10)
    print(f"Using {len(test_images)} validation images for testing\n")
    
    # Paths
    frozen_base = BASELINE_MODEL_DIR / "weights"
    reconverted_base = Path("temp_reconverted_models")  # Where you'll export
    
    formats = ["fp32", "fp16", "int8"]
    
    for fmt in formats:
        print(f"Testing {fmt.upper()}...")
        
        frozen_path = frozen_base / f"openvino_{fmt}"
        reconv_path = reconverted_base / f"openvino_{fmt}"
        
        if not frozen_path.exists():
            print(f"  ✗ SKIP: Frozen model not found at {frozen_path}")
            continue
        
        if not reconv_path.exists():
            print(f"  ✗ SKIP: Reconverted model not found at {reconv_path}")
            print(f"    Run conversion script first to generate models in {reconverted_base}")
            continue
        
        # Run inference
        frozen_results = run_inference(frozen_path, test_images)
        reconv_results = run_inference(reconv_path, test_images)
        
        # Compare
        is_equiv, max_diff = compare_results(frozen_results, reconv_results)
        
        if is_equiv:
            print(f"  ✓ PASS: Models are functionally equivalent (max diff: {max_diff:.6f})")
        else:
            print(f"  ✗ FAIL: Models produce different outputs (max diff: {max_diff:.6f})")
            print(f"    This might indicate a version mismatch or calibration difference.")
    
    print("\n" + "=" * 70)
    print("Test complete. If all models passed, you can safely delete")
    print(f"{reconverted_base} — frozen models are verified equivalent.")
    print("=" * 70)


if __name__ == "__main__":
    main()