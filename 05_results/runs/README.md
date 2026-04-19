# Run Directory Convention

Each experiment run produces one subdirectory named:

    {YYYYMMDD_HHMMSS}_{method}_{workload}_{rep}/

Where:
  - method in {static_max, static_min, reactive_thermal, reactive_util, proactive, proactive_hcc}
  - workload in {worst_case, moderate, realistic}
  - rep: zero-padded repetition number (e.g., 01, 02, ..., 05)

Each run directory contains:
  - run_metadata.json       - config, git SHA, ambient temp, duration, seed, host
  - telemetry_raw.csv       - raw 5 Hz signals from telemetry_pipeline.py
  - telemetry_state.csv     - derived state vector (smoothed + derivatives)
  - inference_log.csv       - per-frame inference outputs and latency
  - scheduler_decisions.csv - per-decision scheduler actions (if applicable)
  - km003c_power.csv        - external power meter log (if collected)
  - detections/             - optional, saved detection images for spot-checks

Do NOT put analysis outputs here. Use 05_results/analysis/ instead.

Naming example:
  20260425_143022_proactive_hcc_worst_case_03/

This makes runs chronologically sortable, method-filterable, and workload-groupable.