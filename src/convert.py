# convert.py — Full pipeline: comic file → e-reader optimized output
# Usage: python src/convert.py <comic-file> [--device kindle|xteink] [--manga] [--ltr] [--title "Title"]
#
# Two output paths:
#   kindle  — Uses KCC for proper Kindle EPUB (whole pages, correct metadata,
#             virtual panel view enabled in Kindle's Aa menu)
#   xteink  — Uses Kumiko panel detection for panel-per-page EPUB
#             optimized for CrossPoint on XTe Ink X4 (480x800)
#
# Reading direction auto-detected from ComicInfo.xml. Override with --manga or --ltr.
#
# Gotchas:
# - KCC needs 7z (brew install p7zip, symlink 7z to 7zz if needed)
# - KCC profiles: KPW=Paperwhite, KCS=Colorsoft, KS=Scribe, OTHER=custom
# - For XTe Ink, Kumiko detects panels and we build a custom EPUB sized to 480x800

import sys
import shutil
from pathlib import Path

from extract import extract, detect_reading_direction
from detect_panels import detect_panels, crop_panels, process_directory
from build_epub import build_epub

DEVICE_PROFILES = {
    'kindle': {
        'name': 'Kindle Paperwhite 7th Gen',
        'kcc_profile': 'KPW',
        'width': 1072,
        'height': 1448,
        'method': 'kcc',
    },
    'xteink': {
        'name': 'XTe Ink X4 (CrossPoint, portrait)',
        'width': 480,
        'height': 800,
        'method': 'panels',
    },
}


def convert_kcc(comic_path, manga, title, output_path, device):
    """Convert using KCC — produces whole-page EPUB with proper Kindle metadata."""
    from kindlecomicconverter.comic2ebook import main as kcc_main

    if output_path is None:
        output_path = Path("output")

    args = [
        '-p', device['kcc_profile'],
        '-f', 'EPUB',
        '--forcecolor',
        '-c', '1',
        '-o', str(output_path),
    ]

    if title:
        args.extend(['-t', title])

    if manga:
        args.append('-m')

    args.append(str(comic_path))

    print(f"  KCC profile: {device['kcc_profile']} ({device['name']})")
    print(f"  Output: EPUB with virtual panel view support")

    import sys as _sys
    old_argv = _sys.argv
    _sys.argv = ['kcc-c2e'] + args
    try:
        kcc_main(args)
    finally:
        _sys.argv = old_argv


def convert_panels(comic_path, manga, title, output_path, device, keep_intermediates):
    """Convert using Kumiko panel detection — one panel per page EPUB."""
    print("[1/3] Extracting pages...")
    pages_dir = extract(comic_path)
    print()

    cover_path = None
    cover_candidates = sorted(pages_dir.glob("page_*.*"))
    if cover_candidates:
        cover_path = cover_candidates[0]

    print("[2/3] Detecting panels...")
    panels_dir = process_directory(pages_dir, manga=manga)
    print()

    print("[3/3] Building EPUB...")
    epub_path = build_epub(
        panels_dir,
        title=title,
        output_path=output_path,
        cover_image_path=cover_path,
        manga=manga,
        max_width=device['width'],
        max_height=device['height'],
    )

    if not keep_intermediates:
        shutil.rmtree(pages_dir)
        shutil.rmtree(panels_dir)
        print(f"\nCleaned up intermediate files.")

    return epub_path


def convert(comic_path, device_key='kindle', manga=None, title=None, output_path=None, keep_intermediates=False):
    comic_path = Path(comic_path)
    if not comic_path.exists():
        print(f"Error: {comic_path} not found")
        sys.exit(1)

    device = DEVICE_PROFILES[device_key]
    print(f"=== Converting: {comic_path.name} ===")
    print(f"  Device: {device['name']}\n")

    if manga is None:
        direction, reason = detect_reading_direction(comic_path)
        manga = (direction == 'rtl')
        print(f"[auto] Reading direction: {'RTL (manga)' if manga else 'LTR (western)'} — {reason}")
    else:
        print(f"[manual] Reading direction: {'RTL (manga)' if manga else 'LTR (western)'}")
    print()

    if title is None:
        title = comic_path.stem

    if device['method'] == 'kcc':
        print("[KCC] Converting with Kindle Comic Converter...")
        convert_kcc(comic_path, manga, title, output_path, device)
        print(f"\n=== Done! Kindle EPUB ready in output/ ===")
        print(f"  Tip: Enable virtual panel view in Kindle's Aa menu for panel-by-panel reading")
    else:
        epub_path = convert_panels(comic_path, manga, title, output_path, device, keep_intermediates)
        print(f"\n=== Done! EPUB ready: {epub_path} ===")
        return epub_path


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python src/convert.py <comic-file> [--device kindle|xteink] [--manga] [--ltr] [--title \"Title\"] [--keep]")
        print("\nDevices:")
        for key, d in DEVICE_PROFILES.items():
            print(f"  {key:10s} — {d['name']} ({d['width']}x{d['height']})")
        sys.exit(1)

    comic = sys.argv[1]
    keep = "--keep" in sys.argv

    device_key = 'kindle'
    if "--device" in sys.argv:
        idx = sys.argv.index("--device")
        if idx + 1 < len(sys.argv):
            device_key = sys.argv[idx + 1]

    if device_key not in DEVICE_PROFILES:
        print(f"Unknown device '{device_key}'. Available: {', '.join(DEVICE_PROFILES.keys())}")
        sys.exit(1)

    manga = None
    if "--manga" in sys.argv:
        manga = True
    elif "--ltr" in sys.argv:
        manga = False

    title = None
    if "--title" in sys.argv:
        idx = sys.argv.index("--title")
        if idx + 1 < len(sys.argv):
            title = sys.argv[idx + 1]

    output = None
    if "--output" in sys.argv:
        idx = sys.argv.index("--output")
        if idx + 1 < len(sys.argv):
            output = sys.argv[idx + 1]

    convert(comic, device_key=device_key, manga=manga, title=title, output_path=output, keep_intermediates=keep)
