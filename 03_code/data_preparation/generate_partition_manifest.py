"""
generate_partition_manifest.py
Produces a reproducibility manifest of the train/val/test partition.
Lists every image + label file with SHA256 hashes.
Run once after partition is finalized; output goes to
00_frozen_artifacts/dataset_manifests/

Path change (2026-04-25): replaced hardcoded Windows BASE_DIR with
imports from common.paths. Output timestamp now in UTC. No logic
changes to hash computation or output format.
"""

import sys
import hashlib
from pathlib import Path
from datetime import datetime, timezone

# ---- cross-platform path resolution ----------------------------------------
_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))
from common.paths import PROCESSED_YOLO_DIR, DATASET_MANIFESTS  # noqa: E402
# ----------------------------------------------------------------------------


def sha256_of_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def manifest_subset(subset: str):
    img_dir = PROCESSED_YOLO_DIR / subset / "images"
    lbl_dir = PROCESSED_YOLO_DIR / subset / "labels"

    if not img_dir.exists():
        raise FileNotFoundError(f"Image directory not found: {img_dir}")
    if not lbl_dir.exists():
        raise FileNotFoundError(f"Label directory not found: {lbl_dir}")

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
    DATASET_MANIFESTS.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    print(f"Processed YOLO dir: {PROCESSED_YOLO_DIR}")
    print(f"Output dir        : {DATASET_MANIFESTS}")
    print(f"Timestamp (UTC)   : {timestamp}")
    print()

    for subset in ["train", "val", "test"]:
        print(f"Processing {subset}...")
        entries = manifest_subset(subset)
        output_path = DATASET_MANIFESTS / f"{subset}_manifest.txt"

        with open(output_path, "w", encoding="utf-8") as f:
            f.write(f"# Partition manifest for {subset} split\n")
            f.write(f"# Generated (UTC): {timestamp}\n")
            f.write(f"# Seed: 42 (from split_train_images.py)\n")
            f.write(f"# File count: {len(entries)}\n")
            f.write(f"# Format: <stem>\\t<image_sha256>\\t<label_sha256>\n")
            f.write("\n")
            for stem, img_hash, lbl_hash in entries:
                f.write(f"{stem}\t{img_hash}\t{lbl_hash}\n")

        print(f"  {subset}: {len(entries)} files -> {output_path}")


if __name__ == "__main__":
    main()