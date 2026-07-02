# Workload Videos

The paper's benchmark video is `thermal_benchmark_30fps.mp4`, located at
`00_frozen_artifacts/benchmark_workloads/thermal_benchmark_30fps.mp4` and
locked via SHA256SUMS.txt.

## What is the benchmark video?

- The test split of the RDD2022-USA subset (n=961 disjoint images, seed 42)
- Stitched at 30 FPS via OpenCV into a 32-second video
- Looped ~56 times to cover each 30-minute experimental run
- Constructed so no frame appears in training or validation splits, forcing
  full feature extraction on every frame

## Reproducing the benchmark video

Run `03_code/workload/build_benchmark_video.py` on the RDD2022-USA test split.
The output must match SHA256 `67fb8f1f06b21c693e74c140040f76e6f33a8b02062910c9384c704df0f8dab2`.

## Historical / development videos

This directory previously hosted a Pexels traffic video used for early
pipeline testing (Phase D). That video was NOT used for any results in the
paper and is intentionally excluded from Git.