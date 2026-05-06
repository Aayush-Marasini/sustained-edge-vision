# 03_code/analysis/measure_deployed_map.py
"""
Task 19: Measure mAP50 of the deployed OpenVINO FP32 model on the
validation set (481 images) using the Pi inference pipeline.
Compares to Ultralytics training mAP50 = 0.533.

Run on Pi:
  sudo /home/raspberrypi/yolov8_env/bin/python \
      03_code/analysis/measure_deployed_map.py

Output: 05_results/deployed_map_results.json
"""
import json
import time
import numpy as np
from pathlib import Path
from collections import defaultdict

# ── Paths ─────────────────────────────────────────────────────────────
REPO_ROOT  = Path(__file__).resolve().parents[2]
MODEL_DIR  = REPO_ROOT / "02_models/openvino/yolov8n_fp32"
VAL_IMAGES = REPO_ROOT / "04_workload/val_images"   # 481 images
VAL_LABELS = REPO_ROOT / "04_workload/val_labels"   # YOLO format .txt
OUT_FILE   = REPO_ROOT / "05_results/deployed_map_results.json"

# RDD2022 classes
CLASSES = ["D00", "D10", "D20", "D40"]
NC = len(CLASSES)

# IoU threshold for mAP50
IOU_THRESH = 0.50
CONF_THRESH = 0.001   # low threshold to collect all detections for PR curve


def iou(box_a, box_b):
    """box format: [x1, y1, x2, y2]"""
    xi1 = max(box_a[0], box_b[0])
    yi1 = max(box_a[1], box_b[1])
    xi2 = min(box_a[2], box_b[2])
    yi2 = min(box_a[3], box_b[3])
    inter = max(0, xi2-xi1) * max(0, yi2-yi1)
    a_area = (box_a[2]-box_a[0]) * (box_a[3]-box_a[1])
    b_area = (box_b[2]-box_b[0]) * (box_b[3]-box_b[1])
    union = a_area + b_area - inter
    return inter / union if union > 0 else 0.0


def load_ground_truth(label_path: Path, img_w: int, img_h: int) -> list:
    """Load YOLO format labels → list of [cls, x1, y1, x2, y2]"""
    boxes = []
    if not label_path.exists():
        return boxes
    with open(label_path) as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) != 5:
                continue
            cls = int(parts[0])
            cx, cy, bw, bh = map(float, parts[1:])
            x1 = (cx - bw/2) * img_w
            y1 = (cy - bh/2) * img_h
            x2 = (cx + bw/2) * img_w
            y2 = (cy + bh/2) * img_h
            boxes.append([cls, x1, y1, x2, y2])
    return boxes


def compute_ap(recalls, precisions):
    """Compute AP using 11-point interpolation."""
    ap = 0.0
    for t in np.arange(0, 1.1, 0.1):
        p_at_r = [p for r, p in zip(recalls, precisions) if r >= t]
        ap += max(p_at_r) if p_at_r else 0.0
    return ap / 11.0


def main():
    # ── Load model ────────────────────────────────────────────────────
    from openvino.runtime import Core
    import cv2

    print("Loading OpenVINO model...")
    ie   = Core()
    model = ie.read_model(str(MODEL_DIR / "yolov8n.xml"))
    compiled = ie.compile_model(model, "CPU")
    infer_req = compiled.create_infer_request()

    input_layer  = compiled.input(0)
    output_layer = compiled.output(0)
    input_shape  = input_layer.shape   # [1, 3, 640, 640]
    H, W = int(input_shape[2]), int(input_shape[3])

    print(f"Model input: {input_shape}")

    # ── Find val images ───────────────────────────────────────────────
    img_paths = sorted(list(VAL_IMAGES.glob("*.jpg")) +
                       list(VAL_IMAGES.glob("*.png")))
    if not img_paths:
        raise FileNotFoundError(
            f"No images found in {VAL_IMAGES}\n"
            f"Copy val images there first:\n"
            f"  mkdir -p {VAL_IMAGES}\n"
            f"  # copy from RDD2022 val split"
        )
    print(f"Found {len(img_paths)} val images")

    # ── Per-class detection accumulator ──────────────────────────────
    # detections[cls] = [(conf, tp), ...] sorted by conf descending
    all_detections = defaultdict(list)  # cls → [(conf, is_tp)]
    n_gt = defaultdict(int)             # cls → count of GT boxes

    t0 = time.time()
    for idx, img_path in enumerate(img_paths):
        if idx % 50 == 0:
            elapsed = time.time() - t0
            print(f"  [{idx}/{len(img_paths)}] {elapsed:.1f}s elapsed")

        # Load image
        img_bgr = cv2.imread(str(img_path))
        if img_bgr is None:
            continue
        img_h_orig, img_w_orig = img_bgr.shape[:2]

        # Preprocess: letterbox to 640×640
        scale = min(W / img_w_orig, H / img_h_orig)
        new_w = int(img_w_orig * scale)
        new_h = int(img_h_orig * scale)
        resized = cv2.resize(img_bgr, (new_w, new_h))
        padded  = np.full((H, W, 3), 114, dtype=np.uint8)
        dw = (W - new_w) // 2
        dh = (H - new_h) // 2
        padded[dh:dh+new_h, dw:dw+new_w] = resized

        inp = padded[:, :, ::-1].astype(np.float32) / 255.0
        inp = inp.transpose(2, 0, 1)[np.newaxis]

        # Infer
        infer_req.infer({input_layer: inp})
        output = infer_req.get_output_tensor(0).data  # [1, 8, 8400]

        # Parse output: [x_c, y_c, w, h, cls0..cls3] × 8400
        preds = output[0].T   # [8400, 8]
        boxes_xywh = preds[:, :4]
        scores     = preds[:, 4:]

        cls_ids   = scores.argmax(axis=1)
        confs     = scores.max(axis=1)

        # Filter by confidence
        mask = confs > CONF_THRESH
        boxes_xywh = boxes_xywh[mask]
        cls_ids    = cls_ids[mask]
        confs      = confs[mask]

        # Convert xywh (model coords) to xyxy (original image coords)
        detections_img = []
        for (cx, cy, bw, bh), cls, conf in zip(boxes_xywh, cls_ids, confs):
            # Undo letterbox padding and scale
            x1 = ((cx - bw/2) - dw) / scale
            y1 = ((cy - bh/2) - dh) / scale
            x2 = ((cx + bw/2) - dw) / scale
            y2 = ((cy + bh/2) - dh) / scale
            x1 = max(0, x1); y1 = max(0, y1)
            x2 = min(img_w_orig, x2); y2 = min(img_h_orig, y2)
            detections_img.append((int(cls), float(conf), [x1,y1,x2,y2]))

        # Load ground truth
        label_path = VAL_LABELS / (img_path.stem + ".txt")
        gt_boxes   = load_ground_truth(label_path, img_w_orig, img_h_orig)

        for cls in range(NC):
            n_gt[cls] += sum(1 for g in gt_boxes if g[0] == cls)

        # Match detections to GT per class
        for cls in range(NC):
            dets_cls = [(c, b) for (cc, c, b) in detections_img if cc == cls]
            dets_cls.sort(key=lambda x: x[0], reverse=True)
            gt_cls   = [g[1:] for g in gt_boxes if g[0] == cls]
            matched  = [False] * len(gt_cls)

            for conf, det_box in dets_cls:
                best_iou = 0.0
                best_j   = -1
                for j, gt_box in enumerate(gt_cls):
                    if matched[j]:
                        continue
                    iou_val = iou(det_box, gt_box)
                    if iou_val > best_iou:
                        best_iou = iou_val
                        best_j   = j
                is_tp = (best_iou >= IOU_THRESH and best_j >= 0)
                if is_tp:
                    matched[best_j] = True
                all_detections[cls].append((conf, int(is_tp)))

    # ── Compute per-class AP and mAP50 ───────────────────────────────
    print("\nComputing mAP50...")
    aps = {}
    for cls in range(NC):
        dets = sorted(all_detections[cls], key=lambda x: x[0], reverse=True)
        n    = n_gt[cls]
        if n == 0 or not dets:
            aps[cls] = 0.0
            continue
        tp_cum = 0; fp_cum = 0
        recalls = []; precisions = []
        for conf, is_tp in dets:
            if is_tp: tp_cum += 1
            else:     fp_cum += 1
            recalls.append(tp_cum / n)
            precisions.append(tp_cum / (tp_cum + fp_cum))
        aps[cls] = compute_ap(recalls, precisions)

    map50 = float(np.mean(list(aps.values())))
    total_time = time.time() - t0

    results = {
        "map50_deployed_openvino": round(map50, 4),
        "map50_ultralytics_training": 0.533,
        "delta": round(map50 - 0.533, 4),
        "per_class": {
            CLASSES[c]: round(aps[c], 4) for c in range(NC)
        },
        "n_gt_per_class": {CLASSES[c]: n_gt[c] for c in range(NC)},
        "n_images": len(img_paths),
        "model": str(MODEL_DIR),
        "iou_threshold": IOU_THRESH,
        "conf_threshold": CONF_THRESH,
        "inference_time_s": round(total_time, 1),
    }

    print("\n" + "="*60)
    print("DEPLOYED MODEL mAP50 RESULTS (Task 19)")
    print("="*60)
    print(f"  OpenVINO deployed mAP50: {map50:.4f}")
    print(f"  Ultralytics training:    0.5330")
    print(f"  Delta:                   {map50-0.533:+.4f}")
    print()
    for cls in range(NC):
        print(f"  {CLASSES[cls]}: AP50={aps[cls]:.4f}  "
              f"(GT instances: {n_gt[cls]})")
    print(f"\nTotal inference time: {total_time:.1f}s")
    print("="*60)

    with open(OUT_FILE, "w") as f:
        json.dump(results, f, indent=2)
    print(f"Saved: {OUT_FILE}")


if __name__ == "__main__":
    main()