# Project Changelog

All notable changes to code, data, and experimental configuration.
Required by the No Silent Changes Rule.

Format: ## [YYYY-MM-DD] Short Title
Each entry includes: Added / Changed / Removed / Notes sections as needed.

---

## [2026-04-18] Phase 2 Kickoff: Baseline Freeze and Restructure

### Added
- 00_frozen_artifacts/ directory containing:
  - yolov8n_baseline_seed42/weights/ (best.pt, last.pt, OpenVINO FP16/FP32/INT8)
  - yolov8n_baseline_seed42/args.yaml, data.yaml
  - yolov8n_baseline_seed42/training_outputs/ (curves, confusion matrices, batch images)
  - benchmark_workloads/thermal_benchmark_30fps.mp4
  - dataset_manifests/ (train, val, test partition SHA256 hashes)
  - SHA256SUMS.txt and MANIFEST.md
- 03_code/common/paths.py - cross-platform path management (single source of truth)
- 03_code/data_preparation/generate_partition_manifest.py
- 03_code/ subdirectories: telemetry/, scheduler/, experiments/,
  experiments/baselines/, analysis/, common/, data_preparation/
- __init__.py in every Python package directory
- 05_results/runs/README.md - experiment run directory naming convention
- .gitignore and .gitattributes (Git LFS for .pt, .bin, .xml, .mp4)

### Changed
- Moved frozen prep scripts (split_train_images.py, verify_annotations.py,
  class_distribution.py) from 03_code/baseline_scripts/ to 03_code/data_preparation/
- Moved run_experiment.py to 03_code/experiments/
- Renamed old log_telemetry.py to log_telemetry_DEPRECATED.py (moved to 03_code/telemetry/)
- Moved stray pretrained checkpoints (yolov8n.pt, yolo26n.pt) to archive/
  (these were Ultralytics auto-downloaded pretrained weights, not the baseline model)
- Moved yolo_usa_split.zip (284 MB dataset backup) to archive/

### Removed
- 03_code/baseline_scripts/ (contents redistributed by role)
- 03_code/scheduler_logic/ (redundant with scheduler/)
- Stray data.yaml at project root (leftover from a miscopied command)
- 01_documentation/proposal/paper (AutoRecovered).docx (Word crash-recovery file)

### Notes
- Read-only attributes set on all files in 00_frozen_artifacts/ via attrib +R /S
- Baseline model identity verified by SHA256 hashes (see 00_frozen_artifacts/SHA256SUMS.txt)
- Initial Git repository created with LFS enabled for large binaries
- paths.py tested on Windows; Linux/Pi logic present but untested until deployment
- 9 binary files totaling ~110 MB tracked via LFS, not native git storage

---

## Template for Future Entries

## [YYYY-MM-DD] Title

### Added
- ...

### Changed
- ...

### Removed
- ...

### Notes
- ...