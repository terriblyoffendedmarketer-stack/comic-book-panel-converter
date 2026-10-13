# xteink_split_convert.py — Split comic pages at row gutters for XTe Ink X4 landscape reading
# Usage: python scripts/xteink_split_convert.py <comic-file> --title "Title"
# Requires: Pillow, numpy
#
# Same row-splitting approach as kindle_split_convert.py but targeting XTe Ink X4:
# - Viewport: 800x480 (landscape)
# - Output: XTCH format (2-bit, 4-level grayscale) for CrossPoint reader
# - No dithering — 4-level quantization preserves text clarity
# - Contrast and sharpening tuned for e-ink
#
# Gotchas:
# - XTCH uses 4-level grayscale (levels: >=212→white, >=127→light gray, >=42→dark gray, <42→black)
#   which is much better for text than 1-bit dithered XTC
# - Row segments are naturally landscape (wider than tall), so no rotation needed
# - For EPUB sources, must render via Calibre to PDF first (composites HTML text layers)
# - Don't upscale — only downscale to preserve sharpness
# - The 10th percentile brightness per row filters out text lines from gutter detection

import sys
import os
import shutil
from pathlib import Path
from PIL import Image, ImageFilter, ImageOps
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / 'src'))

from extract import extract
from build_xtc import image_to_xth, build_xtc

# XTe Ink X4 landscape viewport
XTEINK_W = 800
XTEINK_H = 480


def find_row_gutters(img):
    """Find horizontal gutters between panel rows.
    Returns list of (y_start, y_end) for each gutter, sorted by position."""
    arr = np.array(img.convert('L'))
    h, w = arr.shape

    margin = int(w * 0.1)
    center = arr[:, margin:w - margin]

    row_brightness = np.percentile(center, 10, axis=1)
    is_gutter = row_brightness > 180

    bands = []
    in_band = False
    start = 0
    for y in range(h):
        if is_gutter[y] and not in_band:
            start = y
            in_band = True
        elif not is_gutter[y] and in_band:
            if y - start >= 8:
                bands.append((start, y))
            in_band = False

    bands = [b for b in bands if b[0] > h * 0.1 and b[1] < h * 0.9]

    merged = []
    for b in bands:
        if merged and b[0] - merged[-1][1] < 40:
            merged[-1] = (merged[-1][0], b[1])
        else:
            merged.append(b)

    return merged


def auto_crop_whitespace(img, threshold=240, min_margin=10):
    """Crop surrounding whitespace to the content bounding box."""
    arr = np.array(img.convert('L'))
    h, w = arr.shape

    dark_rows = arr.min(axis=1) < threshold
    dark_cols = arr.min(axis=0) < threshold

    if not dark_rows.any() or not dark_cols.any():
        return img

    row_indices = np.where(dark_rows)[0]
    col_indices = np.where(dark_cols)[0]

    top = max(0, row_indices[0] - min_margin)
    bottom = min(h, row_indices[-1] + min_margin)
    left = max(0, col_indices[0] - min_margin)
    right = min(w, col_indices[-1] + min_margin)

    if (right - left) < w * 0.95 or (bottom - top) < h * 0.95:
        return img.crop((left, top, right, bottom))
    return img


def classify_page(img):
    """Classify a page as: 'comic', 'text', or 'splash'."""
    arr = np.array(img.convert('L'))
    dark_fraction = (arr < 128).mean()

    if dark_fraction < 0.08:
        return 'text'
    if dark_fraction > 0.7:
        return 'splash'
    return 'comic'


def is_spread(img):
    """Detect double-page spread (width significantly > height)."""
    w, h = img.size
    return w > h * 1.3


def select_split_points(gutters, page_height, target_rows=3):
    """From candidate gutters, pick the best 1-2 that create balanced rows."""
    if not gutters:
        return []

    centers = [(g[0] + g[1]) // 2 for g in gutters]
    widths = [g[1] - g[0] for g in gutters]

    if len(centers) == 1:
        return centers

    if len(centers) == 2:
        row_sizes = [centers[0], centers[1] - centers[0], page_height - centers[1]]
        min_row = min(row_sizes)
        if min_row > page_height * 0.15:
            return centers
        best = centers[widths.index(max(widths))]
        return [best]

    best_score = float('inf')
    best_pair = None

    for i in range(len(centers)):
        for j in range(i + 1, len(centers)):
            rows = [centers[i], centers[j] - centers[i], page_height - centers[j]]
            mean_row = page_height / 3
            score = sum((r - mean_row) ** 2 for r in rows)
            score -= (widths[i] + widths[j]) * 10
            if score < best_score:
                best_score = score
                best_pair = [centers[i], centers[j]]

    best_single_idx = widths.index(max(widths))
    best_single = centers[best_single_idx]

    if best_pair:
        rows_3 = [best_pair[0], best_pair[1] - best_pair[0], page_height - best_pair[1]]
        if min(rows_3) < page_height * 0.15:
            return [best_single]
        return best_pair

    return [best_single]


def process_row_xteink(img_crop):
    """Process a cropped row for XTe Ink: grayscale, rotate to portrait, pad to 480x800, sharpen.
    CrossPoint expects exactly 480x800 portrait pages. Landscape rows get rotated 90°."""
    if img_crop.mode != 'L':
        img_crop = ImageOps.grayscale(img_crop)

    # Rotate landscape segments to portrait (CrossPoint is a portrait device)
    w, h = img_crop.size
    if w > h:
        img_crop = img_crop.transpose(Image.ROTATE_90)

    img_crop = ImageOps.autocontrast(img_crop, cutoff=1)

    # Resize to fit within 480x800, then center on white canvas
    w, h = img_crop.size
    scale = min(480 / w, 800 / h)
    if scale < 1:
        img_crop = img_crop.resize((int(w * scale), int(h * scale)), Image.LANCZOS)

    img_crop = img_crop.filter(ImageFilter.UnsharpMask(radius=1.5, percent=80, threshold=2))

    # Pad to exactly 480x800
    result = Image.new('L', (480, 800), 255)
    paste_x = (480 - img_crop.width) // 2
    paste_y = (800 - img_crop.height) // 2
    result.paste(img_crop, (paste_x, paste_y))

    return result


def split_page(img, page_idx):
    """Split a single page into XTe Ink-ready segments.
    Returns list of (PIL Image, description) tuples."""
    img = auto_crop_whitespace(img)

    w, h = img.size
    page_type = classify_page(img)
    spread = is_spread(img)

    if page_type == 'text':
        return [(process_row_xteink(img), 'text_full')]

    if page_type == 'splash':
        return [(process_row_xteink(img), 'splash_full')]

    if spread:
        segments = []
        segments.append((process_row_xteink(img), 'spread_full'))
        mid_x = w // 2
        left = img.crop((0, 0, mid_x, h))
        right = img.crop((mid_x, 0, w, h))
        segments.append((process_row_xteink(left), 'spread_left'))
        segments.append((process_row_xteink(right), 'spread_right'))
        return segments

    gutters = find_row_gutters(img)
    splits = select_split_points(gutters, h)

    if not splits:
        third = h // 3
        splits = [third, third * 2]

    segments = []
    boundaries = [0] + splits + [h]
    for i in range(len(boundaries) - 1):
        y_start = boundaries[i]
        y_end = boundaries[i + 1]

        overlap = int((y_end - y_start) * 0.02)
        crop_start = max(0, y_start - overlap)
        crop_end = min(h, y_end + overlap)

        row_crop = img.crop((0, crop_start, w, crop_end))
        processed = process_row_xteink(row_crop)
        segments.append((processed, f'row_{i}'))

    return segments


def convert_comic(comic_path, title, output_dir):
    """Convert a comic file to split XTe Ink XTCH."""
    comic_path = Path(comic_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    temp_dir = output_dir / '_temp_xteink_split'

    print(f"\n  Extracting pages from {comic_path.name}...")
    pages_dir = extract(comic_path, output_base=temp_dir)

    page_files = sorted(
        [p for p in pages_dir.iterdir()
         if p.suffix.lower() in {'.jpg', '.jpeg', '.png'}],
        key=lambda f: f.name
    )
    print(f"  {len(page_files)} pages extracted")

    xth_pages = []
    segment_count = 0
    skipped = 0
    stats = {'text': 0, 'splash': 0, 'spread': 0, 'split_2': 0, 'split_3': 0, 'split_fallback': 0}

    for i, page_file in enumerate(page_files):
        try:
            img = Image.open(page_file)
            img.load()
        except (OSError, IOError) as e:
            print(f"  Warning: skipping corrupt page {page_file.name}: {e}")
            skipped += 1
            continue

        segments = split_page(img, i)

        for seg_img, seg_type in segments:
            xth_data = image_to_xth(seg_img)
            xth_pages.append(xth_data)
            segment_count += 1

        if len(segments) == 1:
            if 'text' in segments[0][1]:
                stats['text'] += 1
            else:
                stats['splash'] += 1
        elif any('spread' in s[1] for s in segments):
            stats['spread'] += 1
        elif len(segments) == 2:
            stats['split_2'] += 1
        elif len(segments) == 3:
            stats['split_3'] += 1
        else:
            stats['split_fallback'] += 1

        if (i + 1) % 25 == 0 or i == 0:
            print(f"  Processed {i + 1}/{len(page_files)} pages → {segment_count} segments")

    print(f"  {len(page_files)} pages → {segment_count} segments")
    print(f"  Stats: {stats}")
    if skipped:
        print(f"  Skipped {skipped} corrupt pages")

    xtch_data = build_xtc(xth_pages, title=title, is_2bit=True)

    xtch_path = output_dir / f"{title}.xtch"
    with open(xtch_path, 'wb') as f:
        f.write(xtch_data)

    if temp_dir.exists():
        shutil.rmtree(temp_dir, ignore_errors=True)

    size_mb = xtch_path.stat().st_size / 1024 / 1024
    print(f"  Done: {xtch_path.name} ({size_mb:.1f} MB, {segment_count} segments from {len(page_files)} pages)")
    return xtch_path


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python scripts/xteink_split_convert.py <comic-file> --title 'Title'")
        sys.exit(1)

    comic_file = sys.argv[1]
    title = None
    if '--title' in sys.argv:
        idx = sys.argv.index('--title')
        if idx + 1 < len(sys.argv):
            title = sys.argv[idx + 1]

    if title is None:
        title = Path(comic_file).stem

    convert_comic(comic_file, title, 'output/XTeInk')
