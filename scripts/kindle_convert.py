# kindle_convert.py — Clean Kindle EPUB builder for graphic novels
# Usage: python scripts/kindle_convert.py <comic-file> --title "Title"
# Requires: Pillow, ebooklib
#
# Approach: full-page conversion, no panel splitting. Each source page becomes
# one EPUB page, resized to Kindle Paperwhite viewport (1072x1448).
# For e-ink: grayscale, light sharpening, high-quality JPEG.
#
# Gotchas:
# - EPUB graphic novels (.epub) may have text as HTML overlays — DON'T extract
#   just images. Use the source EPUB directly for Kindle.
# - CBR/CBZ/PDF have text baked into images — those need this conversion.
# - ebooklib strips viewport meta tags — must post-process the ZIP to inject them.
# - Don't use KCC — it drops text-only pages and mangles non-manga content.

import sys
import os
import glob
import shutil
from pathlib import Path
from io import BytesIO
from PIL import Image, ImageFilter, ImageOps

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / 'src'))

from extract import extract
from build_epub import build_epub

KINDLE_WIDTH = 1072
KINDLE_HEIGHT = 1448


def process_for_kindle(img):
    """Optimize a page image for Kindle Paperwhite e-ink display."""
    if img.mode != 'L':
        img = ImageOps.grayscale(img)

    w, h = img.size
    ratio = min(KINDLE_WIDTH / w, KINDLE_HEIGHT / h)
    if ratio < 1:
        new_w = int(w * ratio)
        new_h = int(h * ratio)
        img = img.resize((new_w, new_h), Image.LANCZOS)

    img = ImageOps.autocontrast(img, cutoff=0.5)
    img = img.filter(ImageFilter.UnsharpMask(radius=1.0, percent=50, threshold=2))

    return img


def process_for_kindle_landscape(img):
    """Optimize a landscape page for Kindle — keep landscape orientation."""
    if img.mode != 'L':
        img = ImageOps.grayscale(img)

    w, h = img.size
    target_w = max(KINDLE_WIDTH, KINDLE_HEIGHT)  # 1448
    target_h = min(KINDLE_WIDTH, KINDLE_HEIGHT)  # 1072
    ratio = min(target_w / w, target_h / h)
    if ratio < 1:
        new_w = int(w * ratio)
        new_h = int(h * ratio)
        img = img.resize((new_w, new_h), Image.LANCZOS)

    img = ImageOps.autocontrast(img, cutoff=0.5)
    img = img.filter(ImageFilter.UnsharpMask(radius=1.0, percent=50, threshold=2))

    return img


def convert_one(comic_path, title, output_dir, no_rotate=False):
    """Convert a single comic file to Kindle EPUB."""
    comic_path = Path(comic_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    temp_dir = output_dir / '_temp_kindle_work'

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

    skipped = 0
    for i, page_file in enumerate(page_files):
        try:
            img = Image.open(page_file)
            img.load()
            if no_rotate:
                processed = process_for_kindle_landscape(img)
            else:
                processed = process_for_kindle(img)

            out_path = processed_dir / f"page_{i:04d}.jpg"
            processed.save(str(out_path), "JPEG", quality=92)
        except (OSError, IOError) as e:
            print(f"  Warning: skipping corrupt page {page_file.name}: {e}")
            skipped += 1
            continue

        if (i + 1) % 50 == 0 or i == 0:
            print(f"  Processed {i + 1}/{len(page_files)} pages")

    if skipped:
        print(f"  Skipped {skipped} corrupt pages")

    print(f"  All {len(page_files)} pages processed")

    epub_path = output_dir / f"{title}.epub"
    print(f"  Building EPUB...")

    if no_rotate:
        from build_epub import build_epub as _build_epub, LANDSCAPE_THRESHOLD
        import build_epub as _bmod
        old_thresh = _bmod.LANDSCAPE_THRESHOLD
        _bmod.LANDSCAPE_THRESHOLD = 999
        _build_epub(
            str(processed_dir),
            title=title,
            output_path=str(epub_path),
            max_width=max(KINDLE_WIDTH, KINDLE_HEIGHT),
            max_height=min(KINDLE_WIDTH, KINDLE_HEIGHT),
        )
        _bmod.LANDSCAPE_THRESHOLD = old_thresh
    else:
        build_epub(
            str(processed_dir),
            title=title,
            output_path=str(epub_path),
            max_width=KINDLE_WIDTH,
            max_height=KINDLE_HEIGHT,
        )

    if temp_dir.exists():
        shutil.rmtree(temp_dir, ignore_errors=True)

    size_mb = epub_path.stat().st_size / 1024 / 1024
    print(f"  Done: {epub_path.name} ({size_mb:.1f} MB, {len(page_files)} pages)")
    return epub_path


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python scripts/kindle_convert.py <comic-file> --title 'Title'")
        sys.exit(1)

    comic_file = sys.argv[1]
    title = None
    if '--title' in sys.argv:
        idx = sys.argv.index('--title')
        if idx + 1 < len(sys.argv):
            title = sys.argv[idx + 1]

    no_rotate = '--no-rotate' in sys.argv

    if title is None:
        title = Path(comic_file).stem

    convert_one(comic_file, title, 'output/Kindle', no_rotate=no_rotate)
