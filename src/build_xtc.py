# build_xtc.py — XTC format builder for XTe Ink X4/X3
# Ports the XTG page encoder and XTC container from xtcjs.
# XTG = 1-bit packed grayscale page, XTC = container of XTG pages.
#
# Usage: called by web_app.py conversion pipeline
# Requires: Pillow, numpy
#
# Gotchas:
# - XTG packs 8 pixels per byte, MSB first. Pixel >= 128 = white (1), else black (0).
# - XTC header uses little-endian throughout, 64-bit offsets.
# - Title field is 128 bytes, author 112 bytes — both null-terminated UTF-8.
# - CrossPoint reads XTC natively — no EPUB overhead, instant page turns.

import struct
import numpy as np
from PIL import Image
from pathlib import Path


def image_to_xtg(img):
    """Convert a PIL Image to XTG format (1-bit packed).

    Returns bytes containing the XTG page data with header.
    """
    if img.mode != 'L':
        img = img.convert('L')

    w, h = img.size
    pixels = np.array(img, dtype=np.uint8)

    bits = (pixels >= 128).astype(np.uint8)
    row_bytes = (w + 7) // 8
    pad = row_bytes * 8 - w
    if pad > 0:
        bits = np.pad(bits, ((0, 0), (0, pad)), constant_values=0)
    pixel_data = np.packbits(bits, axis=1).tobytes()

    digest = pixel_data[:8] if len(pixel_data) >= 8 else pixel_data + b'\x00' * (8 - len(pixel_data))

    header = bytearray(22)
    header[0:3] = b'XTG'
    header[3] = 0x00
    struct.pack_into('<H', header, 4, w)
    struct.pack_into('<H', header, 6, h)
    header[8] = 0
    header[9] = 0
    struct.pack_into('<I', header, 10, len(pixel_data))
    header[14:22] = digest[:8]

    return bytes(header) + pixel_data


def build_xtc(xtg_pages, title=None, author=None):
    """Build an XTC file from a list of XTG page byte arrays.

    Returns bytes containing the complete XTC file.
    """
    page_count = len(xtg_pages)
    has_metadata = bool(title or author)

    HEADER_BASE = 48
    TOC_OFFSET_PTR = 8
    INDEX_ENTRY = 16
    TITLE_SIZE = 128
    AUTHOR_SIZE = 112
    TOC_HEADER = 16

    if has_metadata:
        header_size = HEADER_BASE + TOC_OFFSET_PTR
        metadata_size = TITLE_SIZE + AUTHOR_SIZE + TOC_HEADER
        metadata_offset = header_size
        toc_entries_offset = header_size + TITLE_SIZE + AUTHOR_SIZE + TOC_HEADER
    else:
        header_size = HEADER_BASE
        metadata_size = 0
        metadata_offset = 0
        toc_entries_offset = 0

    index_offset = header_size + metadata_size
    data_offset = index_offset + page_count * INDEX_ENTRY

    total_size = data_offset + sum(len(p) for p in xtg_pages)
    buf = bytearray(total_size)

    # Magic: XTC\0
    buf[0:3] = b'XTC'
    buf[3] = 0x00
    struct.pack_into('<H', buf, 4, 1)           # version
    struct.pack_into('<H', buf, 6, page_count)

    # Flags
    if has_metadata:
        struct.pack_into('<I', buf, 8, 0x01000100)
        struct.pack_into('<I', buf, 12, 0x00000001)

    # Offsets (64-bit LE)
    struct.pack_into('<Q', buf, 16, metadata_offset)
    struct.pack_into('<Q', buf, 24, index_offset)
    struct.pack_into('<Q', buf, 32, data_offset)
    struct.pack_into('<Q', buf, 40, 0)  # reserved

    if has_metadata:
        struct.pack_into('<Q', buf, 48, toc_entries_offset)

    # Metadata
    if has_metadata:
        off = metadata_offset
        if title:
            title_bytes = title.encode('utf-8')[:TITLE_SIZE - 1]
            buf[off:off + len(title_bytes)] = title_bytes
        off += TITLE_SIZE

        if author:
            author_bytes = author.encode('utf-8')[:AUTHOR_SIZE - 1]
            buf[off:off + len(author_bytes)] = author_bytes
        off += AUTHOR_SIZE

        # TOC header (no chapters)
        struct.pack_into('<I', buf, off, 0)       # timestamp
        struct.pack_into('<H', buf, off + 4, 0)   # reserved
        struct.pack_into('<H', buf, off + 6, 0)   # chapter count

    # Index entries
    rel_offset = data_offset
    for i, xtg in enumerate(xtg_pages):
        entry_off = index_offset + i * INDEX_ENTRY
        pg_w = struct.unpack_from('<H', xtg, 4)[0] if len(xtg) >= 8 else 480
        pg_h = struct.unpack_from('<H', xtg, 6)[0] if len(xtg) >= 8 else 800

        struct.pack_into('<Q', buf, entry_off, rel_offset)
        struct.pack_into('<I', buf, entry_off + 8, len(xtg))
        struct.pack_into('<H', buf, entry_off + 12, pg_w)
        struct.pack_into('<H', buf, entry_off + 14, pg_h)

        rel_offset += len(xtg)

    # Page data
    write_off = data_offset
    for xtg in xtg_pages:
        buf[write_off:write_off + len(xtg)] = xtg
        write_off += len(xtg)

    return bytes(buf)


def convert_views_to_xtc(views_dir, title=None, output_path=None):
    """Convert a directory of view images to XTC format.

    Reads all JPEG/PNG files in sorted order, converts each to XTG,
    and builds the XTC container.
    """
    views_dir = Path(views_dir)
    view_files = sorted(views_dir.glob('*.jpg')) + sorted(views_dir.glob('*.png'))
    view_files.sort(key=lambda p: p.name)

    xtg_pages = []
    for vf in view_files:
        img = Image.open(vf)
        xtg_pages.append(image_to_xtg(img))

    xtc_data = build_xtc(xtg_pages, title=title)

    if output_path:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(xtc_data)
        return output_path

    return xtc_data
