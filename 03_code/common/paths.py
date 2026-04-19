"""
paths.py
Central source of truth for all filesystem paths used across the project.

Paths auto-adjust based on environment:
  - Set RESEARCH_PROJECT_ROOT environment variable to override
  - On Windows, defaults to the hardcoded project location
  - On Linux (Raspberry Pi), defaults to ~/research_project

All other scripts should import from this module rather than hardcoding paths.
"""

import os
import platform
from pathlib import Path

# ---- Project root detection ----
if "RESEARCH_PROJECT_ROOT" in os.environ:
    PROJECT_ROOT = Path(os.environ["RESEARCH_PROJECT_ROOT"])
elif platform.system() == "Windows":
    PROJECT_ROOT = Path("C:/Users/User/Desktop/research_project")
elif platform.system() == "Linux":
    PROJECT_ROOT = Path.home() / "research_project"
else:
    raise RuntimeError(
        "Unrecognized platform: " + platform.system()
        + ". Set RESEARCH_PROJECT_ROOT environment variable."
    )

# ---- Frozen artifacts ----
FROZEN_DIR = PROJECT_ROOT / "00_frozen_artifacts"
BASELINE_MODEL_DIR = FROZEN_DIR / "yolov8n_baseline_seed42"
BASELINE_PT = BASELINE_MODEL_DIR / "weights" / "best.pt"
BASELINE_OPENVINO_FP16 = BASELINE_MODEL_DIR / "weights" / "openvino_fp16"
BASELINE_OPENVINO_FP32 = BASELINE_MODEL_DIR / "weights" / "openvino_fp32"
BASELINE_OPENVINO_INT8 = BASELINE_MODEL_DIR / "weights" / "openvino_int8"
BASELINE_ARGS_YAML = BASELINE_MODEL_DIR / "args.yaml"
BASELINE_DATA_YAML = BASELINE_MODEL_DIR / "data.yaml"
BENCHMARK_VIDEO = FROZEN_DIR / "benchmark_workloads" / "thermal_benchmark_30fps.mp4"
DATASET_MANIFESTS = FROZEN_DIR / "dataset_manifests"

# ---- Data ----
DATA_DIR = PROJECT_ROOT / "02_data"
PROCESSED_YOLO_DIR = DATA_DIR / "processed_yolo"
RAW_DATASET_DIR = DATA_DIR / "rdd2022_raw"
VIDEOS_DIR = DATA_DIR / "videos"
TELEMETRY_LOGS_DIR = DATA_DIR / "processed_telemetry"
RAW_LOGS_DIR = DATA_DIR / "logs"

# ---- Results ----
RESULTS_DIR = PROJECT_ROOT / "05_results"
RUNS_DIR = RESULTS_DIR / "runs"
PLOTS_DIR = RESULTS_DIR / "plots"
TABLES_DIR = RESULTS_DIR / "tables"
PAPER_DRAFTS_DIR = RESULTS_DIR / "paper_drafts"

# ---- Code ----
CODE_DIR = PROJECT_ROOT / "03_code"

# ---- Documentation ----
DOCS_DIR = PROJECT_ROOT / "01_documentation"
CHANGELOG = DOCS_DIR / "CHANGELOG.md"


def _verify(label, path, must_exist=True):
    if path.exists():
        status = "OK"
    elif must_exist:
        status = "MISSING"
    else:
        status = "not yet"
    print("  [" + status.ljust(8) + "] " + label + ": " + str(path))


if __name__ == "__main__":
    print("Platform: " + platform.system())
    print("PROJECT_ROOT: " + str(PROJECT_ROOT))
    print()
    print("Critical frozen artifacts (must exist):")
    _verify("best.pt", BASELINE_PT)
    _verify("OpenVINO INT8", BASELINE_OPENVINO_INT8)
    _verify("benchmark video", BENCHMARK_VIDEO)
    _verify("args.yaml", BASELINE_ARGS_YAML)
    _verify("data.yaml", BASELINE_DATA_YAML)
    _verify("train_manifest", DATASET_MANIFESTS / "train_manifest.txt")
    print()
    print("Data directories:")
    _verify("processed YOLO", PROCESSED_YOLO_DIR)
    _verify("raw dataset", RAW_DATASET_DIR)
    print()
    print("Result directories (may not exist yet):")
    _verify("runs", RUNS_DIR, must_exist=False)
    _verify("plots", PLOTS_DIR, must_exist=False)