import os
from collections import Counter

LABEL_DIR = r"C:\Users\User\Desktop\research_project\02_data\processed_yolo\train\labels"
CLASSES = ["D00", "D10", "D20", "D40"]

def check_distribution():
    counts = Counter()
    for file in os.listdir(LABEL_DIR):
        with open(os.path.join(LABEL_DIR, file), 'r') as f:
            for line in f:
                counts[int(line.split()[0])] += 1
    
    print("--- Dataset Class Distribution ---")
    for idx, name in enumerate(CLASSES):
        print(f"{name}: {counts[idx]} instances ({counts[idx]/sum(counts.values())*100:.2f}%)")

check_distribution()