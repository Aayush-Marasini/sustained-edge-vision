# Sustained Edge Vision: Proactive DVFS Thermal Control on a Passively-Cooled Raspberry Pi 5

Code, data, and frozen artifacts for the paper:

> **Empirically-Calibrated DVFS: Eliminating Thermal Throttling on Passively-Cooled Edge Devices**
> Aayush Marasini, Zhaoxian Zhou — University of Southern Mississippi
> *(under review; citation will be added upon publication)*

An empirically-calibrated, state-aware DVFS scheduler that eliminates all thermal
throttling during sustained 30-minute YOLOv8n inference on a fan-less Raspberry Pi 5,
outperforming a temperature-only reactive baseline by **+6.8% FPS** (Cohen's d = 8.73)
at **-1.9% J/frame**, and beating an actively-cooled reference on energy-per-frame
(0.531 vs 0.563 J/frame).

## Repository layout

```
00_frozen_artifacts/   Frozen baseline: YOLOv8n weights (seed 42), OpenVINO exports,
                       benchmark video, dataset split manifests. SHA256-locked.
01_documentation/      CHANGELOG.md (No Silent Changes log).
02_data/               YOLO-format annotation labels for the RDD2022-USA subset
                       (images not redistributed; see Dataset below).
03_code/               All source. Key entry points:
                         scheduler/thermal_scheduler.py        - the proactive scheduler
                         scheduler/reactive_threshold_scheduler.py - reactive baseline
                         telemetry/telemetry_pipeline.py       - 2 Hz telemetry
                         experiments/run_scheduled_experiment.py - 30-min runs
                         analysis/compute_paper_statistics.py  - CANONICAL statistics
                         analysis/generate_paper_figures.py    - all paper figures
04_hardware_config/    DVFS / governor configuration applied on the Pi.
04_workload/           Benchmark video assembly.
05_results/            Raw per-run telemetry (runs/), canonical paper CSVs, figures.
tests/                 Unit and end-to-end scheduler tests.
```

## Canonical data sources (paper numbers)

Every number in the paper comes from these files, produced by
`03_code/analysis/compute_paper_statistics.py` and
`compute_sustainability_metrics.py` (bootstrap, 10,000 resamples, seed 42,
paired Cohen's d):

- `05_results/condition_stats_paper.csv`
- `05_results/pairwise_comparisons_paper.csv`
- `05_results/sustainability_metrics.csv` (Table 9)
- `05_results/power_analysis_robust.csv` (per-condition power summaries)

No other CSV in this repository is a paper source. Per-run-to-condition mapping
is documented in `05_results/runs/README.md`.

## Hardware / software

- Raspberry Pi 5 Model B (BCM2712, 4x Cortex-A76 @ 2.4 GHz, 8 GB), passive
  heatsink (official Active Cooler with fan header disconnected; fan connected
  only for the active-cooling reference condition).
- Raspberry Pi OS Lite (Debian 13 trixie, aarch64), kernel 6.12.75+rpt-rpi-2712.
- ChargerLAB POWER-Z KM003C inline USB-C power meter (1 kSPS).
- Python 3.13, Ultralytics 8.4.7, OpenVINO 2026.0.0, NNCF 3.0.0.
  See `requirements.txt`.

## Reproducing a run

On the Pi (sysfs DVFS control requires root; use the full venv interpreter
path):

```bash
cd ~/sustained-edge-vision
sudo /home/raspberrypi/yolov8_env/bin/python 03_code/experiments/run_scheduled_experiment.py
```

Each run writes a timestamped directory under `05_results/runs/` containing
`run_metadata.json` (git SHA, software versions, seed, ambient temperature),
raw and derived telemetry, per-frame inference log, and scheduler decisions.
See `05_results/runs/README.md` for the run-to-condition mapping used in the
paper.

Statistics and figures (any machine):

```bash
python 03_code/analysis/compute_paper_statistics.py
python 03_code/analysis/generate_paper_figures.py
```

## Scheduler at a glance

Three DVFS states via `scaling_max_freq` on the ondemand governor: S0 = 2400,
S1 = 1800, S2 = 1500 MHz. All thresholds are derived from measured quantities,
not tuned: sensor noise sigma_T = 0.5835 C (hysteresis floor >= 3*sigma_T),
post-EMA derivative noise sigma_Tdot = 0.0759 C/s (Tdot trigger = 6.6 *
sigma_Tdot = 0.5 C/s), thermal time constant tau = 10 s (dwell = 2*tau = 20 s),
N_confirm = 3 samples at 2 Hz.

## Dataset

Road-damage detector trained on the **USA subset of RDD2022** (Arya et al.,
2022, arXiv:2209.08538). This repository redistributes only our YOLO-format
annotation files and split manifests (70/10/20, seed 42, n = 3363/481/961);
obtain the images from the RDD2022 release.

## Frozen artifacts

`00_frozen_artifacts/SHA256SUMS.txt` locks the model weights, OpenVINO exports,
and benchmark video. Verify with:

```bash
cd 00_frozen_artifacts && sha256sum -c SHA256SUMS.txt
```

Large binaries are stored with Git LFS - install `git-lfs` before cloning.

## Raw power-meter data

Raw ChargerLAB POWER-Z KM003C exports (~7 GB across 46 SQLite databases) are not
redistributed - they require the proprietary PowerZ Windows software to read and
exceed practical LFS quotas. The derived per-run energy summaries used by the
paper are in `05_results/power_analysis_robust.csv` and
`05_results/sustainability_metrics.csv`; the analysis script that produced them
is `03_code/analysis/analyze_powerz_robust.py`. Raw `.db` files are available
on request.

## License

See `LICENSE` (once added). RDD2022 annotations derive from the original
dataset; see the RDD2022 release for dataset terms.