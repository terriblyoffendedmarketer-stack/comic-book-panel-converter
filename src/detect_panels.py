# detect_panels.py — Detects panel boundaries in comic/manga page images
# Usage: python src/detect_panels.py <image-or-directory> [--manga] [--debug]
# Requires: opencv-python-headless, numpy, Pillow
#
# Gotchas:
# - Uses projection-based gutter detection: project ink density onto rows/columns,
#   find valleys (low-ink bands) = gutters. Works for narrow gutters that
#   morphological approaches miss.
# - Full-page splashes (no panels) return the whole page as a single panel.
# - Manga reading order: rows top-to-bottom, panels RIGHT-to-left within rows.
# - The --debug flag saves annotated images showing detected panel boundaries.

import sys
import cv2
import numpy as np
from pathlib import Path
from PIL import Image


def find_gutter_positions(projection, page_size, min_gutter_width=5, ink_threshold=0.05):
    """
    Find gutter positions from a 1D ink projection.
    A gutter is a contiguous run of rows/columns where ink density is below threshold.
    Returns list of gutter center positions.
    """
    is_gutter = projection < (page_size * ink_threshold)

    gutters = []
    in_gutter = False
    start = 0

    for i in range(len(is_gutter)):
        if is_gutter[i]:
            if not in_gutter:
                in_gutter = True
                start = i
        else:
            if in_gutter:
                width = i - start
                if width >= min_gutter_width:
                    center = (start + i) // 2
                    gutters.append(center)
                in_gutter = False

    return gutters


def detect_panels(image_path, manga=False, min_panel_ratio=0.03, debug=False):
    """
    Detect panels in a comic page image using projection-based gutter detection.
    Returns list of (x, y, w, h) tuples in reading order.
    """
    img = cv2.imread(str(image_path))
    if img is None:
        return []

    h, w = img.shape[:2]
    min_panel_area = h * w * min_panel_ratio

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # Create ink mask (dark pixels = content)
    _, ink = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY_INV)

    # Trim page margins: find content bounding box
    margin_top, margin_bottom = 0, h
    margin_left, margin_right = 0, w

    h_proj = np.sum(ink, axis=1) / 255  # ink pixels per row
    v_proj = np.sum(ink, axis=0) / 255  # ink pixels per column

    # Find content bounds (skip empty margins)
    content_rows = np.where(h_proj > w * 0.01)[0]
    content_cols = np.where(v_proj > h * 0.01)[0]
    if len(content_rows) > 0:
        margin_top = max(0, content_rows[0] - 5)
        margin_bottom = min(h, content_rows[-1] + 5)
    if len(content_cols) > 0:
        margin_left = max(0, content_cols[0] - 5)
        margin_right = min(w, content_cols[-1] + 5)

    # Find horizontal gutters (splits page into rows of panels)
    # Only search within content area
    h_proj_content = h_proj[margin_top:margin_bottom]
    h_gutters = find_gutter_positions(h_proj_content, w, min_gutter_width=5, ink_threshold=0.03)
    h_gutters = [g + margin_top for g in h_gutters]

    # Build horizontal strips
    h_splits = [margin_top] + h_gutters + [margin_bottom]

    panels = []
    for strip_idx in range(len(h_splits) - 1):
        strip_top = h_splits[strip_idx]
        strip_bottom = h_splits[strip_idx + 1]
        strip_height = strip_bottom - strip_top

        if strip_height < 30:
            continue

        # For each horizontal strip, find vertical gutters
        strip_ink = ink[strip_top:strip_bottom, margin_left:margin_right]
        v_proj_strip = np.sum(strip_ink, axis=0) / 255

        v_gutters = find_gutter_positions(v_proj_strip, strip_height, min_gutter_width=5, ink_threshold=0.03)
        v_gutters = [g + margin_left for g in v_gutters]

        v_splits = [margin_left] + v_gutters + [margin_right]

        for col_idx in range(len(v_splits) - 1):
            panel_left = v_splits[col_idx]
            panel_right = v_splits[col_idx + 1]
            panel_width = panel_right - panel_left

            if panel_width < 30:
                continue

            area = panel_width * strip_height
            if area < min_panel_area:
                continue

            panels.append((panel_left, strip_top, panel_width, strip_height))

    # If no panels found, treat whole page as single panel
    if not panels:
        panels = [(margin_left, margin_top, margin_right - margin_left, margin_bottom - margin_top)]

    panels = sort_panels(panels, manga=manga)

    if debug:
        save_debug_image(img, panels, image_path, manga)

    return panels


def sort_panels(panels, manga=False, row_threshold_ratio=0.3):
    """
    Sort panels in reading order.
    Group into rows by vertical position, then sort within rows.
    """
    if not panels:
        return panels

    heights = [h for _, _, _, h in panels]
    median_h = sorted(heights)[len(heights) // 2]
    row_threshold = median_h * row_threshold_ratio

    panels_sorted = sorted(panels, key=lambda p: p[1])

    rows = []
    current_row = [panels_sorted[0]]

    for panel in panels_sorted[1:]:
        prev_y = current_row[0][1]
        if abs(panel[1] - prev_y) < row_threshold:
            current_row.append(panel)
        else:
            rows.append(current_row)
            current_row = [panel]
    rows.append(current_row)

    ordered = []
    for row in rows:
        row_sorted = sorted(row, key=lambda p: p[0], reverse=manga)
        ordered.extend(row_sorted)

    return ordered


def crop_panels(image_path, panels, output_dir, page_index, padding=5):
    """Crop and save individual panels from a page."""
    img = Image.open(image_path)
    w, h = img.size
    saved = []

    for i, (x, y, pw, ph) in enumerate(panels):
        x1 = max(0, x - padding)
        y1 = max(0, y - padding)
        x2 = min(w, x + pw + padding)
        y2 = min(h, y + ph + padding)

        panel_img = img.crop((x1, y1, x2, y2))
        out_path = output_dir / f"page_{page_index:04d}_panel_{i:02d}.jpg"
        panel_img.save(out_path, "JPEG", quality=95)
        saved.append(out_path)

    return saved


def save_debug_image(img, panels, image_path, manga):
    """Save image with panel boundaries drawn for visual verification."""
    debug_img = img.copy()
    colors = [(0, 255, 0), (255, 0, 0), (0, 0, 255), (255, 255, 0),
              (255, 0, 255), (0, 255, 255)]

    for i, (x, y, w, h) in enumerate(panels):
        color = colors[i % len(colors)]
        cv2.rectangle(debug_img, (x, y), (x + w, y + h), color, 3)
        label = f"{i + 1}"
        cv2.putText(debug_img, label, (x + 10, y + 40),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.2, color, 3)

    debug_path = Path(image_path).parent / f"{Path(image_path).stem}_debug.jpg"
    cv2.imwrite(str(debug_path), debug_img)
    direction = "RTL (manga)" if manga else "LTR (western)"
    print(f"  Debug: {debug_path.name} — {len(panels)} panels [{direction}]")


def process_directory(input_dir, output_dir=None, manga=False, debug=False):
    """Process all page images in a directory."""
    input_dir = Path(input_dir)
    if output_dir is None:
        output_dir = input_dir.parent / f"{input_dir.name}_panels"
    else:
        output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    pages = sorted([p for p in input_dir.glob("page_*.jpg") if "_debug" not in p.name])
    if not pages:
        pages = sorted([p for p in input_dir.glob("*.jpg") if "_debug" not in p.name])
    if not pages:
        pages = sorted([p for p in input_dir.glob("*.png") if "_debug" not in p.name])

    total_panels = 0
    for page_path in pages:
        page_idx = int(page_path.stem.split("_")[1]) if "_" in page_path.stem else pages.index(page_path)
        panels = detect_panels(page_path, manga=manga, debug=debug)
        saved = crop_panels(page_path, panels, output_dir, page_idx)
        total_panels += len(saved)
        print(f"  {page_path.name}: {len(panels)} panels")

    print(f"\nDone. {total_panels} panels from {len(pages)} pages → {output_dir}/")
    return output_dir


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python src/detect_panels.py <image-or-directory> [--manga] [--debug]")
        sys.exit(1)

    target = sys.argv[1]
    manga = "--manga" in sys.argv
    debug = "--debug" in sys.argv

    target_path = Path(target)
    if target_path.is_dir():
        process_directory(target_path, manga=manga, debug=debug)
    elif target_path.is_file():
        panels = detect_panels(target_path, manga=manga, debug=debug)
        print(f"{target_path.name}: {len(panels)} panels detected")
        for i, (x, y, w, h) in enumerate(panels):
            print(f"  Panel {i + 1}: x={x}, y={y}, w={w}, h={h}")
    else:
        print(f"Error: {target} not found")
        sys.exit(1)
