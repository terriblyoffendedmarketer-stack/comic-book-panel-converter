# batch_convert.py — Converts philosophy graphic novels for Kindle and XTe Ink
# Usage: python scripts/batch_convert.py [--kindle-only] [--xteink-only]
# Requires: All project dependencies (see requirements.txt)
#
# Each comic gets a per-comic conversion strategy based on its visual characteristics:
# - Panel layout (grid, rows, full-page)
# - Text density (heavy dialogue vs visual storytelling)
# - Art style (B&W line art vs color vs painterly)
# - Page orientation (portrait vs landscape)
#
# Kindle: KCC produces fixed-layout EPUBs with virtual panel view.
# XTe Ink: Panel-per-page extraction → xtc_pipeline processing → XTC output.
#
# Gotchas:
# - KCC needs 7zz symlink: brew install p7zip && ln -sf /opt/homebrew/bin/7z /opt/homebrew/bin/7zz
# - KCC can take a directory of images (for EPUB/PDF sources) or a CBR/CBZ directly
# - For XTe Ink, Atkinson dithering is better for bold B&W art (Understanding Comics style),
#   Floyd-Steinberg is better for painterly/photographic art (Verissimus, Here)
# - Panel detection via Kumiko sometimes detects too many panels on pages with
#   irregular layouts — group_panels_into_views handles this with row grouping

import sys
import os
import glob
import shutil
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / 'src'))

from extract import extract, detect_reading_direction
from detect_panels import detect_panels, group_panels_into_views, crop_panels
from xtc_pipeline import process_page, process_cover
from build_xtc import image_to_xtg, build_xtc
from PIL import Image


DOWNLOADS = Path.home() / 'Downloads'
OUTPUT_ROOT = PROJECT_ROOT / 'output'

COMICS = [
    {
        'name': 'Understanding Comics',
        'glob': 'Understanding Comics*',
        'devices': ['kindle'],
        'reason': 'Extremely text-heavy educational comic — needs 6" Kindle screen for readability',
        'manga': False,
    },
    {
        'name': 'Logicomix',
        'glob': 'Logicomix*',
        'devices': ['kindle'],
        'reason': 'Dense multi-panel layout with heavy dialogue — too detailed for 4.3" XTe Ink',
        'manga': False,
    },
    {
        'name': 'Here',
        'glob': 'Here*McGuire*',
        'devices': ['kindle'],
        'reason': 'Landscape full-page compositions — cannot split without destroying the art',
        'manga': False,
    },
    {
        'name': '99 Ways to Tell a Story',
        'glob': '99 Ways*',
        'devices': ['kindle', 'xteink'],
        'reason': 'Clean 3-row grid, minimal text — XTe Ink: panel-per-page, Atkinson dither for B&W',
        'xteink_dither': 'atkinson',
        'manga': False,
    },
    {
        'name': 'Aristotle',
        'glob': 'Aristotle*',
        'devices': ['kindle', 'xteink'],
        'reason': '2-3 large horizontal panels, minimal text, sepia/blue tones → great grayscale',
        'xteink_dither': 'floyd',
        'manga': False,
    },
    {
        'name': 'Verissimus',
        'glob': 'Verissimus*',
        'devices': ['kindle', 'xteink'],
        'reason': '2 large painterly panels per page — Floyd-Steinberg preserves gradients',
        'xteink_dither': 'floyd',
        'manga': False,
    },
    {
        'name': 'The Labyrinth',
        'glob': 'The Labyrinth*',
        'devices': ['kindle', 'xteink'],
        'reason': '2x2 grid of bold B&W panels — perfect panel-per-page for XTe Ink',
        'xteink_dither': 'atkinson',
        'manga': False,
    },
]


def find_comic(comic_glob):
    matches = glob.glob(str(DOWNLOADS / comic_glob))
    if matches:
        return Path(matches[0])
    return None


def convert_kindle(comic_path, title, manga=False):
    """Convert for Kindle using KCC. Returns EPUB path or None."""
    out_dir = OUTPUT_ROOT / 'Kindle'
    out_dir.mkdir(parents=True, exist_ok=True)
    temp_dir = OUTPUT_ROOT / '_temp_kindle'

    ext = comic_path.suffix.lower()

    # Always extract to directory first — KCC fails on some CBR filenames
    print(f"  Extracting pages for KCC...")
    pages_dir = extract(comic_path, output_base=temp_dir)
    kcc_input = str(pages_dir)

    print(f"  Running KCC (profile: KPW)...")
    try:
        from kindlecomicconverter.comic2ebook import main as kcc_main
        args = [
            '-p', 'KPW',
            '-f', 'EPUB',
            '-c', '1',
            '-o', str(out_dir),
            '-t', title,
        ]
        if manga:
            args.append('-m')
        args.append(kcc_input)

        old_argv = sys.argv
        sys.argv = ['kcc-c2e'] + args
        try:
            kcc_main(args)
        finally:
            sys.argv = old_argv

        epubs = sorted(out_dir.glob("*.epub"), key=lambda f: f.stat().st_mtime)
        if epubs:
            result = epubs[-1]
            print(f"  ✓ Kindle EPUB: {result.name}")
            return result
        print(f"  ✗ KCC produced no output")
        return None
    except Exception as e:
        print(f"  ✗ KCC error: {e}")
        return None
    finally:
        if pages_dir.exists():
            shutil.rmtree(pages_dir, ignore_errors=True)


def convert_xteink_panels(comic_path, title, dither_algo='floyd', manga=False):
    """Convert for XTe Ink: panel detection → process each panel → build XTC."""
    out_dir = OUTPUT_ROOT / 'XTe Ink'
    out_dir.mkdir(parents=True, exist_ok=True)
    temp_dir = OUTPUT_ROOT / '_temp_xteink'

    print(f"  Extracting pages...")
    pages_dir = extract(comic_path, output_base=temp_dir)

    skip = ("_debug", "_grouped")
    pages = sorted(
        [p for p in pages_dir.iterdir()
         if p.suffix.lower() in {'.jpg', '.jpeg', '.png'} and not any(s in p.name for s in skip)],
        key=lambda f: f.name
    )

    if not pages:
        print(f"  ✗ No pages found")
        return None

    print(f"  {len(pages)} pages extracted")

    xtg_pages = []

    # Process cover (first page, no splitting)
    print(f"  Processing cover...")
    cover_img = Image.open(pages[0])
    cover = process_cover(cover_img, dither_algo=dither_algo, contrast_level=2, sharpen=0.7)
    xtg_pages.append(image_to_xtg(cover))

    # Process content pages with panel detection
    content_pages = pages[1:]
    total_panels = 0

    for page_idx, page_path in enumerate(content_pages):
        img = Image.open(page_path)
        pw, ph = img.size

        # Detect panels
        panels = detect_panels(page_path, manga=manga)
        views = group_panels_into_views(panels, pw, ph)

        if not views:
            views = [(0, 0, pw, ph)]

        for vx, vy, vw, vh in views:
            # Crop the panel with small padding
            padding = 5
            x1 = max(0, vx - padding)
            y1 = max(0, vy - padding)
            x2 = min(pw, vx + vw + padding)
            y2 = min(ph, vy + vh + padding)
            panel_img = img.crop((x1, y1, x2, y2))

            # Process through XTe Ink pipeline
            processed = process_page(
                panel_img,
                dither_algo=dither_algo,
                contrast_level=2,
                sharpen=0.7,
                trim_content=True,
            )
            xtg_pages.append(image_to_xtg(processed))
            total_panels += 1

        if (page_idx + 1) % 50 == 0:
            print(f"  Processed {page_idx + 1}/{len(content_pages)} pages ({total_panels} panels)...")

    print(f"  {total_panels} panels from {len(content_pages)} pages")

    # Build XTC
    print(f"  Building XTC...")
    xtc_path = out_dir / f"{title}.xtc"
    xtc_data = build_xtc(xtg_pages, title=title)
    xtc_path.write_bytes(xtc_data)
    print(f"  ✓ XTe Ink XTC: {xtc_path.name} ({len(xtg_pages)} pages, {len(xtc_data) / 1024 / 1024:.1f} MB)")

    # Clean up extracted pages
    if pages_dir.exists():
        shutil.rmtree(pages_dir, ignore_errors=True)

    return xtc_path


def main():
    kindle_only = '--kindle-only' in sys.argv
    xteink_only = '--xteink-only' in sys.argv

    print("=" * 60)
    print("BATCH COMIC CONVERSION")
    print(f"Output: {OUTPUT_ROOT}")
    print("=" * 60)

    results = []
    start_time = time.time()

    for comic in COMICS:
        path = find_comic(comic['glob'])
        if not path:
            print(f"\n✗ {comic['name']}: file not found (glob: {comic['glob']})")
            results.append((comic['name'], 'NOT FOUND', None, None))
            continue

        print(f"\n{'=' * 60}")
        print(f"  {comic['name']}")
        print(f"  File: {path.name}")
        print(f"  Strategy: {comic['reason']}")
        print(f"  Devices: {', '.join(comic['devices'])}")
        print(f"{'=' * 60}")

        kindle_result = None
        xteink_result = None
        title = comic['name']

        if 'kindle' in comic['devices'] and not xteink_only:
            print(f"\n  [KINDLE]")
            kindle_result = convert_kindle(path, title, manga=comic['manga'])

        if 'xteink' in comic['devices'] and not kindle_only:
            print(f"\n  [XTe INK]")
            xteink_result = convert_xteink_panels(
                path, title,
                dither_algo=comic.get('xteink_dither', 'floyd'),
                manga=comic['manga'],
            )

        results.append((comic['name'], path.name, kindle_result, xteink_result))

    # Clean up any remaining temp directories
    for d in ('_temp_kindle', '_temp_xteink'):
        td = OUTPUT_ROOT / d
        if td.exists():
            shutil.rmtree(td, ignore_errors=True)

    elapsed = time.time() - start_time

    print(f"\n{'=' * 60}")
    print(f"RESULTS (completed in {elapsed:.0f}s)")
    print(f"{'=' * 60}")
    for name, source, kindle, xteink in results:
        status = []
        if kindle:
            status.append(f"Kindle: {Path(kindle).name}")
        if xteink:
            status.append(f"XTe Ink: {Path(xteink).name}")
        if not status:
            status.append("SKIPPED" if source != 'NOT FOUND' else "NOT FOUND")
        print(f"  {name}: {' | '.join(status)}")


if __name__ == '__main__':
    main()
