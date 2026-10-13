# kindle_split_convert.py — Split comic pages at row gutters for readable Kindle viewing
# Usage: python scripts/kindle_split_convert.py <comic-file> --title "Title"
# Requires: Pillow, numpy, ebooklib
#
# Splits each page into 2-3 rows at detected horizontal gutters, then resizes
# each row to fill the Kindle Paperwhite landscape viewport (1448x1072).
# Falls back to even thirds when no clear gutters are detected.
#
# Gotchas:
# - Text-only pages (ToC, copyright) should NOT be split — detect by content density
# - Double-page spreads (landscape) get a full view + split if text-heavy
# - Always crop from the original high-res source — never upscale
# - The 10th percentile brightness per row filters out text lines from gutter detection
# - Merge candidate gutters within 40px to avoid splitting on thin panel borders

import sys
import os
import shutil
from pathlib import Path
from PIL import Image, ImageFilter, ImageOps
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / 'src'))

from extract import extract
from build_epub import build_epub

# Kindle Paperwhite landscape viewport
KINDLE_W = 1448
KINDLE_H = 1072


def find_row_gutters(img):
    """Find horizontal gutters between panel rows.
    Returns list of (y_start, y_end) for each gutter, sorted by position."""
    arr = np.array(img.convert('L'))
    h, w = arr.shape

    # Check center 80% of page width — gutters span the full page
    margin = int(w * 0.1)
    center = arr[:, margin:w - margin]

    # 10th percentile brightness per row: filters out text lines
    # (text has dark pixels that pull down the percentile)
    row_brightness = np.percentile(center, 10, axis=1)

    # A gutter row: nearly all pixels bright
    is_gutter = row_brightness > 180

    # Find contiguous gutter bands
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

    # Skip top/bottom margins (outer 10%)
    bands = [b for b in bands if b[0] > h * 0.1 and b[1] < h * 0.9]

    # Merge bands within 40px of each other
    merged = []
    for b in bands:
        if merged and b[0] - merged[-1][1] < 40:
            merged[-1] = (merged[-1][0], b[1])
        else:
            merged.append(b)

    return merged


def auto_crop_whitespace(img, threshold=240, min_margin=10):
    """Crop surrounding whitespace to the content bounding box.
    Keeps a small margin around content."""
    arr = np.array(img.convert('L'))
    h, w = arr.shape

    # Find rows and columns that have dark content
    dark_rows = arr.min(axis=1) < threshold
    dark_cols = arr.min(axis=0) < threshold

    if not dark_rows.any() or not dark_cols.any():
        return img  # all white, return as-is

    row_indices = np.where(dark_rows)[0]
    col_indices = np.where(dark_cols)[0]

    top = max(0, row_indices[0] - min_margin)
    bottom = min(h, row_indices[-1] + min_margin)
    left = max(0, col_indices[0] - min_margin)
    right = min(w, col_indices[-1] + min_margin)

    # Only crop if we're removing at least 5% of the page
    if (right - left) < w * 0.95 or (bottom - top) < h * 0.95:
        return img.crop((left, top, right, bottom))
    return img


def classify_page(img):
    """Classify a page as: 'comic' (has panels), 'text' (mostly text/whitespace),
    or 'splash' (full-bleed art, no gutters)."""
    arr = np.array(img.convert('L'))
    h, w = arr.shape

    # Content density: what fraction of pixels are dark (<128)?
    dark_fraction = (arr < 128).mean()

    # If very low ink coverage, it's a text/blank page
    if dark_fraction < 0.08:
        return 'text'

    # If extremely high ink coverage, it's full-bleed art
    if dark_fraction > 0.7:
        return 'splash'

    return 'comic'


def is_spread(img):
    """Detect double-page spread (width significantly > height)."""
    w, h = img.size
    return w > h * 1.3


def select_split_points(gutters, page_height, target_rows=3):
    """From candidate gutters, pick the best 1-2 that create balanced rows.
    Returns list of y-coordinates to split at."""
    if not gutters:
        return []

    # Center point of each gutter
    centers = [(g[0] + g[1]) // 2 for g in gutters]
    widths = [g[1] - g[0] for g in gutters]

    if len(centers) == 1:
        return centers

    if len(centers) == 2:
        # Check if they create a reasonable 3-way split
        row_sizes = [centers[0], centers[1] - centers[0], page_height - centers[1]]
        min_row = min(row_sizes)
        max_row = max(row_sizes)
        if min_row > page_height * 0.15:  # each row is at least 15% of page
            return centers
        # Otherwise just use the wider gutter for a 2-way split
        best = centers[widths.index(max(widths))]
        return [best]

    # More than 2 candidates: find the best pair for a 3-way split
    best_score = float('inf')
    best_pair = None

    for i in range(len(centers)):
        for j in range(i + 1, len(centers)):
            rows = [centers[i], centers[j] - centers[i], page_height - centers[j]]
            # Score: how uneven are the rows? Lower is better.
            mean_row = page_height / 3
            score = sum((r - mean_row) ** 2 for r in rows)
            # Bonus for wider gutters (more confident)
            score -= (widths[i] + widths[j]) * 10
            if score < best_score:
                best_score = score
                best_pair = [centers[i], centers[j]]

    # Also consider single best gutter for 2-way split
    best_single_idx = widths.index(max(widths))
    best_single = centers[best_single_idx]
    rows_2 = [best_single, page_height - best_single]
    mean_2 = page_height / 2
    score_2 = sum((r - mean_2) ** 2 for r in rows_2) - widths[best_single_idx] * 10

    # Check if the 3-way split rows are all reasonable (>15% of page)
    if best_pair:
        rows_3 = [best_pair[0], best_pair[1] - best_pair[0], page_height - best_pair[1]]
        if min(rows_3) < page_height * 0.15:
            return [best_single]
        return best_pair

    return [best_single]


def process_row(img_crop, target_w=KINDLE_W, target_h=KINDLE_H):
    """Process a cropped row for Kindle: grayscale, fit to landscape viewport, sharpen."""
    if img_crop.mode != 'L':
        img_crop = ImageOps.grayscale(img_crop)

    w, h = img_crop.size
    ratio = min(target_w / w, target_h / h)

    # Only downscale, never upscale (preserve sharpness)
    if ratio < 1:
        new_w = int(w * ratio)
        new_h = int(h * ratio)
        img_crop = img_crop.resize((new_w, new_h), Image.LANCZOS)

    img_crop = ImageOps.autocontrast(img_crop, cutoff=0.5)
    img_crop = img_crop.filter(ImageFilter.UnsharpMask(radius=1.0, percent=50, threshold=2))

    return img_crop


def split_page(img, page_idx):
    """Split a single page into Kindle-ready segments.
    Returns list of (PIL Image, description) tuples."""
    # Auto-crop whitespace margins (especially from Calibre PDF rendering)
    img = auto_crop_whitespace(img)

    w, h = img.size
    page_type = classify_page(img)
    spread = is_spread(img)

    # Text/blank pages: keep as single view
    if page_type == 'text':
        return [(process_row(img, KINDLE_W, KINDLE_H), 'text_full')]

    # Splash pages: single view
    if page_type == 'splash':
        return [(process_row(img, KINDLE_W, KINDLE_H), 'splash_full')]

    # Spreads
    if spread:
        segments = []
        # Always include a full view first
        segments.append((process_row(img, KINDLE_W, KINDLE_H), 'spread_full'))
        # Split left/right for readable portions
        mid_x = w // 2
        left = img.crop((0, 0, mid_x, h))
        right = img.crop((mid_x, 0, w, h))
        segments.append((process_row(left), 'spread_left'))
        segments.append((process_row(right), 'spread_right'))
        return segments

    # Comic page: detect gutters and split into rows
    gutters = find_row_gutters(img)
    splits = select_split_points(gutters, h)

    if not splits:
        # No clear gutters — fall back to even thirds
        third = h // 3
        splits = [third, third * 2]

    # Create row segments
    segments = []
    boundaries = [0] + splits + [h]
    for i in range(len(boundaries) - 1):
        y_start = boundaries[i]
        y_end = boundaries[i + 1]

        # Slight overlap (2% of row height) to avoid cutting right at panel edge
        overlap = int((y_end - y_start) * 0.02)
        crop_start = max(0, y_start - overlap)
        crop_end = min(h, y_end + overlap)

        row_crop = img.crop((0, crop_start, w, crop_end))
        processed = process_row(row_crop)
        segments.append((processed, f'row_{i}'))

    return segments


def convert_comic(comic_path, title, output_dir):
    """Convert a comic file to split Kindle EPUB."""
    comic_path = Path(comic_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    temp_dir = output_dir / '_temp_kindle_split'

    print(f"\n  Extracting pages from {comic_path.name}...")
    pages_dir = extract(comic_path, output_base=temp_dir)

    page_files = sorted(
        [p for p in pages_dir.iterdir()
         if p.suffix.lower() in {'.jpg', '.jpeg', '.png'}],
        key=lambda f: f.name
    )
    print(f"  {len(page_files)} pages extracted")

    processed_dir = temp_dir / f"{title}_processed"
    processed_dir.mkdir(parents=True, exist_ok=True)

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
            out_path = processed_dir / f"page_{segment_count:04d}.jpg"
            seg_img.save(str(out_path), "JPEG", quality=92)
            segment_count += 1

        # Track stats
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

    # Build EPUB with landscape viewport
    epub_path = output_dir / f"{title}.epub"
    print(f"  Building EPUB...")

    import build_epub as _bmod
    old_thresh = _bmod.LANDSCAPE_THRESHOLD
    _bmod.LANDSCAPE_THRESHOLD = 999  # disable rotation — our segments are already landscape-ready
    build_epub(
        str(processed_dir),
        title=title,
        output_path=str(epub_path),
        max_width=KINDLE_W,
        max_height=KINDLE_H,
    )
    _bmod.LANDSCAPE_THRESHOLD = old_thresh

    if temp_dir.exists():
        shutil.rmtree(temp_dir, ignore_errors=True)

    size_mb = epub_path.stat().st_size / 1024 / 1024
    print(f"  Done: {epub_path.name} ({size_mb:.1f} MB, {segment_count} segments from {len(page_files)} pages)")
    return epub_path


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python scripts/kindle_split_convert.py <comic-file> --title 'Title'")
        sys.exit(1)

    comic_file = sys.argv[1]
    title = None
    if '--title' in sys.argv:
        idx = sys.argv.index('--title')
        if idx + 1 < len(sys.argv):
            title = sys.argv[idx + 1]

    if title is None:
        title = Path(comic_file).stem

    convert_comic(comic_file, title, 'output/Kindle')
