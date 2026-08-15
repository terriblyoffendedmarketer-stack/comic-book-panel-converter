# split_page.py — Panel-aware page splitter with e-ink optimization
# Splits comic pages into overlapping horizontal strips ("overlapping thirds")
# for readable display on small e-ink screens like XTe Ink X4.
#
# Usage: called by convert.py pipeline, not standalone
# Requires: Pillow
#
# Gotchas:
# - Naive thirds cut through panels. This uses panel coordinates from Kumiko
#   to find gutter lines between rows and snaps split boundaries to them.
# - For e-ink: grayscale, auto-contrast, sharpen, posterize to 16 levels.
# - Cover pages (page 0) should NOT be split — handle in the caller.
# - White background padding (not black) — matches comic page color on e-ink.

from PIL import Image, ImageOps, ImageEnhance, ImageFilter


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


def compute_split_points(gutters, num_splits, page_height):
    """Compute split y-coordinates, snapping to nearest gutter when close."""
    if num_splits <= 1:
        return []

    ideal = [(i * page_height) // num_splits for i in range(1, num_splits)]
    threshold = page_height * 0.15

    splits = []
    used_gutters = set()
    for y in ideal:
        best = y
        best_dist = threshold + 1
        best_gi = -1
        for gi, g in enumerate(gutters):
            if gi in used_gutters:
                continue
            dist = abs(g - y)
            if dist < best_dist:
                best = g
                best_dist = dist
                best_gi = gi
        if best_dist <= threshold and best_gi >= 0:
            used_gutters.add(best_gi)
        splits.append(best)

    return splits


def determine_splits(panels, page_width, page_height):
    """Determine how many splits and where, based on panel layout.

    Returns (num_splits, split_points).
    Full-bleed pages get 1 split (no splitting).
    """
    if not panels:
        return 3, compute_split_points([], 3, page_height)

    # Full-bleed: single panel covering most of the page
    if len(panels) == 1:
        p = panels[0]
        if p[2] * p[3] > page_width * page_height * 0.5:
            return 1, []

    rows = find_panel_rows(panels)
    gutters = find_gutter_centers(rows)

    num_rows = len(rows)
    if num_rows <= 1:
        num_splits = 1
    elif num_rows == 2:
        num_splits = 2
    else:
        num_splits = 3

    split_points = compute_split_points(gutters, num_splits, page_height)
    return num_splits, split_points


def split_page(img, panels, overlap_pct=0.15):
    """Split a page into overlapping horizontal strips with panel-aware boundaries.

    Returns list of (x, y, w, h) crop regions.
    overlap_pct: fraction of page height shared between adjacent strips.
    """
    w, h = img.size

    num_splits, split_points = determine_splits(panels, w, h)

    if num_splits <= 1:
        return [(0, 0, w, h)]

    boundaries = [0] + split_points + [h]
    overlap_px = int(h * overlap_pct)
    half_overlap = overlap_px // 2

    views = []
    for i in range(len(boundaries) - 1):
        y_start = max(0, boundaries[i] - half_overlap) if i > 0 else 0
        y_end = min(h, boundaries[i + 1] + half_overlap) if i < len(boundaries) - 2 else h
        views.append((0, y_start, w, y_end - y_start))

    return views


def process_for_eink(img, target_width=480, target_height=800):
    """Optimize image for e-ink display: grayscale, contrast, sharpen, resize."""
    if img.mode != 'L':
        img = img.convert('L')

    img = ImageOps.autocontrast(img, cutoff=0.5)
    img = img.filter(ImageFilter.SHARPEN)

    img.thumbnail((target_width, target_height), Image.LANCZOS)

    bg = Image.new('L', (target_width, target_height), 255)
    x_offset = (target_width - img.width) // 2
    y_offset = (target_height - img.height) // 2
    bg.paste(img, (x_offset, y_offset))

    return bg


def process_cover_for_eink(img, target_width=480, target_height=800):
    """Process cover image for e-ink: grayscale, contrast, resize. No splitting."""
    if img.mode != 'L':
        img = img.convert('L')

    img = ImageOps.autocontrast(img, cutoff=0.3)

    img.thumbnail((target_width, target_height), Image.LANCZOS)

    bg = Image.new('L', (target_width, target_height), 255)
    x_offset = (target_width - img.width) // 2
    y_offset = (target_height - img.height) // 2
    bg.paste(img, (x_offset, y_offset))

    return bg
