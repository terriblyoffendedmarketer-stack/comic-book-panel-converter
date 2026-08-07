# extract.py — Extracts page images from comic book archives (CBZ/CBR/CB7)
# Usage: python src/extract.py <comic-file> [--output-dir output/]
# Requires: rarfile, py7zr, Pillow
# System dep: brew install unrar (for CBR files)
#
# Gotchas:
# - CBZ is just a ZIP, CBR is RAR, CB7 is 7zip — all contain sequential images.
# - Image filenames inside archives aren't always zero-padded, so sort naturally.
# - Some archives nest images inside a subdirectory — we flatten on extract.
# - On macOS, `brew install unrar` doesn't exist anymore. Use `brew install unar`
#   and set rarfile.UNRAR_TOOL = "unar" + rarfile.ALT_TOOL = "unar".

import sys
import os
import zipfile
import shutil
import re
from pathlib import Path
import rarfile

rarfile.UNRAR_TOOL = "unar"
rarfile.ALT_TOOL = "unar"

IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.tiff'}


def natural_sort_key(s):
    """Sort strings with embedded numbers in human order (page1, page2, page10)."""
    return [int(c) if c.isdigit() else c.lower() for c in re.split(r'(\d+)', str(s))]


def is_image(filename):
    return Path(filename).suffix.lower() in IMAGE_EXTENSIONS


def extract_cbz(filepath, output_dir):
    """Extract images from a CBZ (ZIP) archive."""
    with zipfile.ZipFile(filepath, 'r') as zf:
        image_names = sorted(
            [n for n in zf.namelist() if is_image(n) and not n.startswith('__MACOSX')],
            key=natural_sort_key
        )
        for i, name in enumerate(image_names):
            ext = Path(name).suffix.lower()
            out_path = output_dir / f"page_{i:04d}{ext}"
            with zf.open(name) as src, open(out_path, 'wb') as dst:
                shutil.copyfileobj(src, dst)
        return len(image_names)


def extract_cbr(filepath, output_dir):
    """Extract images from a CBR (RAR) archive."""
    with rarfile.RarFile(filepath, 'r') as rf:
        image_names = sorted(
            [n for n in rf.namelist() if is_image(n)],
            key=natural_sort_key
        )
        for i, name in enumerate(image_names):
            ext = Path(name).suffix.lower()
            out_path = output_dir / f"page_{i:04d}{ext}"
            with rf.open(name) as src, open(out_path, 'wb') as dst:
                shutil.copyfileobj(src, dst)
        return len(image_names)


def extract_cb7(filepath, output_dir):
    """Extract images from a CB7 (7zip) archive."""
    import py7zr
    with py7zr.SevenZipFile(filepath, 'r') as sz:
        all_files = sz.getnames()
        image_names = sorted(
            [n for n in all_files if is_image(n)],
            key=natural_sort_key
        )
        sz.extractall(path=output_dir)
        # Flatten: rename extracted files to sequential page names
        extracted = []
        for name in image_names:
            src_path = output_dir / name
            if src_path.exists():
                extracted.append(src_path)
        for i, src_path in enumerate(extracted):
            ext = src_path.suffix.lower()
            dst_path = output_dir / f"page_{i:04d}{ext}"
            if src_path != dst_path:
                src_path.rename(dst_path)
        # Clean up any leftover subdirectories
        for item in output_dir.iterdir():
            if item.is_dir():
                shutil.rmtree(item)
        return len(extracted)


EXTRACTORS = {
    '.cbz': extract_cbz,
    '.cbr': extract_cbr,
    '.cb7': extract_cb7,
}


def extract(filepath, output_base=None):
    filepath = Path(filepath)
    if not filepath.exists():
        print(f"Error: {filepath} not found")
        sys.exit(1)

    ext = filepath.suffix.lower()
    if ext not in EXTRACTORS:
        print(f"Error: unsupported format '{ext}'. Supported: {', '.join(EXTRACTORS)}")
        sys.exit(1)

    if output_base is None:
        output_base = Path("output")
    else:
        output_base = Path(output_base)

    output_dir = output_base / filepath.stem
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Extracting {filepath.name} → {output_dir}/")
    count = EXTRACTORS[ext](filepath, output_dir)
    print(f"Done. {count} pages extracted.")
    return output_dir


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python src/extract.py <comic-file> [--output-dir <dir>]")
        sys.exit(1)

    comic_path = sys.argv[1]
    output_dir = None
    if "--output-dir" in sys.argv:
        idx = sys.argv.index("--output-dir")
        if idx + 1 < len(sys.argv):
            output_dir = sys.argv[idx + 1]

    extract(comic_path, output_dir)
