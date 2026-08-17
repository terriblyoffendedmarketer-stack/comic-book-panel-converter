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
import xml.etree.ElementTree as ET
from pathlib import Path
import rarfile

rarfile.UNRAR_TOOL = "unar"
rarfile.ALT_TOOL = "unar"

IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.tiff'}

MANGA_GENRES = {'seinen', 'shounen', 'shoujo', 'josei', 'shonen', 'shojo',
                'manhua', 'manhwa', 'manga'}
MANGA_SOURCES = {'mangadex', 'manga', 'mihon', 'tachiyomi', 'komga'}
CJK_RANGES = [
    (0x3000, 0x303F),   # CJK punctuation
    (0x3040, 0x309F),   # Hiragana
    (0x30A0, 0x30FF),   # Katakana
    (0x4E00, 0x9FFF),   # CJK unified ideographs
    (0xAC00, 0xD7AF),   # Hangul
]


def has_cjk(text):
    for ch in text:
        cp = ord(ch)
        for start, end in CJK_RANGES:
            if start <= cp <= end:
                return True
    return False


def detect_reading_direction(comic_path):
    """
    Auto-detect if a comic is manga (RTL) or western (LTR).
    Returns ('rtl', reason) or ('ltr', reason).
    Checks ComicInfo.xml metadata inside CBZ/CBR archives.
    """
    comic_path = Path(comic_path)
    ext = comic_path.suffix.lower()

    marker = comic_path.with_suffix('.manga')
    if marker.exists():
        return 'rtl', 'manga source marker'

    metadata = None
    if ext == '.cbz':
        try:
            with zipfile.ZipFile(comic_path, 'r') as zf:
                if 'ComicInfo.xml' in zf.namelist():
                    with zf.open('ComicInfo.xml') as f:
                        metadata = f.read().decode('utf-8')
        except Exception:
            pass

    if metadata:
        try:
            root = ET.fromstring(metadata)

            # Check explicit Manga field
            manga_elem = root.find('Manga')
            if manga_elem is not None and manga_elem.text:
                val = manga_elem.text.lower()
                if 'yes' in val or 'right' in val:
                    return 'rtl', f'ComicInfo.xml Manga={manga_elem.text}'
                if 'no' in val or 'left' in val:
                    return 'ltr', f'ComicInfo.xml Manga={manga_elem.text}'

            full_text = metadata.lower()

            # Check genres for manga indicators
            genre_elem = root.find('Genre')
            if genre_elem is not None and genre_elem.text:
                genres = {g.strip().lower() for g in genre_elem.text.split(',')}
                matches = genres & MANGA_GENRES
                if matches:
                    return 'rtl', f'genre: {", ".join(matches)}'

            # Check for CJK in title/summary (Japanese/Chinese/Korean names)
            for field in ['Title', 'Series', 'Summary']:
                elem = root.find(field)
                if elem is not None and elem.text and has_cjk(elem.text):
                    return 'rtl', f'CJK text in {field}'

            # Check source (Mihon/Tachiyomi = manga reader)
            for elem in root.iter():
                if 'source' in elem.tag.lower() or 'mihon' in elem.tag.lower():
                    if elem.text:
                        for src in MANGA_SOURCES:
                            if src in elem.text.lower():
                                return 'rtl', f'source: {elem.text}'

        except ET.ParseError:
            pass

    return 'ltr', 'default (no manga indicators found)'


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
