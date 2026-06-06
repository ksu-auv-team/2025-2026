"""
emoji_data_generator.py
=======================
RoboSub Emoji Object Detection - Dataset Generator & Trainer
Handles:
  1. PDF emoji extraction
  2. Background image crawling
  3. Synthetic image generation with auto-annotations (YOLO format)
  4. Albumentations augmentation pipeline
  5. YOLOv8 training

Usage:
    python emoji_data_generator.py --pdf Robosub_Emojies.pdf --all
    python emoji_data_generator.py --pdf Robosub_Emojies.pdf --generate  # skip crawl if backgrounds exist
    python emoji_data_generator.py --train                                # skip gen if dataset exists

Requirements:
    pip install pymupdf Pillow opencv-python numpy albumentations icrawler ultralytics
"""

import argparse
import os
import random
import shutil
from pathlib import Path

import cv2
import numpy as np

# ─────────────────────────────────────────────
# CONFIGURATION  (edit these as needed)
# ─────────────────────────────────────────────
CONFIG = {
    # Paths
    "pdf_path":         "/home/user/2025-2026/Robosub_Emojies.pdf",
    "emoji_dir":        "model_training/emojis/emoji_assets",
    "bg_dir":           "model_training/emojis/backgrounds",
    "dataset_dir":      "model_training/emojis/dataset",

    # Class definitions  (order must match PDF page order)
    "class_names": [
        "compass",
        "hammers",
        "life_preserver",
        "sos",
        "fire",
        "blood_drop",
    ],

    # Per-class sampling weights — higher = more examples generated.
    # Indices match class_names above:
    #   compass=0, hammers=1, life_preserver=2, sos=3, fire=4, blood_drop=5
    # Hammers/fire/blood_drop were the weakest classes in v2, so oversample them.
    "class_weights": [1.0, 3.0, 1.0, 1.5, 2.5, 2.5],

    # Background crawl settings
    "bg_keywords": [
        # Underwater pool / ocean — original
        "underwater pool floor",
        "underwater swimming pool",
        "ocean floor underwater",
        "underwater blue water",
        "pool underwater clear",
        # Structural / non-water — added for diversity
        "underwater concrete wall",
        "swimming pool lane markers",
        "underwater pipe structure",
    ],
    "bg_per_keyword":   40,     # images crawled per keyword

    # Synthetic generation settings
    "output_size":      (640, 640),
    "images_per_bg":    12,     # was 5 — more images per background
    "max_emojis_per_img": 4,    # max emoji instances pasted per image
    "emoji_scale_min":  0.02,   # relative to output_size (~13px at 640 ≈ 3-4 m range)
    "emoji_scale_max":  0.35,
    "hard_negative_ratio": 0.10,  # fraction of images generated with NO emojis (hard negatives)

    # Train / val split
    "val_split":        0.1,    # 10% of generated images go to val

    # YOLOv8 training settings
    "yolo_model":       "yolov8s.pt",   # small; better small-object detection than nano
    "epochs":           100,    # was 50 — v2 curves showed plateau around epoch 38, more headroom
    "imgsz":            640,
    "batch":            32,
    "device":           "",     # "" = auto-detect (GPU if available, else CPU)
}

# Distance-range profiles — merged over CONFIG at generation time.
# "close" mirrors the existing defaults (1-3 m); "far" targets 6-7 m.
#
# Scale reasoning (object ~30 cm across, ZED 2i at 640 px wide):
#   1 m  → ~0.20-0.35  (128-224 px)
#   3 m  → ~0.07-0.12  ( 45- 77 px)   ← current scale_max covers this
#   6 m  → ~0.03-0.06  ( 19- 38 px)
#   7 m  → ~0.01-0.04  (  6- 26 px)
#
# At 6-7 m the water column also blurs, attenuates contrast, and adds more
# turbidity — hence the tighter fog/blur parameters in the far profile.
RANGE_PROFILES = {
    "close": {
        "range_profile":       "close",
        "emoji_scale_min":     0.02,
        "emoji_scale_max":     0.35,
        "dataset_dir":         "model_training/emojis/dataset",
        "hard_negative_ratio": 0.10,
        "max_emojis_per_img":  4,
    },
    "far": {
        "range_profile":       "far",
        # Emojis at 6-7 m: roughly 6-38 px wide in a 640-px frame
        "emoji_scale_min":     0.01,
        "emoji_scale_max":     0.06,
        "dataset_dir":         "model_training/emojis/dataset_far",
        # Harder to see at distance → more hard-negative training pressure
        "hard_negative_ratio": 0.15,
        # Smaller emojis pack more instances per frame
        "max_emojis_per_img":  8,
        # More images per background to compensate for the harder task
        "images_per_bg":       20,
    },
}


# ─────────────────────────────────────────────
# STEP 1 — EXTRACT EMOJIS FROM PDF
# ─────────────────────────────────────────────
def extract_emojis(pdf_path: str, output_dir: str) -> list:
    """Extract each PDF page as a high-res RGBA PNG."""
    try:
        import fitz  # pymupdf
    except ImportError:
        raise ImportError("Run: pip install pymupdf")

    from PIL import Image

    os.makedirs(output_dir, exist_ok=True)
    doc = fitz.open(pdf_path)
    saved = []

    for i, page in enumerate(doc):
        pix = page.get_pixmap(dpi=300, alpha=True)
        img = Image.frombytes("RGBA", [pix.width, pix.height], pix.samples)
        out = Path(output_dir) / f"emoji_{i}.png"
        img.save(str(out))
        print(f"  [extract] Saved {out}")
        saved.append(out)

    print(f"  [extract] {len(saved)} emoji PNGs extracted from '{pdf_path}'")
    return saved


# ─────────────────────────────────────────────
# STEP 2 — CRAWL BACKGROUND IMAGES
# ─────────────────────────────────────────────
def _generate_procedural_backgrounds(bg_dir: str, count: int = 20) -> None:
    """Generate simple procedural underwater-style backgrounds as a crawl fallback."""
    print(f"  [crawl] Generating {count} procedural underwater backgrounds as fallback...")
    rng = np.random.default_rng(42)
    for i in range(count):
        h, w = 640, 640
        # Base underwater gradient: dark teal/blue tones
        base_b = rng.integers(120, 200)
        base_g = rng.integers(80, 160)
        base_r = rng.integers(10, 60)
        img = np.zeros((h, w, 3), dtype=np.uint8)
        for row in range(h):
            t = row / h
            img[row, :] = [
                int(base_b * (1 - t * 0.4)),
                int(base_g * (1 - t * 0.3)),
                int(base_r * (1 - t * 0.2)),
            ]
        # Add subtle noise for texture
        noise = rng.integers(-15, 15, (h, w, 3), dtype=np.int16)
        img = np.clip(img.astype(np.int16) + noise, 0, 255).astype(np.uint8)
        cv2.imwrite(str(Path(bg_dir) / f"procedural_{i:03d}.jpg"), img)


def crawl_backgrounds(bg_dir: str, keywords: list, per_keyword: int) -> None:
    """Download background images via icrawler (Bing Images)."""
    try:
        from icrawler.builtin import BingImageCrawler
    except ImportError:
        raise ImportError("Run: pip install icrawler")

    os.makedirs(bg_dir, exist_ok=True)

    for kw in keywords:
        safe_kw = kw.replace(" ", "_")
        save_dir = str(Path(bg_dir) / safe_kw)
        print(f"  [crawl] Searching: '{kw}' -> {save_dir}")
        crawler = BingImageCrawler(
            storage={"root_dir": save_dir},
            log_level=50,  # suppress icrawler noise
        )
        crawler.crawl(keyword=kw, max_num=per_keyword)

    # Flatten all crawled images into bg_dir root for easy loading
    all_imgs = list(Path(bg_dir).rglob("*.jpg")) + list(Path(bg_dir).rglob("*.png"))
    flat_dir = Path(bg_dir)
    for img in all_imgs:
        if img.parent != flat_dir:
            dest = flat_dir / img.name
            if not dest.exists():
                shutil.move(str(img), str(dest))

    # Clean up empty subdirs
    for d in [p for p in flat_dir.iterdir() if p.is_dir()]:
        try:
            shutil.rmtree(str(d))
        except Exception:
            pass

    total = len(list(flat_dir.glob("*.jpg"))) + len(list(flat_dir.glob("*.png")))
    if total == 0:
        print("  [crawl] Warning: no images downloaded, falling back to procedural backgrounds")
        _generate_procedural_backgrounds(bg_dir)
        total = len(list(flat_dir.glob("*.jpg")))
    print(f"  [crawl] {total} background images available in '{bg_dir}'")


# ─────────────────────────────────────────────
# STEP 3 — SYNTHETIC IMAGE GENERATION
# ─────────────────────────────────────────────
def _rotate_emoji(emoji_rgba, angle):
    """Rotate an RGBA emoji by angle degrees, expanding the canvas to fit."""
    h, w = emoji_rgba.shape[:2]
    cx, cy = w / 2.0, h / 2.0
    M = cv2.getRotationMatrix2D((cx, cy), angle, 1.0)
    cos_a = abs(M[0, 0])
    sin_a = abs(M[0, 1])
    new_w = int(h * sin_a + w * cos_a)
    new_h = int(h * cos_a + w * sin_a)
    M[0, 2] += new_w / 2.0 - cx
    M[1, 2] += new_h / 2.0 - cy
    return cv2.warpAffine(
        emoji_rgba, M, (new_w, new_h),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(0, 0, 0, 0),
    )


def _iou(a, b):
    """IoU between two (x, y, w, h) pixel boxes."""
    ax2, ay2 = a[0] + a[2], a[1] + a[3]
    bx2, by2 = b[0] + b[2], b[1] + b[3]
    inter_w = max(0, min(ax2, bx2) - max(a[0], b[0]))
    inter_h = max(0, min(ay2, by2) - max(a[1], b[1]))
    inter = inter_w * inter_h
    union = a[2] * a[3] + b[2] * b[3] - inter
    return inter / union if union > 0 else 0.0


def _paste_emoji(bg, emoji_rgba, x, y, scale):
    """Alpha-blend a scaled emoji onto bg at (x, y). Returns (x, y, w, h) or None."""
    h, w = emoji_rgba.shape[:2]
    new_w = max(int(w * scale), 10)
    new_h = max(int(h * scale), 10)

    resized = cv2.resize(emoji_rgba, (new_w, new_h), interpolation=cv2.INTER_AREA)

    x2, y2 = x + new_w, y + new_h
    if x < 0 or y < 0 or x2 > bg.shape[1] or y2 > bg.shape[0]:
        return None

    alpha = resized[:, :, 3:4].astype(np.float32) / 255.0
    rgb   = resized[:, :, :3].astype(np.float32)
    roi   = bg[y:y2, x:x2].astype(np.float32)

    bg[y:y2, x:x2] = np.clip(alpha * rgb + (1.0 - alpha) * roi, 0, 255).astype(np.uint8)
    return (x, y, new_w, new_h)


def _build_augmentation_pipeline(cfg: dict | None = None):
    """Return an Albumentations augmentation pipeline.

    When cfg["range_profile"] == "far", use heavier blur, fog, noise, and
    compression to simulate the water-column degradation at 6-7 m.
    """
    try:
        import albumentations as A
    except ImportError:
        raise ImportError("Run: pip install albumentations")

    is_far = (cfg or {}).get("range_profile") == "far"

    # Gaussian blur: wider kernel + higher probability at far range
    gblur_limit = (3, 9)  if is_far else (3, 5)
    gblur_p     = 0.50    if is_far else 0.30
    # Motion blur: longer streaks at far range (AUV micro-movements matter more)
    mblur_limit = (3, 11) if is_far else (3, 7)
    mblur_p     = 0.35    if is_far else 0.20
    # Gaussian noise: stronger sensor noise at low contrast
    noise_var   = (20, 80) if is_far else (10, 50)
    noise_p     = 0.40     if is_far else 0.30
    # Fog / turbidity: heavier and more frequent at distance
    fog_coef    = (0.2, 0.5) if is_far else (0.1, 0.3)
    fog_p       = 0.45       if is_far else 0.25
    # JPEG compression: more block artifacts simulate long-range stream quality
    comp_qual   = (55, 85) if is_far else (70, 95)

    return A.Compose([
        A.RandomBrightnessContrast(brightness_limit=0.3, contrast_limit=0.3, p=0.6),
        A.GaussianBlur(blur_limit=gblur_limit, p=gblur_p),
        A.MotionBlur(blur_limit=mblur_limit, p=mblur_p),
        A.GaussNoise(var_limit=noise_var, p=noise_p),
        A.HueSaturationValue(hue_shift_limit=15, sat_shift_limit=30, val_shift_limit=20, p=0.5),
        A.RandomFog(fog_coef_range=fog_coef, alpha_coef=0.1, p=fog_p),
        A.RandomShadow(num_shadows_limit=(1, 2), p=0.2),
        A.ImageCompression(quality_range=comp_qual, p=0.3),
        A.Rotate(limit=15, p=0.4),
    ])


def generate_dataset(emoji_dir, bg_dir, dataset_dir, class_names, cfg):
    """Generate synthetic images with YOLO-format labels."""
    output_size       = cfg["output_size"]
    imgs_per_bg       = cfg["images_per_bg"]
    max_per_img       = cfg["max_emojis_per_img"]
    scale_min         = cfg["emoji_scale_min"]
    scale_max         = cfg["emoji_scale_max"]
    val_split         = cfg["val_split"]
    hard_neg_ratio    = cfg.get("hard_negative_ratio", 0.0)
    num_classes       = len(class_names)

    # Build weighted class sampling distribution
    raw_weights  = cfg.get("class_weights", [1.0] * num_classes)
    raw_weights  = raw_weights[:num_classes]  # trim to actual class count
    weight_total = sum(raw_weights)
    class_probs  = [w / weight_total for w in raw_weights]

    # Output dirs
    for split in ("train", "val"):
        os.makedirs(Path(dataset_dir) / "images" / split, exist_ok=True)
        os.makedirs(Path(dataset_dir) / "labels" / split, exist_ok=True)

    # Load emoji assets
    emoji_paths = sorted(Path(emoji_dir).glob("*.png"))
    if not emoji_paths:
        raise FileNotFoundError(f"No PNGs found in '{emoji_dir}'. Run extraction first.")
    emojis = [cv2.imread(str(p), cv2.IMREAD_UNCHANGED) for p in emoji_paths]
    emojis = emojis[:num_classes]  # trim to class count
    print(f"  [generate] Loaded {len(emojis)} emoji assets")

    # Load backgrounds
    bg_paths = (
        list(Path(bg_dir).glob("*.jpg"))
        + list(Path(bg_dir).glob("*.jpeg"))
        + list(Path(bg_dir).glob("*.png"))
    )
    if not bg_paths:
        print(f"  [generate] No backgrounds in '{bg_dir}', generating procedural ones...")
        _generate_procedural_backgrounds(bg_dir)
        bg_paths = (
            list(Path(bg_dir).glob("*.jpg"))
            + list(Path(bg_dir).glob("*.jpeg"))
            + list(Path(bg_dir).glob("*.png"))
        )
    print(f"  [generate] Found {len(bg_paths)} background images")

    augment   = _build_augmentation_pipeline(cfg)
    img_count = 0

    for bg_path in bg_paths:
        bg_orig = cv2.imread(str(bg_path))
        if bg_orig is None:
            continue
        bg_orig = cv2.resize(bg_orig, output_size)

        for _ in range(imgs_per_bg):
            bg          = bg_orig.copy()
            yolo_labels = []
            placed_boxes = []  # pixel (x, y, w, h) of already-placed emojis

            # Hard negatives: some images intentionally have no emojis
            is_hard_negative = random.random() < hard_neg_ratio
            num_emojis = 0 if is_hard_negative else random.randint(1, max_per_img)

            for _ in range(num_emojis):
                class_id = random.choices(range(len(emojis)), weights=class_probs)[0]
                emoji    = emojis[class_id]
                if emoji is None:
                    continue

                # Rotate the emoji before pasting (full 360° for orientation robustness)
                angle         = random.uniform(0, 360)
                emoji_rotated = _rotate_emoji(emoji, angle)

                scale = random.uniform(scale_min, scale_max)
                max_x = output_size[0] - int(emoji_rotated.shape[1] * scale)
                max_y = output_size[1] - int(emoji_rotated.shape[0] * scale)
                if max_x <= 0 or max_y <= 0:
                    continue

                x    = random.randint(0, max_x)
                y    = random.randint(0, max_y)
                bbox = _paste_emoji(bg, emoji_rotated, x, y, scale)
                if bbox is None:
                    continue

                # Skip this annotation if it heavily overlaps an existing one
                if any(_iou(bbox, prev) > 0.4 for prev in placed_boxes):
                    continue
                placed_boxes.append(bbox)

                bx, by, bw, bh = bbox
                cx = (bx + bw / 2) / output_size[0]
                cy = (by + bh / 2) / output_size[1]
                nw = bw / output_size[0]
                nh = bh / output_size[1]
                yolo_labels.append(
                    f"{class_id} {cx:.6f} {cy:.6f} {nw:.6f} {nh:.6f}"
                )

            # Apply augmentations to the final composite
            augmented = augment(image=bg)
            bg = augmented["image"]

            # Train / val split
            split    = "val" if random.random() < val_split else "train"
            img_file = Path(dataset_dir) / "images" / split / f"{img_count:06d}.jpg"
            lbl_file = Path(dataset_dir) / "labels" / split / f"{img_count:06d}.txt"

            cv2.imwrite(str(img_file), bg)
            with open(lbl_file, "w") as f:
                f.write("\n".join(yolo_labels))

            img_count += 1

    print(f"  [generate] {img_count} synthetic images written to '{dataset_dir}'")


# ─────────────────────────────────────────────
# STEP 4 — WRITE YOLO DATASET CONFIG
# ─────────────────────────────────────────────
def write_dataset_yaml(dataset_dir, class_names):
    """Write dataset.yaml for YOLOv8 training."""
    yaml_path = Path(dataset_dir) / "dataset.yaml"
    names_str = "\n".join(f"  {i}: {n}" for i, n in enumerate(class_names))
    content = f"""# Auto-generated by emoji_data_generator.py
path: {Path(dataset_dir).resolve()}
train: images/train
val: images/val

nc: {len(class_names)}
names:
{names_str}
"""
    with open(yaml_path, "w") as f:
        f.write(content)
    print(f"  [config] dataset.yaml written -> {yaml_path}")
    return str(yaml_path)


# ─────────────────────────────────────────────
# STEP 5 — TRAIN WITH YOLOV8
# ─────────────────────────────────────────────
def train_model(yaml_path, cfg, base_model: str | None = None):
    """Kick off YOLOv8 training.

    base_model: path to a previous best.pt to fine-tune from, or None to use cfg["yolo_model"].
    """
    try:
        from ultralytics import YOLO
    except ImportError:
        raise ImportError("Run: pip install ultralytics")

    checkpoint = base_model or cfg["yolo_model"]
    print(f"\n  [train] Starting YOLOv8 training on '{yaml_path}' (base: {checkpoint})")
    model = YOLO(checkpoint)
    model.train(
        data=yaml_path,
        epochs=cfg["epochs"],
        imgsz=cfg["imgsz"],
        batch=cfg["batch"],
        device=cfg["device"] if cfg["device"] else None,
        project="runs/robosub_emoji",
        name="train",
        exist_ok=True,
        multi_scale=True,
    )
    print("\n  [train] Training complete. Results saved to runs/robosub_emoji/train/")


# ─────────────────────────────────────────────
# CLI ENTRYPOINT
# ─────────────────────────────────────────────
def parse_args():
    parser = argparse.ArgumentParser(
        description="RoboSub Emoji Dataset Generator & YOLOv8 Trainer"
    )
    parser.add_argument("--pdf",        default=CONFIG["pdf_path"],  help="Path to emoji PDF")
    parser.add_argument("--crawl",      action="store_true",         help="Crawl background images")
    parser.add_argument("--generate",   action="store_true",         help="Generate synthetic dataset")
    parser.add_argument("--train",      action="store_true",         help="Train YOLOv8 model")
    parser.add_argument("--all",        action="store_true",         help="Run all steps end-to-end")
    parser.add_argument(
        "--base-model",
        default=None,
        metavar="PATH",
        help="Path to a previous best.pt to fine-tune from (default: use yolo_model in CONFIG)",
    )
    parser.add_argument(
        "--range",
        choices=["close", "far", "all"],
        default="close",
        help=(
            "Distance profile for dataset generation: "
            "'close' = 1-3 m (current behaviour, scale 0.02-0.35), "
            "'far' = 6-7 m (small emojis + heavy water effects, scale 0.01-0.06), "
            "'all' = generate both datasets back-to-back."
        ),
    )
    return parser.parse_args()


def main():
    args = parse_args()

    do_extract  = args.all or args.generate  # extraction is a prerequisite for generate
    do_crawl    = args.all or args.crawl
    do_generate = args.all or args.generate
    do_train    = args.all or args.train

    print("=" * 55)
    print("  RoboSub Emoji Dataset Generator")
    print("=" * 55)

    yaml_path = str(Path(CONFIG["dataset_dir"]) / "dataset.yaml")  # default path

    if do_extract:
        print("\n[STEP 1] Extracting emojis from PDF...")
        extract_emojis(args.pdf, CONFIG["emoji_dir"])

    if do_crawl:
        print("\n[STEP 2] Crawling background images...")
        crawl_backgrounds(
            CONFIG["bg_dir"],
            CONFIG["bg_keywords"],
            CONFIG["bg_per_keyword"],
        )

    if do_generate:
        ranges = list(RANGE_PROFILES.keys()) if args.range == "all" else [args.range]
        for r in ranges:
            merged_cfg = {**CONFIG, **RANGE_PROFILES[r]}
            print(f"\n[STEP 3] Generating synthetic dataset (range: {r})...")
            generate_dataset(
                CONFIG["emoji_dir"],
                CONFIG["bg_dir"],
                merged_cfg["dataset_dir"],
                CONFIG["class_names"],
                merged_cfg,
            )
            print(f"\n[STEP 4] Writing dataset.yaml for range '{r}'...")
            yaml_path = write_dataset_yaml(merged_cfg["dataset_dir"], CONFIG["class_names"])

    if do_train:
        print("\n[STEP 5] Training YOLOv8...")
        train_model(yaml_path, CONFIG, base_model=args.base_model)

    if not any([do_extract, do_crawl, do_generate, do_train]):
        print("Nothing to do. Pass --crawl, --generate, --train, or --all.")
        print("Example: python emoji_data_generator.py --pdf Robosub_Emojies.pdf --all")

    print("\nDone.")


if __name__ == "__main__":
    main()
