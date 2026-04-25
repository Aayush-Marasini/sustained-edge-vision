"""
split_train_images.py
Splits the RDD2022-US dataset into train/val/test, converts XML annotations
to YOLO format, and stitches the test set into a 30 FPS benchmark video.

Path change (2026-04-19): replaced all hardcoded Windows paths with imports
from common.paths. No logic changes (split ratios, seed, class list, file
operations are identical). See CHANGELOG.md.
"""
import os
import shutil
import random
import sys
import cv2
import xml.etree.ElementTree as ET
from pathlib import Path
from tqdm import tqdm

# ---- cross-platform path resolution ----------------------------------------
_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))
from common.paths import (  # noqa: E402
    RAW_DATASET_DIR,
    PROCESSED_YOLO_DIR,
    VIDEOS_DIR,
)
# ----------------------------------------------------------------------------

# ============= CONFIGURATION =============
RANDOM_SEED = 42  # locks partition; do NOT change without invalidating frozen artifacts.

CLASSES = ["D00", "D10", "D20", "D40"]

# Derived paths — all from common.paths, no hardcoding.
RAW_IMG_DIR = RAW_DATASET_DIR / "United_States" / "train" / "images"
RAW_XML_DIR = RAW_DATASET_DIR / "United_States" / "train" / "annotations" / "xmls"
OUTPUT_DIR  = PROCESSED_YOLO_DIR
VIDEO_OUT   = VIDEOS_DIR / "thermal_benchmark_30fps.mp4"
# =========================================


def convert_bbox(size, box):
    """Convert Pascal VOC bbox to YOLO normalized format."""
    dw, dh = 1.0 / size[0], 1.0 / size[1]
    return (
        (box[0] + box[1]) / 2.0 * dw,
        (box[2] + box[3]) / 2.0 * dh,
        (box[1] - box[0]) * dw,
        (box[3] - box[2]) * dh,
    )


def main():
    print(f"Random seed     : {RANDOM_SEED}")
    print(f"Raw images      : {RAW_IMG_DIR}")
    print(f"Raw annotations : {RAW_XML_DIR}")
    print(f"Output dir      : {OUTPUT_DIR}")
    print(f"Benchmark video : {VIDEO_OUT}")

    if not RAW_IMG_DIR.exists():
        raise FileNotFoundError(f"Raw image directory not found: {RAW_IMG_DIR}")
    if not RAW_XML_DIR.exists():
        raise FileNotFoundError(f"Raw XML directory not found: {RAW_XML_DIR}")

    # Ensure output directories exist.
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    VIDEOS_DIR.mkdir(parents=True, exist_ok=True)

    all_files = sorted([f[:-4] for f in os.listdir(RAW_IMG_DIR) if f.endswith('.jpg')])
    # Use a local RNG so import-time side effects cannot perturb the shuffle.
    # Bit-identical to the global-seeded version when run from a clean interpreter,
    # which is how the frozen partition was produced.
    rng = random.Random(RANDOM_SEED)
    rng.shuffle(all_files)

    train_end = int(len(all_files) * 0.7)
    val_end   = int(len(all_files) * 0.8)
    subsets = {
        'train': all_files[:train_end],
        'val':   all_files[train_end:val_end],
        'test':  all_files[val_end:],
    }

    # 2. Process folders
    for subset, names in subsets.items():
        img_out = OUTPUT_DIR / subset / "images"
        lbl_out = OUTPUT_DIR / subset / "labels"
        img_out.mkdir(parents=True, exist_ok=True)
        lbl_out.mkdir(parents=True, exist_ok=True)

        for name in tqdm(names, desc=f"Splitting {subset}"):
            shutil.copy(RAW_IMG_DIR / f"{name}.jpg", img_out / f"{name}.jpg")
            xml_path = RAW_XML_DIR / f"{name}.xml"
            if xml_path.exists():
                root = ET.parse(xml_path).getroot()
                size_el = root.find('size')
                w = int(size_el.find('width').text)
                h = int(size_el.find('height').text)
                with open(lbl_out / f"{name}.txt", 'w', encoding="utf-8") as lf:
                    for obj in root.iter('object'):
                        cls = obj.find('name').text
                        if cls not in CLASSES:
                            continue
                        bbox = obj.find('bndbox')
                        pts = (
                            float(bbox.find('xmin').text),
                            float(bbox.find('xmax').text),
                            float(bbox.find('ymin').text),
                            float(bbox.find('ymax').text),
                        )
                        yolo_coords = convert_bbox((w, h), pts)
                        lf.write(
                            f"{CLASSES.index(cls)} "
                            + " ".join(f"{c:.6f}" for c in yolo_coords)
                            + "\n"
                        )

# 3. Stitch test set into 30 FPS benchmark video.
    #
    # Reproducibility note: the H.264/MPEG-4 encoder used by OpenCV's
    # VideoWriter is platform-dependent (linked FFmpeg / system codecs),
    # so two machines running this script on identical inputs may
    # produce binary-different videos. The canonical benchmark video
    # is therefore distributed as a frozen artifact in
    # 00_frozen_artifacts/benchmark_workloads/ with its SHA256 hash
    # recorded in SHA256SUMS.txt. This script documents the source
    # frame ordering and FPS; it is not a bit-reproducible regenerator.
    test_imgs = sorted([
        OUTPUT_DIR / "test" / "images" / f"{n}.jpg"
        for n in subsets['test']
    ])
    if not test_imgs:
        raise RuntimeError("No test images to stitch.")

    first_frame = cv2.imread(str(test_imgs[0]))
    if first_frame is None:
        raise RuntimeError(f"Could not read first test image: {test_imgs[0]}")
    h_f, w_f, _ = first_frame.shape

    out = cv2.VideoWriter(
        str(VIDEO_OUT),
        cv2.VideoWriter_fourcc(*'mp4v'),
        30,
        (w_f, h_f),
    )
    if not out.isOpened():
        raise RuntimeError(f"VideoWriter failed to open at {VIDEO_OUT}")

    written = 0
    for img_path in tqdm(test_imgs, desc="Stitching video"):
        frame = cv2.imread(str(img_path))
        if frame is None:
            raise RuntimeError(f"Failed to read frame: {img_path}")
        if frame.shape != (h_f, w_f, 3):
            raise RuntimeError(
                f"Frame shape mismatch at {img_path}: "
                f"expected {(h_f, w_f, 3)}, got {frame.shape}"
            )
        out.write(frame)
        written += 1
    out.release()

    print(f"\nPipeline complete. Benchmark video saved to: {VIDEO_OUT}")
    print(f"  Frames written: {written}")
    print(f"  Resolution    : {w_f}x{h_f}")
    print(f"  FPS           : 30")


if __name__ == "__main__":
    main()
