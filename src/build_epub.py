# build_epub.py — Assembles cropped panels into an EPUB (one panel per page)
# Usage: python src/build_epub.py <panels-directory> [--title "Title"] [--output file.epub]
# Requires: ebooklib, Pillow
#
# Gotchas:
# - Kindle wants images sized to device resolution for best display.
#   Kindle Paperwhite: 1236x1648, XTe Ink 4: check specs. We scale to fit
#   within a max dimension while preserving aspect ratio.
# - EPUB images must be referenced with relative paths inside the archive.
# - ebooklib doesn't handle image-only EPUBs perfectly — we wrap each image
#   in minimal HTML for reliable rendering.

import sys
from pathlib import Path
from PIL import Image
from ebooklib import epub
import re


def natural_sort_key(s):
    return [int(c) if c.isdigit() else c.lower() for c in re.split(r'(\d+)', str(s))]


def resize_for_device(img, max_width=1236, max_height=1648):
    """Resize image to fit device screen, preserving aspect ratio."""
    w, h = img.size
    ratio_w = max_width / w
    ratio_h = max_height / h
    ratio = min(ratio_w, ratio_h)

    if ratio < 1:
        new_w = int(w * ratio)
        new_h = int(h * ratio)
        return img.resize((new_w, new_h), Image.LANCZOS)
    return img


def build_epub(panels_dir, title=None, output_path=None, max_width=1236, max_height=1648):
    """Build an EPUB from a directory of panel images."""
    panels_dir = Path(panels_dir)

    if title is None:
        title = panels_dir.name.replace("_panels", "")

    if output_path is None:
        output_path = panels_dir.parent / f"{title}.epub"
    else:
        output_path = Path(output_path)

    # Gather panel images
    panel_files = sorted(
        [f for f in panels_dir.iterdir() if f.suffix.lower() in {'.jpg', '.jpeg', '.png'}],
        key=lambda f: natural_sort_key(f.name)
    )

    if not panel_files:
        print(f"Error: no images found in {panels_dir}")
        sys.exit(1)

    book = epub.EpubBook()
    book.set_identifier(f"comic-{title}")
    book.set_title(title)
    book.set_language("en")

    # Add metadata for comic/manga rendering
    book.add_metadata(None, "meta", "", {"name": "fixed-layout", "content": "true"})
    book.add_metadata(None, "meta", "", {"name": "original-resolution", "content": f"{max_width}x{max_height}"})

    spine = ["nav"]
    toc = []

    for i, panel_file in enumerate(panel_files):
        # Resize image for device
        img = Image.open(panel_file)
        img = resize_for_device(img, max_width, max_height)

        # Convert to JPEG bytes
        from io import BytesIO
        buf = BytesIO()
        if img.mode == "RGBA":
            img = img.convert("RGB")
        img.save(buf, "JPEG", quality=92)
        img_data = buf.getvalue()
        img_w, img_h = img.size

        img_filename = f"images/panel_{i:04d}.jpg"
        epub_img = epub.EpubImage()
        epub_img.file_name = img_filename
        epub_img.media_type = "image/jpeg"
        epub_img.content = img_data
        book.add_item(epub_img)

        # Create HTML page for this panel
        page_id = f"panel_{i:04d}"

        chapter = epub.EpubHtml(
            title=f"Panel {i+1}",
            file_name=f"{page_id}.xhtml",
            lang="en"
        )
        chapter.content = f'<div style="margin:0;padding:0;text-align:center;background:#000;"><img src="{img_filename}" alt="Panel {i+1}" style="max-width:100%;max-height:100%;"/></div>'
        book.add_item(chapter)
        spine.append(chapter)

        # Add TOC entry for first panel of each page
        page_match = re.match(r'page_(\d+)_panel_(\d+)', panel_file.stem)
        if page_match and page_match.group(2) == "00":
            page_num = int(page_match.group(1)) + 1
            toc.append(epub.Link(f"{page_id}.xhtml", f"Page {page_num}", page_id))

    book.toc = toc
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = spine

    # Set cover image manually (set_cover creates broken empty XHTML on some versions)
    if panel_files:
        cover_img = Image.open(panel_files[0])
        cover_img = resize_for_device(cover_img, max_width, max_height)
        buf = BytesIO()
        if cover_img.mode == "RGBA":
            cover_img = cover_img.convert("RGB")
        cover_img.save(buf, "JPEG", quality=92)

        cover_image = epub.EpubImage()
        cover_image.file_name = "cover.jpg"
        cover_image.media_type = "image/jpeg"
        cover_image.content = buf.getvalue()
        book.add_item(cover_image)
        book.add_metadata("http://www.idpf.org/2007/opf", "cover", "", {"content": "cover-img"})
        cover_image.id = "cover-img"

    epub.write_epub(str(output_path), book)
    print(f"Done. {len(panel_files)} panels → {output_path}")
    print(f"  Title: {title}")
    print(f"  Size: {output_path.stat().st_size / 1024 / 1024:.1f} MB")
    return output_path


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python src/build_epub.py <panels-directory> [--title \"Title\"] [--output file.epub]")
        sys.exit(1)

    panels_path = sys.argv[1]
    title = None
    output = None

    if "--title" in sys.argv:
        idx = sys.argv.index("--title")
        if idx + 1 < len(sys.argv):
            title = sys.argv[idx + 1]

    if "--output" in sys.argv:
        idx = sys.argv.index("--output")
        if idx + 1 < len(sys.argv):
            output = sys.argv[idx + 1]

    build_epub(panels_path, title=title, output_path=output)
