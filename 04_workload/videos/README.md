# Workload Videos

This directory contains test videos for YOLOv8n inference workload.

## Videos NOT in Git

Video files (.mp4, .avi) are excluded from version control due to size.
Download them using the instructions below.

## Test Video (Phase D Development)

**File:** `test_traffic.mp4`
**Source:** Pexels (CC0 license)
**URL:** https://videos.pexels.com/video-files/854100/854100-hd_1920_1080_25fps.mp4
**Specs:** 1920×1080, 25 FPS, 7.8 MB, 393 frames (~15.7 seconds)

```bash
cd ~/sustained-edge-vision/04_workload/videos
wget -O test_traffic.mp4 "https://videos.pexels.com/video-files/854100/854100-hd_1920_1080_25fps.mp4"
```

## Production Videos (Phase D Baseline Runs)

TBD: Curate 2-3 moderate-complexity videos per WorkPlan Task 13.

Criteria:
- Creative Commons (CC-BY or CC0)
- 1920×1080 or 1280×720, 30 FPS
- Moderate object density (5-15 detectable objects/frame)
- Realistic scenes (traffic, warehouse, retail)
- Duration: 30-60 seconds

## Provenance

- test_traffic.mp4: Downloaded 2026-04-26 from Pexels
