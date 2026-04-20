"""
verify_annotations.py
Visual verification of YOLO format annotations after XML conversion.
Randomly samples images and draws bounding boxes for human inspection.

Path change (2026-04-19): replaced hardcoded BASE_DIR with imports from
common.paths. No logic changes. See CHANGELOG.md.
"""
import os
import random
import sys
import cv2
import numpy as np
from pathlib import Path
import matplotlib.pyplot as plt

# ---- cross-platform path resolution ----------------------------------------
# Insert repo root so 'common.paths' is importable regardless of cwd.
_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))
from common.paths import PROCESSED_YOLO_DIR, RESULTS_DIR  # noqa: E402
# ----------------------------------------------------------------------------

# ============= CONFIGURATION =============
SPLIT = "train"       # Can be "train", "val", or "test"
NUM_SAMPLES = 50      # Number of random images to verify
RANDOM_SEED = 42      # FIXED SEED FOR REPRODUCIBILITY
CLASSES = ["D00", "D10", "D20", "D40"]
COLORS = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0)]  # BGR colors

# Derived paths — all come from common.paths, work on Windows and Pi.
IMAGE_DIR = PROCESSED_YOLO_DIR / SPLIT / "images"
LABEL_DIR = PROCESSED_YOLO_DIR / SPLIT / "labels"
OUTPUT_DIR = RESULTS_DIR / "annotation_verification" / SPLIT
# =========================================


def read_yolo_label(label_path, img_width, img_height):
    """
    Read YOLO format label file and convert to pixel coordinates.
    YOLO format: class_id x_center y_center width height (normalized 0-1)
    """
    boxes = []
    class_ids = []

    if not os.path.exists(label_path):
        return boxes, class_ids

    with open(label_path, 'r') as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) != 5:
                continue

            class_id = int(parts[0])
            x_center = float(parts[1]) * img_width
            y_center = float(parts[2]) * img_height
            width = float(parts[3]) * img_width
            height = float(parts[4]) * img_height

            # Convert to x1, y1, x2, y2 format
            x1 = int(x_center - width / 2)
            y1 = int(y_center - height / 2)
            x2 = int(x_center + width / 2)
            y2 = int(y_center + height / 2)

            boxes.append([x1, y1, x2, y2])
            class_ids.append(class_id)

    return boxes, class_ids


def draw_boxes(image, boxes, class_ids):
    """Draw bounding boxes on image."""
    img_copy = image.copy()

    for box, class_id in zip(boxes, class_ids):
        x1, y1, x2, y2 = box
        color = COLORS[class_id % len(COLORS)]

        cv2.rectangle(img_copy, (x1, y1), (x2, y2), color, 2)

        label = CLASSES[class_id]
        (w, h), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        cv2.rectangle(img_copy, (x1, y1 - h - 5), (x1 + w + 5, y1), color, -1)
        cv2.putText(img_copy, label, (x1 + 2, y1 - 2),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

    return img_copy


def verify_annotations():
    """Main verification function."""
    random.seed(RANDOM_SEED)
    print(f"Random seed locked: {RANDOM_SEED}")
    print(f"Image dir : {IMAGE_DIR}")
    print(f"Label dir : {LABEL_DIR}")
    print(f"Output dir: {OUTPUT_DIR}")

    if not IMAGE_DIR.exists():
        raise FileNotFoundError(f"Image directory not found: {IMAGE_DIR}")
    if not LABEL_DIR.exists():
        raise FileNotFoundError(f"Label directory not found: {LABEL_DIR}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    all_images = [f for f in os.listdir(IMAGE_DIR) if f.endswith('.jpg')]
    if not all_images:
        raise RuntimeError(f"No .jpg images found in {IMAGE_DIR}")

    sample_size = min(NUM_SAMPLES, len(all_images))
    sampled_images = random.sample(all_images, sample_size)
    print(f"\nVerifying {sample_size} randomly sampled images from {SPLIT} split...")

    verification_log = []

    for i, img_file in enumerate(sampled_images):
        img_path = IMAGE_DIR / img_file
        label_path = LABEL_DIR / (Path(img_file).stem + ".txt")

        image = cv2.imread(str(img_path))
        if image is None:
            print(f"  Could not read image: {img_file}")
            continue

        img_height, img_width = image.shape[:2]
        boxes, class_ids = read_yolo_label(label_path, img_width, img_height)
        verified_image = draw_boxes(image, boxes, class_ids)

        output_path = OUTPUT_DIR / f"verified_{i:03d}_{img_file}"
        cv2.imwrite(str(output_path), verified_image)

        log_entry = {
            'image': img_file,
            'num_boxes': len(boxes),
            'class_ids': class_ids,
            'classes': [CLASSES[cid] for cid in class_ids],
            'saved_as': f"verified_{i:03d}_{img_file}",
        }
        verification_log.append(log_entry)
        print(f"  {img_file}: {len(boxes)} boxes detected")

    # Summary report
    print("\n" + "=" * 50)
    print("VERIFICATION SUMMARY")
    print("=" * 50)
    print(f"Split           : {SPLIT}")
    print(f"Random seed     : {RANDOM_SEED}")
    print(f"Images verified : {len(verification_log)}")

    total_boxes = sum(e['num_boxes'] for e in verification_log)
    print(f"Total boxes     : {total_boxes}")

    class_counts = {cls: 0 for cls in CLASSES}
    for entry in verification_log:
        for cls_name in entry['classes']:
            class_counts[cls_name] += 1

    print("\nClass distribution in verified samples:")
    for cls, count in class_counts.items():
        if count > 0:
            pct = (count / total_boxes) * 100
            print(f"  {cls}: {count} instances ({pct:.1f}%)")

    create_verification_mosaic(OUTPUT_DIR, verification_log[:9])

    print(f"\nVerification complete!")
    print(f"Verified images saved to: {OUTPUT_DIR}")
    print("\nTo reproduce this exact verification:")
    print(f"  RANDOM_SEED = {RANDOM_SEED}")
    print(f"  NUM_SAMPLES = {NUM_SAMPLES}")


def create_verification_mosaic(output_dir, log_entries, grid_size=(3, 3)):
    """Create a 3×3 mosaic of verified images for paper inclusion."""
    if len(log_entries) == 0:
        return

    mosaic_paths = []
    for entry in log_entries[:9]:
        img_path = output_dir / entry['saved_as']
        if img_path.exists():
            mosaic_paths.append(img_path)

    if len(mosaic_paths) < 4:
        return

    fig, axes = plt.subplots(3, 3, figsize=(15, 15))
    fig.suptitle(
        f'Annotation Verification Samples ({SPLIT} set, seed={RANDOM_SEED})',
        fontsize=16,
    )

    for idx, img_path in enumerate(mosaic_paths):
        if idx >= 9:
            break
        row, col = idx // 3, idx % 3
        img = cv2.cvtColor(cv2.imread(str(img_path)), cv2.COLOR_BGR2RGB)
        axes[row, col].imshow(img)
        axes[row, col].axis('off')
        axes[row, col].set_title(
            img_path.name.replace('verified_', ''), fontsize=8
        )

    plt.tight_layout()
    mosaic_path = output_dir / f'verification_mosaic_{SPLIT}_seed{RANDOM_SEED}.png'
    plt.savefig(str(mosaic_path), dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  Mosaic saved to: {mosaic_path}")


if __name__ == "__main__":
    random.seed(RANDOM_SEED)
    verify_annotations()
