# xtc_pipeline.py — Image processing pipeline for XTe Ink, ported from xtcjs
# Faithful Python port of xtcjs converter.ts + image.ts + dithering.ts + canvas.ts
# with panel-aware gutter snapping as default splitting behavior.
#
# Usage: called by web_app.py conversion pipeline
# Requires: Pillow, numpy
#
# Gotchas:
# - Dithering uses numpy float32 buffers (not Pillow's convert('1')) so we get
#   error clamping, serpentine scanning, and algorithm choice. ~10x slower than
#   Pillow native but quality is dramatically better on manga.
# - Content trimming (findContentBounds) crops whitespace margins before processing.
#   4% padding is kept so art doesn't touch the edge.
# - Contrast is histogram-based (xtcjs applyContrast), not Pillow autocontrast.
#   blackCutoff = 3*level percent, whiteCutoff = 3+9*level percent.
# - Gutter snapping adjusts overlap segment boundaries to panel gutters when detected.

import math
import numpy as np
from PIL import Image, ImageFilter

TARGET_WIDTH = 480
TARGET_HEIGHT = 800

ERROR_CLAMP = 96


def to_grayscale(pixels):
    """Convert RGB image to grayscale using luminosity method. Returns numpy L array."""
    if isinstance(pixels, Image.Image):
        if pixels.mode == 'L':
            return np.array(pixels, dtype=np.float32)
        rgb = np.array(pixels.convert('RGB'), dtype=np.float32)
    else:
        rgb = pixels.astype(np.float32)

    if rgb.ndim == 2:
        return rgb
    return 0.299 * rgb[:, :, 0] + 0.587 * rgb[:, :, 1] + 0.114 * rgb[:, :, 2]


def apply_contrast(gray, level=1):
    """Histogram-based contrast stretch matching xtcjs applyContrast.
    level=1 gives blackCutoff=3%, whiteCutoff=12%."""
    black_cutoff = 3 * level
    white_cutoff = 3 + 9 * level

    pixels_u8 = np.clip(gray, 0, 255).astype(np.uint8)
    histogram = np.bincount(pixels_u8.ravel(), minlength=256)
    total_pixels = gray.shape[0] * gray.shape[1]

    black_threshold = total_pixels * black_cutoff / 100
    white_threshold = total_pixels * white_cutoff / 100

    black_point = 0
    count = 0
    for i in range(256):
        count += histogram[i]
        if count >= black_threshold:
            black_point = i
            break

    white_point = 255
    count = 0
    for i in range(255, -1, -1):
        count += histogram[i]
        if count >= white_threshold:
            white_point = i
            break

    rng = white_point - black_point
    if rng <= 0:
        return gray

    result = (gray - black_point) / rng * 255
    return np.clip(result, 0, 255)


def find_content_bounds(gray, white_threshold=245):
    """Find tight bounds around non-white content. Returns (x, y, w, h) or None."""
    mask = gray < white_threshold
    rows = np.any(mask, axis=1)
    cols = np.any(mask, axis=0)

    if not np.any(rows):
        return None

    min_y = np.argmax(rows)
    max_y = len(rows) - 1 - np.argmax(rows[::-1])
    min_x = np.argmax(cols)
    max_x = len(cols) - 1 - np.argmax(cols[::-1])

    content_w = max_x - min_x + 1
    content_h = max_y - min_y + 1
    pad_x = max(4, int(content_w * 0.04))
    pad_y = max(4, int(content_h * 0.04))

    x = max(0, min_x - pad_x)
    y = max(0, min_y - pad_y)
    right = min(gray.shape[1], max_x + pad_x + 1)
    bottom = min(gray.shape[0], max_y + pad_y + 1)

    return (x, y, max(1, right - x), max(1, bottom - y))


def calculate_overlap_segments(width, height):
    """Calculate overlapping segments matching xtcjs exactly."""
    scale = 800 / width
    segment_height = math.floor(480 / scale)

    num_segments = 3
    shift = 0

    if num_segments > 1:
        shift = math.floor(segment_height - (segment_height * num_segments - height) / (num_segments - 1))

    while shift / segment_height > 0.95 and num_segments < 10:
        num_segments += 1
        shift = math.floor(segment_height - (segment_height * num_segments - height) / (num_segments - 1))

    segments = []
    for i in range(num_segments):
        y = shift * i
        h = height - y if i == num_segments - 1 else segment_height
        segments.append((0, y, width, h))

    return segments


def find_panel_rows(panels):
    """Group panels into horizontal rows based on vertical overlap (>40%)."""
    if not panels:
        return []

    rows = []
    used = set()
    sorted_panels = sorted(enumerate(panels), key=lambda p: p[1][1])

    for idx, panel in sorted_panels:
        if idx in used:
            continue
        row = [panel]
        used.add(idx)
        for idx2, panel2 in sorted_panels:
            if idx2 in used:
                continue
            overlap_start = max(panel[1], panel2[1])
            overlap_end = min(panel[1] + panel[3], panel2[1] + panel2[3])
            overlap = max(0, overlap_end - overlap_start)
            min_h = min(panel[3], panel2[3])
            if min_h > 0 and overlap / min_h > 0.4:
                row.append(panel2)
                used.add(idx2)
        rows.append(row)

    return rows


def find_gutter_centers(rows):
    """Find y-coordinates of gutters between panel rows."""
    if len(rows) <= 1:
        return []

    sorted_rows = sorted(rows, key=lambda r: min(p[1] for p in r))
    gutters = []
    for i in range(len(sorted_rows) - 1):
        row_bottom = max(p[1] + p[3] for p in sorted_rows[i])
        next_top = min(p[1] for p in sorted_rows[i + 1])
        gutters.append((row_bottom + next_top) // 2)

    return gutters


def snap_segments_to_gutters(segments, gutters, page_height):
    """Snap segment boundaries to nearest panel gutters (within 15% of segment height)."""
    if not gutters or len(segments) <= 1:
        return segments

    width = segments[0][2]
    segment_height = segments[0][3]
    threshold = segment_height * 0.15
    num = len(segments)

    starts = [s[1] for s in segments]

    used_gutters = set()
    for i in range(1, num):
        best_dist = threshold + 1
        best_gi = -1
        best_g = starts[i]
        for gi, g in enumerate(gutters):
            if gi in used_gutters:
                continue
            dist = abs(g - starts[i])
            if dist < best_dist:
                best_dist = dist
                best_gi = gi
                best_g = g
        if best_dist <= threshold and best_gi >= 0:
            used_gutters.add(best_gi)
            starts[i] = best_g

    result = []
    for i in range(num):
        y = starts[i]
        h = page_height - y if i == num - 1 else segment_height
        result.append((0, y, width, h))

    if result[-1][1] + result[-1][3] < page_height:
        last = result[-1]
        result[-1] = (0, last[1], width, page_height - last[1])

    return result


def get_segments(width, height, panels=None):
    """Get overlap segments with gutter snapping applied when panels are available.
    Landscape pages (w > h) return a single full-page segment (no split)."""
    if width > height:
        return [(0, 0, width, height)]

    segments = calculate_overlap_segments(width, height)
    if len(segments) <= 1:
        return segments

    if panels:
        rows = find_panel_rows(panels)
        gutters = find_gutter_centers(rows)
        if gutters:
            segments = snap_segments_to_gutters(segments, gutters, height)

    return segments


def calculate_continuous_segments(page_widths_heights):
    """Calculate overlapping segments across all pages as one continuous strip.
    Landscape pages are inserted as standalone full-page views."""
    if not page_widths_heights:
        return []

    results = []
    portrait_run = []

    def flush_portrait_run():
        if not portrait_run:
            return
        width = portrait_run[0][1]
        run_heights = [h for _, _, h in portrait_run]
        total_height = sum(run_heights)

        cumulative = [0]
        for h in run_heights:
            cumulative.append(cumulative[-1] + h)

        scale = 800 / width
        segment_height = math.floor(480 / scale)

        num_segments = 3
        if num_segments > 1:
            shift = math.floor(segment_height - (segment_height * num_segments - total_height) / (num_segments - 1))
        else:
            shift = 0

        while shift / segment_height > 0.95 and num_segments < len(run_heights) * 5:
            num_segments += 1
            shift = math.floor(segment_height - (segment_height * num_segments - total_height) / (num_segments - 1))

        for i in range(num_segments):
            y = shift * i
            h = total_height - y if i == num_segments - 1 else segment_height

            run_idx = 0
            for ri in range(len(run_heights)):
                if cumulative[ri + 1] > y:
                    run_idx = ri
                    break

            real_page_idx = portrait_run[run_idx][0]
            y_in_page = y - cumulative[run_idx]
            remaining_in_page = run_heights[run_idx] - y_in_page

            if remaining_in_page >= h:
                results.append((real_page_idx, y_in_page, h))
            else:
                next_run_idx = run_idx + 1
                if next_run_idx < len(portrait_run):
                    next_page_idx = portrait_run[next_run_idx][0]
                    results.append((real_page_idx, y_in_page, remaining_in_page, next_page_idx, h - remaining_in_page))
                else:
                    results.append((real_page_idx, y_in_page, remaining_in_page))

    for page_idx, (w, h) in enumerate(page_widths_heights):
        if w > h:
            flush_portrait_run()
            portrait_run = []
            results.append(('landscape', page_idx))
        else:
            portrait_run.append((page_idx, w, h))

    flush_portrait_run()
    return results


# --- Dithering (ported from xtcjs dithering.ts) ---

def _clamp_error(error):
    if error > ERROR_CLAMP:
        return ERROR_CLAMP
    if error < -ERROR_CLAMP:
        return -ERROR_CLAMP
    return error


def _sharpen_luminance(pixels, width, height, amount=0.7):
    """Unsharp mask on luminance buffer (3x3 gaussian). Ported from xtcjs."""
    if amount <= 0 or width < 3 or height < 3:
        return pixels

    # 3x3 gaussian blur [1 2 1; 2 4 2; 1 2 1] / 16 using numpy padding
    padded = np.pad(pixels, 1, mode='edge')
    blurred = (
        padded[:-2, :-2] + 2 * padded[:-2, 1:-1] + padded[:-2, 2:] +
        2 * padded[1:-1, :-2] + 4 * padded[1:-1, 1:-1] + 2 * padded[1:-1, 2:] +
        padded[2:, :-2] + 2 * padded[2:, 1:-1] + padded[2:, 2:]
    ) / 16.0

    result = pixels + amount * (pixels - blurred)
    return np.clip(result, 0, 255)


def _apply_floyd_steinberg(pixels, width, height):
    """Floyd-Steinberg with serpentine scanning and error clamping."""
    for y in range(height):
        reverse = (y & 1) == 1
        rng = range(width - 1, -1, -1) if reverse else range(width)
        d = -1 if reverse else 1

        for x in rng:
            old = pixels[y, x]
            new = 255.0 if old >= 128 else 0.0
            pixels[y, x] = new
            error = _clamp_error(old - new)

            xa = x + d
            xb = x - d

            if 0 <= xa < width:
                pixels[y, xa] += error * 7 / 16
            if y + 1 < height:
                if 0 <= xb < width:
                    pixels[y + 1, xb] += error * 3 / 16
                pixels[y + 1, x] += error * 5 / 16
                if 0 <= xa < width:
                    pixels[y + 1, xa] += error * 1 / 16

    return pixels


def _apply_sierra_lite(pixels, width, height):
    """Sierra Lite with serpentine scanning and error clamping."""
    for y in range(height):
        reverse = (y & 1) == 1
        rng = range(width - 1, -1, -1) if reverse else range(width)
        d = -1 if reverse else 1

        for x in rng:
            old = pixels[y, x]
            new = 255.0 if old >= 128 else 0.0
            pixels[y, x] = new
            error = _clamp_error(old - new)

            xa = x + d
            xb = x - d

            if 0 <= xa < width:
                pixels[y, xa] += error * 2 / 4
            if y + 1 < height:
                if 0 <= xb < width:
                    pixels[y + 1, xb] += error * 1 / 4
                pixels[y + 1, x] += error * 1 / 4

    return pixels


def _apply_atkinson(pixels, width, height):
    """Atkinson dithering — distributes only 75% of error."""
    for y in range(height):
        reverse = (y & 1) == 1
        rng = range(width - 1, -1, -1) if reverse else range(width)
        d = -1 if reverse else 1

        for x in rng:
            old = pixels[y, x]
            new = 255.0 if old >= 128 else 0.0
            pixels[y, x] = new
            error = _clamp_error(old - new) / 8

            xa1 = x + d
            xa2 = x + d * 2
            xb = x - d

            if 0 <= xa1 < width:
                pixels[y, xa1] += error
            if 0 <= xa2 < width:
                pixels[y, xa2] += error
            if y + 1 < height:
                if 0 <= xb < width:
                    pixels[y + 1, xb] += error
                pixels[y + 1, x] += error
                if 0 <= xa1 < width:
                    pixels[y + 1, xa1] += error
            if y + 2 < height:
                pixels[y + 2, x] += error

    return pixels


def dither(gray, algorithm='floyd'):
    """Apply dithering to a float32 grayscale array. Returns uint8 1-bit result.

    Uses Pillow's C-speed Floyd-Steinberg by default (fast path).
    Custom Python algorithms (sierra-lite, atkinson) available but ~60x slower.
    The sharpen + error clamping are applied before Pillow's dither via
    pre-processing the image to clamp extreme values.
    """
    height, width = gray.shape
    pixels = gray.copy()

    # Sharpen before dithering (xtcjs pipeline order)
    pixels = _sharpen_luminance(pixels, width, height, amount=0.7)

    if algorithm == 'none':
        return (np.where(pixels >= 128, 255, 0)).astype(np.uint8)

    if algorithm in ('sierra-lite', 'atkinson'):
        if algorithm == 'sierra-lite':
            pixels = _apply_sierra_lite(pixels, width, height)
        else:
            pixels = _apply_atkinson(pixels, width, height)
        return np.clip(pixels, 0, 255).astype(np.uint8)

    # Fast path: Pillow's C Floyd-Steinberg with our preprocessing applied
    img = Image.fromarray(np.clip(pixels, 0, 255).astype(np.uint8), mode='L')
    dithered = img.convert('1').convert('L')
    return np.array(dithered, dtype=np.uint8)


# --- High-level processing ---

def resize_with_padding(img, target_w=TARGET_WIDTH, target_h=TARGET_HEIGHT, pad_color=255):
    """Resize image to fit within target dimensions, centered with padding."""
    scale = min(target_w / img.width, target_h / img.height)
    new_w = int(img.width * scale)
    new_h = int(img.height * scale)

    resized = img.resize((new_w, new_h), Image.LANCZOS)
    result = Image.new('L', (target_w, target_h), pad_color)
    x = (target_w - new_w) // 2
    y = (target_h - new_h) // 2
    result.paste(resized, (x, y))
    return result


def process_page(img, rotate_cw=False, contrast_level=1, trim_content=True,
                 dither_algo='floyd', target_w=TARGET_WIDTH, target_h=TARGET_HEIGHT):
    """Full xtcjs processing pipeline for a single segment/page.

    Pipeline: grayscale → content trim → contrast → rotate → resize → dither.

    Returns a PIL Image ready for XTG encoding.
    """
    gray = to_grayscale(img)

    if trim_content:
        bounds = find_content_bounds(gray)
        if bounds:
            x, y, w, h = bounds
            if w < gray.shape[1] or h < gray.shape[0]:
                gray = gray[y:y + h, x:x + w]

    if contrast_level > 0:
        gray = apply_contrast(gray, contrast_level)

    pil_gray = Image.fromarray(np.clip(gray, 0, 255).astype(np.uint8), mode='L')

    # Rotate landscape segments for landscape reading
    if pil_gray.width > pil_gray.height:
        pil_gray = pil_gray.transpose(Image.ROTATE_270 if rotate_cw else Image.ROTATE_90)

    pil_gray = resize_with_padding(pil_gray, target_w, target_h)

    gray_arr = np.array(pil_gray, dtype=np.float32)
    dithered = dither(gray_arr, algorithm=dither_algo)

    return Image.fromarray(dithered, mode='L')


def process_cover(img, contrast_level=1, dither_algo='floyd',
                  target_w=TARGET_WIDTH, target_h=TARGET_HEIGHT):
    """Process cover image — no splitting, no rotation, portrait always."""
    gray = to_grayscale(img)

    bounds = find_content_bounds(gray)
    if bounds:
        x, y, w, h = bounds
        if w < gray.shape[1] or h < gray.shape[0]:
            gray = gray[y:y + h, x:x + w]

    if contrast_level > 0:
        gray = apply_contrast(gray, contrast_level)

    pil_gray = Image.fromarray(np.clip(gray, 0, 255).astype(np.uint8), mode='L')
    pil_gray = resize_with_padding(pil_gray, target_w, target_h)

    gray_arr = np.array(pil_gray, dtype=np.float32)
    dithered = dither(gray_arr, algorithm=dither_algo)

    return Image.fromarray(dithered, mode='L')
