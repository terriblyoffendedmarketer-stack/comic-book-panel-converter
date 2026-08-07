# convert.py — Full pipeline: comic file → panel-by-panel EPUB
# Usage: python src/convert.py <comic-file> [--manga] [--title "Title"] [--output file.epub]
# Requires: all deps from extract.py, detect_panels.py, build_epub.py
#
# This is the main entry point that chains:
# 1. Extract pages from archive (CBZ/CBR/CB7)
# 2. Detect and crop panels from each page
# 3. Build EPUB with one panel per page

import sys
import shutil
from pathlib import Path

from extract import extract
from detect_panels import detect_panels, crop_panels, process_directory
from build_epub import build_epub


def convert(comic_path, manga=False, title=None, output_path=None, keep_intermediates=False):
    comic_path = Path(comic_path)
    print(f"=== Converting: {comic_path.name} ===\n")

    if title is None:
        title = comic_path.stem

    # Step 1: Extract pages
    print("[1/3] Extracting pages...")
    pages_dir = extract(comic_path)
    print()

    # Step 2: Detect and crop panels
    print("[2/3] Detecting panels...")
    panels_dir = process_directory(pages_dir, manga=manga)
    print()

    # Step 3: Build EPUB
    print("[3/3] Building EPUB...")
    epub_path = build_epub(panels_dir, title=title, output_path=output_path)

    # Cleanup intermediates
    if not keep_intermediates:
        shutil.rmtree(pages_dir)
        shutil.rmtree(panels_dir)
        print(f"\nCleaned up intermediate files.")

    print(f"\n=== Done! EPUB ready: {epub_path} ===")
    return epub_path


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python src/convert.py <comic-file> [--manga] [--title \"Title\"] [--output file.epub] [--keep]")
        sys.exit(1)

    comic = sys.argv[1]
    manga = "--manga" in sys.argv
    keep = "--keep" in sys.argv

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
