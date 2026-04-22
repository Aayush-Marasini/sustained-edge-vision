"""
convert_baseline_to_openvino.py
================================
Documents the exact OpenVINO export process used to generate the frozen
baseline models in 00_frozen_artifacts/yolov8n_baseline_seed42/weights/.


Conversion history
------------------
Date: April 1, 2026 (~7:11 PM - 7:42 PM based on file LastWriteTime)
Platform: Windows 11 (development machine with Kaggle-trained best.pt)
Ultralytics version: 8.4.7
Python version: 3.13.7
OpenVINO version: 2026.0.0
NNCF version: 3.0.0 (used for INT8 post-training quantization)

The conversions were executed once and outputs moved to the frozen structure.
SHA256 hashes verified in 00_frozen_artifacts/SHA256SUMS.txt.


"""

import sys
from pathlib import Path

# Cross-platform path imports
_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))
from common.paths import BASELINE_PT, BASELINE_MODEL_DIR, BASELINE_DATA_YAML

# ============================================================================
# CONVERSION COMMANDS (ALREADY EXECUTED)
# ============================================================================

def export_fp32():
    """
    FP32 export (default precision).
    
    Command executed:
        from ultralytics import YOLO
        model = YOLO("path/to/best.pt")
        model.export(format="openvino")
    
    Output:
        best_openvino_model/ (default Ultralytics naming)
        → manually renamed/moved to: openvino_fp32/
    """
    print("FP32: Default precision export")
    print(f"  Input : {BASELINE_PT}")
    print(f"  Output: {BASELINE_MODEL_DIR / 'weights' / 'openvino_fp32'}")
    print(f"  Method: model.export(format='openvino')")


def export_fp16():
    """
    FP16 export (half precision).
    
    Command executed:
        model.export(format="openvino", half=True)
    
    Output:
        best_openvino_model/ 
        → manually renamed/moved to: openvino_fp16/
    """
    print("\nFP16: Half-precision export")
    print(f"  Input : {BASELINE_PT}")
    print(f"  Output: {BASELINE_MODEL_DIR / 'weights' / 'openvino_fp16'}")
    print(f"  Method: model.export(format='openvino', half=True)")


def export_int8():
    """
    INT8 export with calibration on validation set.
    
    Command executed:
        model.export(
            format="openvino",
            int8=True,
            data="rdd2022.yaml",  # Calibration dataset
            fraction=1.0          # Full validation set
        )
    
    Calibration:
        - Dataset: RDD2022-US validation split (n=481 images, 1,124 instances)
        - Method: Post-training quantization via OpenVINO Neural Network
                  Compression Framework (NNCF)
        - Fraction: 1.0 (entire validation set used for calibration)
    
    Output:
        best_openvino_model/
        → manually renamed/moved to: openvino_int8/
    
    Deployment note:
        INT8 achieved 8.22 FPS baseline throughput on Raspberry Pi 5 under
        passive cooling (Progress_Report.pdf §IV). This is the primary format
        used for all scheduler experiments.
    """
    print("\nINT8: Quantized export with calibration")
    print(f"  Input : {BASELINE_PT}")
    print(f"  Output: {BASELINE_MODEL_DIR / 'weights' / 'openvino_int8'}")
    print(f"  Method: model.export(")
    print(f"              format='openvino',")
    print(f"              int8=True,")
    print(f"              data='{BASELINE_DATA_YAML.name}',")
    print(f"              fraction=1.0")
    print(f"          )")
    print(f"  Calibration dataset: {BASELINE_DATA_YAML}")
    print(f"                       481 validation images (full split)")


def verify_outputs():
    """
    Verify that frozen outputs exist and remind user about SHA256 verification.
    """
    print("\n" + "=" * 70)
    print("VERIFICATION CHECKLIST")
    print("=" * 70)
    
    expected = [
        BASELINE_MODEL_DIR / "weights" / "openvino_fp32",
        BASELINE_MODEL_DIR / "weights" / "openvino_fp16",
        BASELINE_MODEL_DIR / "weights" / "openvino_int8",
    ]
    
    all_exist = True
    for path in expected:
        exists = path.exists()
        status = "✓ EXISTS" if exists else "✗ MISSING"
        print(f"  [{status}] {path}")
        if not exists:
            all_exist = False
    
    if all_exist:
        print("\nAll OpenVINO models present in frozen artifacts.")
        print("Verify SHA256 hashes match 00_frozen_artifacts/SHA256SUMS.txt")
    else:
        print("\n⚠ WARNING: Some models are missing from frozen artifacts!")
        print("DO NOT reconvert without PI approval. Check if models were")
        print("archived elsewhere or if the frozen structure changed.")


# ============================================================================
# IMPORTANT IMPLEMENTATION NOTES
# ============================================================================

IMPLEMENTATION_NOTES = """
CRITICAL IMPLEMENTATION DETAILS (from conversion history):

1. NAMING CONVENTION:
   Ultralytics exports to a folder named "best_openvino_model/" by default.
   For AutoBackend loader compatibility on Raspberry Pi 5, the folder MUST
   retain the "_openvino_model" suffix. Our frozen structure uses:
       openvino_fp32/
       openvino_fp16/
       openvino_int8/
   
   The Pi inference runtime expects this exact naming. Do not rename to
   "fp32/", "fp16_model/", etc.

2. AUTOMATION:
   Original conversion used a PowerShell script (Windows dev environment) to
   automate renaming and moving outputs from Ultralytics default paths into
   the project frozen structure. This script is not preserved in the repo
   as it was platform-specific and single-use.

3. PERFORMANCE BASELINE:
   INT8 inference on Raspberry Pi 5 achieved 8.22 FPS under passive cooling
   (Progress_Report.pdf §IV). This was measured with the frozen INT8 model
   processing the 30 FPS benchmark video (thermal_benchmark_30fps.mp4).

4. FILE STRUCTURE:
   Each OpenVINO export produces:
       - model.xml (network topology)
       - model.bin (weights)
       - metadata.yaml (Ultralytics metadata)
   
   Total size per model:
       FP32: ~6.2 MB
       FP16: ~3.1 MB  (50% reduction)
       INT8: ~1.6 MB  (75% reduction)

5. RASPBERRY PI DEPLOYMENT:
   Models are loaded via:
       from ultralytics import YOLO
       model = YOLO("path/to/openvino_int8/")
   
   The AutoBackend detects the OpenVINO format automatically and uses the
   OpenVINO Runtime (installed via `pip install openvino`) for inference.

6. REPRODUCIBILITY:
   OpenVINO optimization passes include non-deterministic graph transforms.
   Re-exporting the same best.pt can produce functionally identical but
   bit-level different binaries. SHA256 hashes lock the exact binaries used
   for all experiments in this paper.
"""


# ============================================================================
# MAIN
# ============================================================================

def main():
    print("=" * 70)
    print("OpenVINO Baseline Export — DOCUMENTATION ONLY")
    print("=" * 70)
    print("\n⚠ This script documents the conversion process that was already")
    print("  executed to generate the frozen baseline models. DO NOT re-run")
    print("  the conversion commands unless explicitly approved by the PI.\n")
    
    export_fp32()
    export_fp16()
    export_int8()
    verify_outputs()
    
    print("\n" + "=" * 70)
    print(IMPLEMENTATION_NOTES)
    print("=" * 70)
    
    print("\nTo reproduce from scratch (ONLY if baseline is being regenerated):")
    print("  1. Train YOLOv8n with seed=42 (see 03_code/experiments/train_baseline.py)")
    print("  2. Load best.pt and run the three export commands documented above")
    print("  3. Move outputs to 00_frozen_artifacts/yolov8n_baseline_seed42/weights/")
    print("  4. Compute SHA256 hashes and update SHA256SUMS.txt")
    print("  5. Commit frozen artifacts with Git LFS")
    print("  6. Update CHANGELOG.md with conversion details\n")


if __name__ == "__main__":
    main()