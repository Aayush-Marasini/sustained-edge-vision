"""
class_distribution.py
Prints class instance counts and percentages for a given YOLO split.

Path change (2026-04-19): replaced hardcoded LABEL_DIR with import from
common.paths. No logic changes. See CHANGELOG.md.
"""
import os
import sys
from collections import Counter
from pathlib import Path

# ---- cross-platform path resolution ----------------------------------------
_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))
from common.paths import PROCESSED_YOLO_DIR  # noqa: E402
# ----------------------------------------------------------------------------

# ============= CONFIGURATION =============
SPLIT = "train"  # Change to "val" or "test" as needed
CLASSES = ["D00", "D10", "D20", "D40"]

# Derived path — works on Windows and Pi.
LABEL_DIR = PROCESSED_YOLO_DIR / SPLIT / "labels"
# =========================================


def check_distribution():
    if not LABEL_DIR.exists():
        raise FileNotFoundError(f"Label directory not found: {LABEL_DIR}")

    counts = Counter()
    label_files = [f for f in os.listdir(LABEL_DIR) if f.endswith('.txt')]

    if not label_files:
        raise RuntimeError(f"No .txt label files found in {LABEL_DIR}")

    for file in label_files:
        with open(LABEL_DIR / file, 'r') as f:
            for line in f:
                parts = line.strip().split()
                if parts:
                    counts[int(parts[0])] += 1

    total = sum(counts.values())
    print(f"--- Dataset Class Distribution ({SPLIT} split) ---")
    print(f"Label dir: {LABEL_DIR}")
    print(f"Total instances: {total}\n")
    for idx, name in enumerate(CLASSES):
        count = counts[idx]
        pct = count / total * 100 if total > 0 else 0.0
        print(f"  {name}: {count} instances ({pct:.2f}%)")


if __name__ == "__main__":
    check_distribution()
