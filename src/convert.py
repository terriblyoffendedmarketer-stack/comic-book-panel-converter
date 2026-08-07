# convert.py — Full pipeline: comic file → panel-by-panel EPUB
# Usage: python src/convert.py <comic-file> [--manga] [--ltr] [--title "Title"] [--output file.epub]
# Requires: all deps from extract.py, detect_panels.py, build_epub.py
#
# Reading direction is auto-detected from ComicInfo.xml metadata (genre, CJK text,
# source app). Override with --manga (force RTL) or --ltr (force LTR).

import sys
import shutil
from pathlib import Path

from extract import extract, detect_reading_direction
from detect_panels import detect_panels, crop_panels, process_directory
from build_epub import build_epub


def convert(comic_path, manga=None, title=None, output_path=None, keep_intermediates=False):
    comic_path = Path(comic_path)
    print(f"=== Converting: {comic_path.name} ===\n")

    # Auto-detect reading direction if not explicitly set
    if manga is None:
        direction, reason = detect_reading_direction(comic_path)
        manga = (direction == 'rtl')
        print(f"[auto] Reading direction: {'RTL (manga)' if manga else 'LTR (western)'} — {reason}")
    else:
        print(f"[manual] Reading direction: {'RTL (manga)' if manga else 'LTR (western)'}")
    print()

    if title is None:
        title = comic_path.stem

    # Step 1: Extract pages
    print("[1/3] Extracting pages...")
    pages_dir = extract(comic_path)
    print()

    # Grab the first page as cover image before panels get cropped
    cover_path = None
    cover_candidates = sorted(pages_dir.glob("page_*.*"))
    if cover_candidates:
        cover_path = cover_candidates[0]

    # Step 2: Detect and crop panels
    print("[2/3] Detecting panels...")
    panels_dir = process_directory(pages_dir, manga=manga)
    print()

    # Step 3: Build EPUB
    print("[3/3] Building EPUB...")
    epub_path = build_epub(panels_dir, title=title, output_path=output_path, cover_image_path=cover_path, manga=manga)

    # Cleanup intermediates
    if not keep_intermediates:
        shutil.rmtree(pages_dir)
        shutil.rmtree(panels_dir)
        print(f"\nCleaned up intermediate files.")

    print(f"\n=== Done! EPUB ready: {epub_path} ===")
    return epub_path


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python src/convert.py <comic-file> [--manga] [--ltr] [--title \"Title\"] [--output file.epub] [--keep]")
        sys.exit(1)

    comic = sys.argv[1]
    keep = "--keep" in sys.argv

    # Reading direction: None = auto-detect, True = manga RTL, False = western LTR
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

    convert(comic, manga=manga, title=title, output_path=output, keep_intermediates=keep)
