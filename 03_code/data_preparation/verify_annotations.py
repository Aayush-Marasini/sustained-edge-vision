"""
verify_annotations.py
Visual verification of YOLO format annotations after XML conversion
Randomly samples images and draws bounding boxes for human inspection
"""

import os
import random
import cv2
import numpy as np
from pathlib import Path
import matplotlib.pyplot as plt

# ============= CONFIGURATION =============
BASE_DIR = r"C:\Users\User\Desktop\research_project"
SPLIT = "train"  # Can be "train", "val", or "test"
NUM_SAMPLES = 50  # Number of random images to verify
RANDOM_SEED = 42  # 🔴 FIXED SEED FOR REPRODUCIBILITY
CLASSES = ["D00", "D10", "D20", "D40"]
COLORS = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0)]  # BGR colors
# =========================================

def read_yolo_label(label_path, img_width, img_height):
    """
    Read YOLO format label file and convert to pixel coordinates
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
            x1 = int(x_center - width/2)
            y1 = int(y_center - height/2)
            x2 = int(x_center + width/2)
            y2 = int(y_center + height/2)
            
            boxes.append([x1, y1, x2, y2])
            class_ids.append(class_id)
    
    return boxes, class_ids

def draw_boxes(image, boxes, class_ids):
    """Draw bounding boxes on image"""
    img_copy = image.copy()
    
    for i, (box, class_id) in enumerate(zip(boxes, class_ids)):
        x1, y1, x2, y2 = box
        color = COLORS[class_id % len(COLORS)]
        
        # Draw rectangle
        cv2.rectangle(img_copy, (x1, y1), (x2, y2), color, 2)
        
        # Draw label background
        label = CLASSES[class_id]
        (w, h), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        cv2.rectangle(img_copy, (x1, y1 - h - 5), (x1 + w + 5, y1), color, -1)
        
        # Draw label text
        cv2.putText(img_copy, label, (x1 + 2, y1 - 2), 
                   cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
    
    return img_copy

def verify_annotations():
    """Main verification function"""
    
    # 🔴 SET SEED AT THE BEGINNING OF VERIFICATION
    random.seed(RANDOM_SEED)
    print(f"🔐 Using random seed: {RANDOM_SEED} for reproducibility")
    
    # Paths
    images_dir = os.path.join(BASE_DIR, "02_data", "processed_yolo", SPLIT, "images")
    labels_dir = os.path.join(BASE_DIR, "02_data", "processed_yolo", SPLIT, "labels")
    output_dir = os.path.join(BASE_DIR, "05_results", "annotation_verification")
    
    # Create output directory
    os.makedirs(output_dir, exist_ok=True)
    
    # Get all image files
    image_files = [f for f in os.listdir(images_dir) if f.endswith(('.jpg', '.png', '.jpeg'))]
    
    if len(image_files) == 0:
        print(f"❌ No images found in {images_dir}")
        return
    
    print(f"Found {len(image_files)} images in {SPLIT} split")
    
    # 🔴 RANDOM SAMPLING NOW USES THE FIXED SEED
    if NUM_SAMPLES < len(image_files):
        sampled_files = random.sample(image_files, NUM_SAMPLES)
    else:
        sampled_files = image_files
    
    print(f"Verifying {len(sampled_files)} random images...")
    
    verification_log = []
    
    for i, img_file in enumerate(sampled_files):
        # Get corresponding label file
        base_name = os.path.splitext(img_file)[0]
        label_file = base_name + ".txt"
        label_path = os.path.join(labels_dir, label_file)
        
        # Read image
        img_path = os.path.join(images_dir, img_file)
        image = cv2.imread(img_path)
        
        if image is None:
            print(f"⚠️ Could not read image: {img_file}")
            continue
        
        img_height, img_width = image.shape[:2]
        
        # Read YOLO labels
        boxes, class_ids = read_yolo_label(label_path, img_width, img_height)
        
        # Draw boxes
        verified_image = draw_boxes(image, boxes, class_ids)
        
        # Save verification image
        output_path = os.path.join(output_dir, f"verifiaed_{i:03d}_{img_file}")
        cv2.imwrite(output_path, verified_image)
        
        # Log results
        log_entry = {
            'image': img_file,
            'num_boxes': len(boxes),
            'class_ids': class_ids,
            'classes': [CLASSES[cid] for cid in class_ids],
            'saved_as': f"verified_{i:03d}_{img_file}"
        }
        verification_log.append(log_entry)
        
        print(f"  ✓ {img_file}: {len(boxes)} boxes detected")
    
    # Generate summary report
    print("\n" + "="*50)
    print("VERIFICATION SUMMARY")
    print("="*50)
    print(f"Split: {SPLIT}")
    print(f"Random seed used: {RANDOM_SEED}")
    print(f"Total images verified: {len(verification_log)}")
    
    total_boxes = sum([entry['num_boxes'] for entry in verification_log])
    print(f"Total boxes verified: {total_boxes}")
    
    # Class distribution in verified samples
    class_counts = {cls: 0 for cls in CLASSES}
    for entry in verification_log:
        for cls_name in entry['classes']:
            class_counts[cls_name] += 1
    
    print("\nClass distribution in verified samples:")
    for cls, count in class_counts.items():
        if count > 0:
            percentage = (count / total_boxes) * 100
            print(f"  {cls}: {count} instances ({percentage:.1f}%)")
    
    # Create a mosaic image for paper
    create_verification_mosaic(output_dir, verification_log[:9])
    
    print(f"\n✅ Verification complete!")
    print(f"Verified images saved to: {output_dir}")
    print("\nTo reproduce this exact verification, use:")
    print(f"  RANDOM_SEED = {RANDOM_SEED}")
    print(f"  NUM_SAMPLES = {NUM_SAMPLES}")

def create_verification_mosaic(output_dir, log_entries, grid_size=(3, 3)):
    """Create a 3x3 mosaic of verified images for paper inclusion"""
    if len(log_entries) == 0:
        return
    
    mosaic_paths = []
    for entry in log_entries[:9]:
        img_path = os.path.join(output_dir, entry['saved_as'])
        if os.path.exists(img_path):
            mosaic_paths.append(img_path)
    
    if len(mosaic_paths) < 4:
        return
    
    # Create figure
    fig, axes = plt.subplots(3, 3, figsize=(15, 15))
    fig.suptitle(f'Annotation Verification Samples ({SPLIT} set, seed={RANDOM_SEED})', fontsize=16)
    
    for idx, img_path in enumerate(mosaic_paths):
        if idx >= 9:
            break
        row, col = idx // 3, idx % 3
        img = cv2.cvtColor(cv2.imread(img_path), cv2.COLOR_BGR2RGB)
        axes[row, col].imshow(img)
        axes[row, col].axis('off')
        axes[row, col].set_title(os.path.basename(img_path).replace('verified_', ''), fontsize=8)
    
    plt.tight_layout()
    mosaic_path = os.path.join(output_dir, f'verification_mosaic_{SPLIT}_seed{RANDOM_SEED}.png')
    plt.savefig(mosaic_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  📊 Mosaic saved to: {mosaic_path}")

if __name__ == "__main__":
    # 🔴 SEED IS SET HERE - ENSURES REPRODUCIBILITY
    random.seed(RANDOM_SEED)
    print(f"🔐 Verification script initialized with seed: {RANDOM_SEED}")
    
    # Run verification
    verify_annotations()