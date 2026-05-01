\# OpenVINO Models Deployed on Pi 5



This document tracks which model binaries are currently deployed to the Pi

and verifies their provenance against the frozen artifacts.



\## yolov8n\_fp32/

\- \*\*Source:\*\* 00\_frozen\_artifacts/yolov8n\_baseline\_seed42/weights/openvino\_fp32/

\- \*\*SHA256 (yolov8n.bin):\*\* 0de2334a04c4b808df26acd7c22cfea3638d4d0204815ad2056cd0296ba8aa27

\- \*\*Classes:\*\* D00, D10, D20, D40 (RDD2022 road damage)

\- \*\*Exported:\*\* 2026-04-01, Ultralytics 8.4.7, OpenVINO 2026.0.0

\- \*\*Deployed to Pi:\*\* 2026-04-29

\- \*\*Verified FPS (passive, n=3, 5min):\*\* 14.579 ± 0.019

\- \*\*Output shape:\*\* \[1,8,8400]



\## yolov8n\_int8/

\- \*\*Source:\*\* 00\_frozen\_artifacts/yolov8n\_baseline\_seed42/weights/openvino\_int8/

\- \*\*SHA256 (yolov8n.bin):\*\* 74ca338c4a866cb803bb68bf39f5f798b78cd110c45f1e4c2f3a77582833df51

\- \*\*Classes:\*\* D00, D10, D20, D40 (RDD2022 road damage)

\- \*\*Calibration:\*\* NNCF 3.0.0 PTQ, 481 validation images (full split, fraction=1.0)

\- \*\*Exported:\*\* 2026-04-01

\- \*\*Deployed to Pi:\*\* 2026-05-01

\- \*\*Verified FPS (passive, 200 frames, no telemetry):\*\* 8.69 FPS, 115 ms latency

\- \*\*Output shape:\*\* \[1,8,8400]



\## Anomaly: INT8 slower than FP32 (documented)



INT8 inference is \*\*42% slower\*\* than FP32 on the Pi 5 (8.69 vs 14.93 FPS).

This is a known characteristic of OpenVINO 2026.0 on ARM Cortex-A76:



1\. The OpenVINO runtime does not aggressively use ARM SDOT/UDOT INT8

&#x20;  instructions on the Pi 5 in this version.

2\. Quantize/dequantize operations at non-INT8 layer boundaries dominate

&#x20;  for small models like YOLOv8n.

3\. NNCF default quantization patterns optimize for Intel deployment.



\*\*Implication for paper §V:\*\* The FP32 ↔ INT8 trade-off is NOT pure

speedup — it must be evaluated on energy/inference (J/frame) rather

than FPS alone. The Pareto frontier becomes non-trivial precisely

because of this anomaly, which motivates the scheduler's role in

choosing precision dynamically based on runtime state.



\*\*Pre-run verification command (for paper-quality runs):\*\*



&#x20;   sha256sum 02\_models/openvino/yolov8n\_fp32/yolov8n.bin

&#x20;   sha256sum 02\_models/openvino/yolov8n\_int8/yolov8n.bin



Both must match the SHA256 values above.

