# Frozen Artifacts Manifest

**Status:** FROZEN as of April 18, 2026

**Rule:** No file in this directory may be modified, moved, or deleted without
PI approval and a corresponding entry in `01_documentation/CHANGELOG.md`.

## Contents

### yolov8n_baseline_seed42/
The sole baseline model used for all scheduler experiments.

- `weights/best.pt` - PyTorch weights at epoch 168 (best mAP50=0.533)
- `weights/last.pt` - PyTorch weights at final epoch 218
- `weights/openvino_fp16/` - OpenVINO IR export, FP16 precision
- `weights/openvino_fp32/` - OpenVINO IR export, FP32 precision
- `weights/openvino_int8/` - OpenVINO IR export, INT8 quantized
- `args.yaml` - Exact Ultralytics training configuration
- `data.yaml` - Dataset configuration used at training time
- `training_outputs/` - Training curves, confusion matrices, validation batches

### benchmark_workloads/
- `thermal_benchmark_30fps.mp4` - 961-frame stitched test-set video, 30 FPS, 32-second loop. Worst-case sustained inference workload.

### dataset_manifests/
(To be populated - partition file lists and hashes via generate_partition_manifest.py)

## Training Provenance

- **Architecture:** YOLOv8n
- **Platform:** Kaggle, Tesla T4 GPU
- **Seed:** 42 (all sources)
- **Epochs completed:** 218 (early stopped, patience=50)
- **Best epoch:** 168
- **Validation mAP50:** 0.533
- **Validation set:** n=481 images, 1,124 instances
- **Class distribution (training):** D00=61.51%, D10=29.70%, D20=7.61%, D40=1.17%

## Verification Command

To verify no files have changed:

    cd 00_frozen_artifacts
    Get-ChildItem -Recurse -File -Exclude SHA256SUMS.txt,MANIFEST.md | Get-FileHash -Algorithm SHA256

Compare output against SHA256SUMS.txt. Any mismatch = Baseline Freeze violated.
