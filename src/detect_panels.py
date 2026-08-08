# detect_panels.py — Detects and groups panel boundaries in comic/manga page images
# Usage: python src/detect_panels.py <image-or-directory> [--manga] [--debug]
# Requires: opencv-python-headless, numpy, Pillow
#
# Pipeline: Kumiko detection → merge split panels → group by row → full-bleed fallback
#
# Gotchas:
# - Kumiko is NOT pip-installable (pip install kumiko = Discord bot).
# - Kumiko handles reading order natively — pass numbering='rtl' for manga.
# - merge_split_panels() only merges narrow panels (<45% page width) to avoid
#   merging separate wide panels that happen to share x/width alignment.
# - group_panels_into_views() uses 40% vertical overlap for row detection
#   and 45% page width as the narrow threshold for grouping.

import sys
import os
import cv2
import numpy as np
from pathlib import Path
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
from kumiko import Page, NotAnImageException


def detect_panels(image_path, manga=False, debug=False):
    numbering = 'rtl' if manga else 'ltr'
    try:
        page = Page(str(image_path), numbering=numbering, debug=False, panel_expansion=True)
    except NotAnImageException:
        return []

    panels = []
    for p in page.panels:
        x, y, w, h = p.to_xywh()
        panels.append((x, y, w, h))

    if debug:
        img = cv2.imread(str(image_path))
        if img is not None:
            save_debug_image(img, panels, image_path, manga)

    return panels


def merge_split_panels(panels, page_width, x_tolerance=30, w_tolerance=50, gap_threshold=50):
    """Merge panels that Kumiko incorrectly split vertically.
    Only merges narrow panels (< 45% page width) — wide panels with matching
    x/width are separate intentional panels, not split errors."""
    narrow_threshold = page_width * 0.45
    merged = [list(p) for p in panels]
    changed = True
    while changed:
        changed = False
        for i in range(len(merged)):
            for j in range(i + 1, len(merged)):
                pi, pj = merged[i], merged[j]
                if pi[2] >= narrow_threshold or pj[2] >= narrow_threshold:
                    continue
                if (abs(pi[0] - pj[0]) < x_tolerance and
                        abs(pi[2] - pj[2]) < w_tolerance):
                    bottom_i = pi[1] + pi[3]
                    bottom_j = pj[1] + pj[3]
                    gap = min(abs(bottom_i - pj[1]), abs(bottom_j - pi[1]))
                    if gap < gap_threshold:
                        x = min(pi[0], pj[0])
                        y = min(pi[1], pj[1])
                        x2 = max(pi[0] + pi[2], pj[0] + pj[2])
                        y2 = max(bottom_i, bottom_j)
                        merged[i] = [x, y, x2 - x, y2 - y]
                        merged.pop(j)
                        changed = True
                        break
            if changed:
                break
    return [tuple(p) for p in merged]


def group_panels_into_views(panels, page_width, page_height):
    """Group narrow panels in the same row into combined views.

    Returns a list of views. Each view is (x, y, w, h) — either a single
    panel or the bounding box of multiple grouped panels.

    Full-bleed fallback: if only 1 panel covers >50% of page area,
    returns [(0, 0, page_width, page_height)] — full page.
    """
    if not panels:
        return []

    page_area = page_width * page_height

    if len(panels) == 1:
        p = panels[0]
        panel_area = p[2] * p[3]
        if panel_area > page_area * 0.50:
            return [(0, 0, page_width, page_height)]
        return [panels[0]]

    panels = merge_split_panels(panels, page_width)

    rows = []
    used = set()
    sorted_panels = sorted(enumerate(panels), key=lambda p: p[1][1])

    for idx, panel in sorted_panels:
        if idx in used:
            continue
        row = [idx]
        used.add(idx)

        for idx2, panel2 in sorted_panels:
            if idx2 in used:
                continue
            overlap_start = max(panel[1], panel2[1])
            overlap_end = min(panel[1] + panel[3], panel2[1] + panel2[3])
            overlap = max(0, overlap_end - overlap_start)
            min_h = min(panel[3], panel2[3])
            if min_h > 0 and overlap / min_h > 0.4:
                row.append(idx2)
                used.add(idx2)

        rows.append(row)

    views = []
    narrow_threshold = page_width * 0.45

    for row in rows:
        row_panels = [panels[i] for i in row]
        if len(row_panels) == 1:
            views.append(row_panels[0])
        else:
            narrow_count = sum(1 for p in row_panels if p[2] < narrow_threshold)
            if narrow_count >= 2:
                x_min = min(p[0] for p in row_panels)
                y_min = min(p[1] for p in row_panels)
                x_max = max(p[0] + p[2] for p in row_panels)
                y_max = max(p[1] + p[3] for p in row_panels)
                views.append((x_min, y_min, x_max - x_min, y_max - y_min))
            else:
                views.extend(row_panels)

    return views


def crop_panels(image_path, panels, output_dir, page_index, padding=5):
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


def save_grouped_debug(image_path, raw_panels, views):
    """Debug image showing raw panels (thin lines) and grouped views (thick boxes)."""
    img = cv2.imread(str(image_path))
    if img is None:
        return
    for x, y, w, h in raw_panels:
        cv2.rectangle(img, (x, y), (x + w, y + h), (128, 128, 128), 2)
    view_colors = [(0, 255, 0), (255, 0, 0), (0, 0, 255), (255, 255, 0),
                   (255, 0, 255), (0, 255, 255)]
    for i, (x, y, w, h) in enumerate(views):
        color = view_colors[i % len(view_colors)]
        cv2.rectangle(img, (x, y), (x + w, y + h), color, 6)
        cv2.putText(img, f"V{i + 1}", (x + 10, y + 50),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.5, color, 4)
    debug_path = Path(image_path).parent / f"{Path(image_path).stem}_grouped.jpg"
    cv2.imwrite(str(debug_path), img)
    print(f"  Grouped debug: {debug_path.name} — {len(views)} views")


def process_directory(input_dir, output_dir=None, manga=False, debug=False):
    input_dir = Path(input_dir)
    if output_dir is None:
        output_dir = input_dir.parent / f"{input_dir.name}_panels"
    else:
        output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    skip = ("_debug", "_grouped")
    pages = sorted([p for p in input_dir.glob("page_*.jpg") if not any(s in p.name for s in skip)])
    if not pages:
        pages = sorted([p for p in input_dir.glob("*.jpg") if not any(s in p.name for s in skip)])
    if not pages:
        pages = sorted([p for p in input_dir.glob("*.png") if not any(s in p.name for s in skip)])

    total_views = 0
    for page_path in pages:
        page_idx = int(page_path.stem.split("_")[1]) if "_" in page_path.stem else pages.index(page_path)
        img = Image.open(page_path)
        pw, ph = img.size
        panels = detect_panels(page_path, manga=manga, debug=debug)
        views = group_panels_into_views(panels, pw, ph)
        saved = crop_panels(page_path, views, output_dir, page_idx)
        total_views += len(saved)
        grouped = f" → {len(views)} views" if len(views) != len(panels) else ""
        print(f"  {page_path.name}: {len(panels)} panels{grouped}")

    print(f"\nDone. {total_views} views from {len(pages)} pages → {output_dir}/")
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
