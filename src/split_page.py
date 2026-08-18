# split_page.py — Overlapping-thirds page splitter with e-ink optimization
# Replicates the xtcjs overlapping segments algorithm for XTe Ink X4 (480x800),
# with an enhancement: split boundaries snap to panel gutters when detected.
#
# Usage: called by convert.py and web_app.py pipeline, not standalone
# Requires: Pillow
#
# Gotchas:
# - The xtcjs algorithm scales page width to 800px (XTe Ink height in landscape),
#   then computes how many image pixels map to the 480px width. This gives the
#   segment height. 3 segments with overlap, more only if overlap < 5%.
# - Panel gutter snapping adjusts each segment boundary to the nearest gutter
#   within 15% of segment height. This avoids cutting through panels.
# - Cover pages (page 0) should NOT be split — handle in the caller.
# - White background padding (not black) — matches comic page color on e-ink.

from PIL import Image, ImageOps, ImageFilter
import math


def calculate_overlap_segments(width, height):
    """Calculate overlapping segments for the 480x800 XTe Ink display.

    Replicates xtcjs calculateOverlapSegments():
    - scale = 800 / width (maps page width to display height in landscape)
    - segmentHeight = floor(480 / scale) (display width mapped back to page pixels)
    - Start with 3 segments, add more only if overlap drops below 5%
    - Each segment shifts by 'shift' pixels; last segment extends to page bottom
    """
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
    """Adjust segment start positions to snap to nearest panel gutters.

    For each segment after the first, check if its start position (y) is
    near a gutter. If within 15% of segment height, shift y to the gutter.
    Segment heights are recalculated to maintain coverage of the full page.
    """
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
        if i == num - 1:
            h = page_height - y
        else:
            h = max(segment_height, starts[i + 1] + segment_height - starts[i + 1])
            h = segment_height
        result.append((0, y, width, h))

    if result[-1][1] + result[-1][3] < page_height:
        last = result[-1]
        result[-1] = (0, last[1], width, page_height - last[1])

    return result


def split_page(img, panels):
    """Split a page into overlapping segments using the xtcjs algorithm.

    If panel data is available, segment boundaries are snapped to gutters.
    Returns list of (x, y, w, h) crop regions.
    """
    w, h = img.size

    segments = calculate_overlap_segments(w, h)

    if len(segments) <= 1:
        return segments

    if panels:
        rows = find_panel_rows(panels)
        gutters = find_gutter_centers(rows)
        if gutters:
            segments = snap_segments_to_gutters(segments, gutters, h)

    return segments


def floyd_steinberg_dither(img):
    """Floyd-Steinberg dithering using Pillow's native C implementation.

    Pillow's convert('1') uses Floyd-Steinberg internally, implemented in C —
    ~100x faster than a pure Python pixel loop.
    """
    return img.convert('1').convert('L')


def process_for_eink(img, target_width=480, target_height=800):
    """Optimize segment for e-ink following xtcjs pipeline order:
    grayscale → contrast → rotate → resize → sharpen → dither.

    Sharpen AFTER resize so downscaling doesn't blur it away.
    Contrast cutoff matches xtcjs defaults (3% black, 12% white).
    """
    if img.mode != 'L':
        img = img.convert('L')

    img = ImageOps.autocontrast(img, cutoff=(3, 12))

    if img.width > img.height:
        img = img.transpose(Image.ROTATE_90)

    img.thumbnail((target_width, target_height), Image.LANCZOS)

    bg = Image.new('L', (target_width, target_height), 255)
    x_offset = (target_width - img.width) // 2
    y_offset = (target_height - img.height) // 2
    bg.paste(img, (x_offset, y_offset))

    bg = bg.filter(ImageFilter.UnsharpMask(radius=1, percent=70, threshold=0))

    bg = floyd_steinberg_dither(bg)

    return bg


def process_cover_for_eink(img, target_width=480, target_height=800):
    """Process cover image for e-ink: grayscale, contrast, resize, sharpen, dither. No splitting."""
    if img.mode != 'L':
        img = img.convert('L')

    img = ImageOps.autocontrast(img, cutoff=(3, 12))

    img.thumbnail((target_width, target_height), Image.LANCZOS)

    bg = Image.new('L', (target_width, target_height), 255)
    x_offset = (target_width - img.width) // 2
    y_offset = (target_height - img.height) // 2
    bg.paste(img, (x_offset, y_offset))

    bg = bg.filter(ImageFilter.UnsharpMask(radius=1, percent=70, threshold=0))

    bg = floyd_steinberg_dither(bg)

    return bg
