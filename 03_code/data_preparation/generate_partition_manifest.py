"""
generate_partition_manifest.py
Produces a reproducibility manifest of the train/val/test partition.
Lists every image + label file with SHA256 hashes.
Run once after partition is finalized; output goes to
00_frozen_artifacts/dataset_manifests/
"""

import os
import hashlib
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(r"C:\Users\User\Desktop\research_project")
PROCESSED_DIR = BASE_DIR / "02_data" / "processed_yolo"
OUTPUT_DIR = BASE_DIR / "00_frozen_artifacts" / "dataset_manifests"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def sha256_of_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def manifest_subset(subset):
    img_dir = PROCESSED_DIR / subset / "images"
    lbl_dir = PROCESSED_DIR / subset / "labels"

    entries = []
    for img_path in sorted(img_dir.iterdir()):
        if img_path.suffix.lower() not in (".jpg", ".jpeg", ".png"):
            continue
        stem = img_path.stem
        lbl_path = lbl_dir / f"{stem}.txt"
        img_hash = sha256_of_file(img_path)
        lbl_hash = sha256_of_file(lbl_path) if lbl_path.exists() else "NO_LABEL"
        entries.append((stem, img_hash, lbl_hash))

    return entries


def main():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    for subset in ["train", "val", "test"]:
        print(f"Processing {subset}...")
        entries = manifest_subset(subset)
        output_path = OUTPUT_DIR / f"{subset}_manifest.txt"

        with open(output_path, "w", encoding="utf-8") as f:
            f.write(f"# Partition manifest for {subset} split\n")
            f.write(f"# Generated: {timestamp}\n")
            f.write(f"# Seed: 42 (from split_train_images.py)\n")
            f.write(f"# File count: {len(entries)}\n")
            f.write(f"# Format: <stem>\\t<image_sha256>\\t<label_sha256>\n")
            f.write("\n")
            for stem, img_hash, lbl_hash in entries:
                f.write(f"{stem}\t{img_hash}\t{lbl_hash}\n")

        print(f"  {subset}: {len(entries)} files -> {output_path}")


if __name__ == "__main__":
    main()
