# build_epub.py — Assembles cropped panels into an EPUB (one panel per page)
# Usage: python src/build_epub.py <panels-directory> [--title "Title"] [--output file.epub]
# Requires: ebooklib, Pillow
#
# Gotchas:
# - Must use EPUB3 rendition properties for Kindle fixed-layout support.
# - ebooklib strips <meta name="viewport"> from XHTML head — we post-process
#   the EPUB zip to inject viewport tags into each page.
# - ebooklib set_cover() is broken — manually create EpubImage + OPF metadata.
# - Landscape panels (width > height * 1.3) are rotated 90 CW for portrait
#   reading, with a small orientation arrow baked into the image.

import sys
import shutil
import tempfile
import zipfile
from pathlib import Path
from io import BytesIO
from PIL import Image, ImageDraw
from ebooklib import epub
import re


def natural_sort_key(s):
    return [int(c) if c.isdigit() else c.lower() for c in re.split(r'(\d+)', str(s))]


def resize_for_device(img, max_width=1236, max_height=1648):
    w, h = img.size
    ratio = min(max_width / w, max_height / h)
    if ratio < 1:
        return img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)
    return img


LANDSCAPE_THRESHOLD = 1.3


def is_landscape_panel(img):
    w, h = img.size
    return w > h * LANDSCAPE_THRESHOLD


def draw_orientation_arrow(img):
    """Draw a small arrow pointing RIGHT — toward the original top of the panel.
    After 90° CW rotation, the original top is on the right side.
    Placed in bottom-right corner to avoid obscuring speech bubbles."""
    w, h = img.size
    arrow_size = min(w, h) // 20
    margin = arrow_size
    cx = w - margin - arrow_size // 2
    cy = h - margin - arrow_size // 2

    draw = ImageDraw.Draw(img, 'RGBA')
    bg_r = arrow_size
    draw.ellipse(
        [cx - bg_r, cy - bg_r, cx + bg_r, cy + bg_r],
        fill=(0, 0, 0, 100)
    )
    draw.polygon([
        (cx + arrow_size // 2, cy),
        (cx - arrow_size // 2, cy - arrow_size // 3),
        (cx - arrow_size // 2, cy + arrow_size // 3)
    ], fill=(255, 255, 255, 180))
    return img


def prepare_panel_image(img, max_width, max_height):
    rotated = False
    if is_landscape_panel(img):
        img = img.rotate(-90, expand=True)
        if img.mode != 'RGBA':
            img = img.convert('RGBA')
        img = draw_orientation_arrow(img)
        rotated = True

    if img.mode == 'RGBA':
        background = Image.new('RGB', img.size, (0, 0, 0))
        background.paste(img, mask=img.split()[3])
        img = background

    img = resize_for_device(img, max_width, max_height)
    return img, rotated


def inject_viewports(epub_path, panel_viewports):
    """Post-process EPUB zip to inject viewport meta into each XHTML page's <head>."""
    tmp_path = epub_path + '.tmp'
    with zipfile.ZipFile(epub_path, 'r') as zin, zipfile.ZipFile(tmp_path, 'w') as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            basename = item.filename.split('/')[-1]
            if basename in panel_viewports:
                w, h = panel_viewports[basename]
                viewport_tag = f'<meta name="viewport" content="width={w}, height={h}"/>'
                content = data.decode('utf-8')
                content = content.replace('</title>', f'</title>\n    {viewport_tag}')
                data = content.encode('utf-8')
            zout.writestr(item, data)
    shutil.move(tmp_path, epub_path)


def build_epub(panels_dir, title=None, output_path=None, cover_image_path=None, manga=False, max_width=1236, max_height=1648):
    panels_dir = Path(panels_dir)

    if title is None:
        title = panels_dir.name.replace("_panels", "")

    if output_path is None:
        output_path = panels_dir.parent / f"{title}.epub"
    else:
        output_path = Path(output_path)

    panel_files = sorted(
        [f for f in panels_dir.iterdir()
         if f.suffix.lower() in {'.jpg', '.jpeg', '.png'} and '_debug' not in f.name],
        key=lambda f: natural_sort_key(f.name)
    )

    if not panel_files:
        print(f"Error: no images found in {panels_dir}")
        sys.exit(1)

    book = epub.EpubBook()
    book.set_identifier(f"comic-{title}")
    book.set_title(title)
    book.set_language("en")

    # EPUB3 fixed-layout metadata
    book.add_metadata(
        "http://www.idpf.org/2007/opf", "meta", "pre-paginated",
        {"property": "rendition:layout"}
    )
    book.add_metadata(
        "http://www.idpf.org/2007/opf", "meta", "none",
        {"property": "rendition:spread"}
    )
    book.add_metadata(
        "http://www.idpf.org/2007/opf", "meta", "auto",
        {"property": "rendition:orientation"}
    )

    if manga:
        book.set_direction("rtl")

    spine = ["nav"]
    toc = []
    rotated_count = 0
    panel_viewports = {}

    # Add cover image first
    cover_src = cover_image_path if cover_image_path else (panel_files[0] if panel_files else None)
    if cover_src:
        cover_img = Image.open(cover_src)
        cover_img = resize_for_device(cover_img, max_width, max_height)
        buf = BytesIO()
        if cover_img.mode == "RGBA":
            cover_img = cover_img.convert("RGB")
        cover_img.save(buf, "JPEG", quality=92)
        cover_w, cover_h = cover_img.size

        cover_epub = epub.EpubImage()
        cover_epub.file_name = "cover.jpg"
        cover_epub.media_type = "image/jpeg"
        cover_epub.content = buf.getvalue()
        cover_epub.id = "cover-img"
        book.add_item(cover_epub)
        book.add_metadata("http://www.idpf.org/2007/opf", "meta", "cover-img",
                          {"name": "cover", "content": "cover-img"})

        # Cover page XHTML
        cover_chapter = epub.EpubHtml(
            title="Cover",
            file_name="cover.xhtml",
            lang="en"
        )
        cover_chapter.content = (
            f'<div style="margin:0;padding:0;width:{cover_w}px;height:{cover_h}px;background:#000;">'
            f'<img src="cover.jpg" alt="Cover" style="width:{cover_w}px;height:{cover_h}px;"/>'
            f'</div>'
        )
        book.add_item(cover_chapter)
        spine.insert(1, cover_chapter)
        panel_viewports["cover.xhtml"] = (cover_w, cover_h)

    for i, panel_file in enumerate(panel_files):
        img = Image.open(panel_file)
        img, rotated = prepare_panel_image(img, max_width, max_height)
        if rotated:
            rotated_count += 1

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

        page_id = f"panel_{i:04d}"
        chapter = epub.EpubHtml(
            title=f"Panel {i+1}",
            file_name=f"{page_id}.xhtml",
            lang="en"
        )
        chapter.content = (
            f'<div style="margin:0;padding:0;width:{img_w}px;height:{img_h}px;background:#000;">'
            f'<img src="{img_filename}" alt="Panel {i+1}" '
            f'style="width:{img_w}px;height:{img_h}px;"/>'
            f'</div>'
        )
        book.add_item(chapter)
        spine.append(chapter)
        panel_viewports[f"{page_id}.xhtml"] = (img_w, img_h)

        page_match = re.match(r'page_(\d+)_(?:panel|view)_(\d+)', panel_file.stem)
        if page_match and page_match.group(2) == "00":
            page_num = int(page_match.group(1)) + 1
            toc.append(epub.Link(f"{page_id}.xhtml", f"Page {page_num}", page_id))

    book.toc = toc
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = spine

    epub.write_epub(str(output_path), book)

    # Post-process: inject viewport meta tags (ebooklib strips them)
    inject_viewports(str(output_path), panel_viewports)

    print(f"Done. {len(panel_files)} panels → {output_path}")
    print(f"  Title: {title}")
    print(f"  Cover: {'yes' if cover_src else 'no'}")
    print(f"  Rotated: {rotated_count} landscape panels")
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
