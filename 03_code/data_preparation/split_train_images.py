import os
import shutil
import random
import cv2
import xml.etree.ElementTree as ET
from tqdm import tqdm

# --- CONFIGURATION ---
RANDOM_SEED = 42
random.seed(RANDOM_SEED)

BASE_DIR = r"C:\Users\User\Desktop\research_project"
RAW_IMG_DIR = os.path.join(BASE_DIR, "02_data", "rdd2022_raw", "United_States", "train", "images")
RAW_XML_DIR = os.path.join(BASE_DIR, "02_data", "rdd2022_raw", "United_States", "train", "annotations", "xmls")
OUTPUT_DIR = os.path.join(BASE_DIR, "02_data", "processed_yolo")
VIDEO_OUT = os.path.join(BASE_DIR, "02_data", "videos", "thermal_benchmark_30fps.mp4")

CLASSES = ["D00", "D10", "D20", "D40"]

def convert_bbox(size, box):
    dw, dh = 1. / size[0], 1. / size[1]
    return ((box[0] + box[1]) / 2. * dw, (box[2] + box[3]) / 2. * dh, 
            (box[1] - box[0]) * dw, (box[3] - box[2]) * dh)

def main():
    # 1. Reproducible Sort & Split
    all_files = sorted([f[:-4] for f in os.listdir(RAW_IMG_DIR) if f.endswith('.jpg')])
    random.shuffle(all_files)
    
    train_end = int(len(all_files) * 0.7)
    val_end = int(len(all_files) * 0.8)
    subsets = {
        'train': all_files[:train_end],
        'val': all_files[train_end:val_end],
        'test': all_files[val_end:]
    }

    # 2. Process Folders
    for subset, names in subsets.items():
        img_out = os.path.join(OUTPUT_DIR, subset, "images")
        lbl_out = os.path.join(OUTPUT_DIR, subset, "labels")
        os.makedirs(img_out, exist_ok=True)
        os.makedirs(lbl_out, exist_ok=True)

        for name in tqdm(names, desc=f"Splitting {subset}"):
            shutil.copy(os.path.join(RAW_IMG_DIR, f"{name}.jpg"), os.path.join(img_out, f"{name}.jpg"))
            xml_path = os.path.join(RAW_XML_DIR, f"{name}.xml")
            if os.path.exists(xml_path):
                root = ET.parse(xml_path).getroot()
                size = root.find('size')
                w, h = int(size.find('width').text), int(size.find('height').text)
                with open(os.path.join(lbl_out, f"{name}.txt"), 'w') as f:
                    for obj in root.iter('object'):
                        cls = obj.find('name').text
                        if cls not in CLASSES: continue
                        bbox = obj.find('bndbox')
                        pts = (float(bbox.find('xmin').text), float(bbox.find('xmax').text),
                               float(bbox.find('ymin').text), float(bbox.find('ymax').text))
                        f.write(f"{CLASSES.index(cls)} {' '.join([f'{c:.6f}' for c in convert_bbox((w, h), pts)])}\n")

    # 3. Stitch 20% Test Set into 30 FPS Video
    test_imgs = sorted([os.path.join(OUTPUT_DIR, "test", "images", f"{n}.jpg") for n in subsets['test']])
    frame = cv2.imread(test_imgs[0])
    h, w, _ = frame.shape
    out = cv2.VideoWriter(VIDEO_OUT, cv2.VideoWriter_fourcc(*'mp4v'), 30, (w, h))
    for img_path in tqdm(test_imgs, desc="Stitching Video"):
        out.write(cv2.imread(img_path))
    out.release()
    print(f"Pipeline Complete. Benchmark video saved to {VIDEO_OUT}")

if __name__ == "__main__":
    main()