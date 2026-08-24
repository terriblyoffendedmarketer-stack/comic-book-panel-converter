# build_xtc.py — XTC/XTCH format builder for XTe Ink X4/X3
# Ports the XTG/XTH page encoders and XTC/XTCH containers from xtcjs.
# XTG = 1-bit packed grayscale page, XTH = 2-bit 4-level grayscale page.
# XTC = container of XTG pages, XTCH = container of XTH pages.
#
# Usage: called by web_app.py conversion pipeline
# Requires: Pillow, numpy
#
# Gotchas:
# - XTG packs 8 pixels per byte, MSB first. Pixel >= 128 = white (1), else black (0).
# - XTH uses column-major encoding with X-axis mirrored, two bit planes.
#   Levels: >=212→0, >=127→1, >=42→2, else→3. colBytes=ceil(h/8), planeSize=colBytes*w.
# - XTC header uses little-endian throughout, 64-bit offsets.
# - XTCH magic is 0x58 0x54 0x43 0x48 instead of XTC\0.
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


def image_to_xth(img):
    """Convert a PIL Image to XTH format (2-bit, 4-level grayscale).

    Column-major encoding with X-axis mirrored, two bit planes.
    Levels: >=212→0(white), >=127→1, >=42→2, <42→3(black).
    """
    if img.mode != 'L':
        img = img.convert('L')

    w, h = img.size
    pixels = np.array(img, dtype=np.uint8)

    levels = np.zeros_like(pixels, dtype=np.uint8)
    levels[pixels < 212] = 1
    levels[pixels < 127] = 2
    levels[pixels < 42] = 3

    col_bytes = (h + 7) // 8
    pad_h = col_bytes * 8 - h
    if pad_h > 0:
        levels = np.pad(levels, ((0, pad_h), (0, 0)), constant_values=0)

    bit0 = (levels & 1).astype(np.uint8)
    bit1 = ((levels >> 1) & 1).astype(np.uint8)

    mirrored_b0 = bit0[:, ::-1]
    mirrored_b1 = bit1[:, ::-1]

    plane0 = np.packbits(mirrored_b0, axis=0).T.tobytes()
    plane1 = np.packbits(mirrored_b1, axis=0).T.tobytes()

    pixel_data = plane0 + plane1
    digest = pixel_data[:8] if len(pixel_data) >= 8 else pixel_data + b'\x00' * (8 - len(pixel_data))

    header = bytearray(22)
    header[0:3] = b'XTH'
    header[3] = 0x00
    struct.pack_into('<H', header, 4, w)
    struct.pack_into('<H', header, 6, h)
    header[8] = 0
    header[9] = 0
    struct.pack_into('<I', header, 10, len(pixel_data))
    header[14:22] = digest[:8]

    return bytes(header) + pixel_data


def build_xtc(xtg_pages, title=None, author=None, is_2bit=False):
    """Build an XTC/XTCH file from a list of XTG/XTH page byte arrays.

    When is_2bit=True, uses XTCH magic (0x58 0x54 0x43 0x48) instead of XTC\\0.
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

    if is_2bit:
        buf[0:4] = b'XTCH'
    else:
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


def read_xtc_page(xtc_data, page_idx):
    """Read a single page from XTC/XTCH data and return a PIL Image.

    Detects XTG vs XTH pages by their magic and decodes accordingly.
    """
    page_count = struct.unpack_from('<H', xtc_data, 6)[0]
    if page_idx >= page_count:
        return None

    index_offset = struct.unpack_from('<Q', xtc_data, 24)[0]
    entry_off = index_offset + page_idx * 16

    page_offset = struct.unpack_from('<Q', xtc_data, entry_off)[0]
    page_size = struct.unpack_from('<I', xtc_data, entry_off + 8)[0]
    pg_w = struct.unpack_from('<H', xtc_data, entry_off + 12)[0]
    pg_h = struct.unpack_from('<H', xtc_data, entry_off + 14)[0]

    page_data = xtc_data[page_offset:page_offset + page_size]
    magic = page_data[0:3]
    pixel_data = page_data[22:]

    if magic == b'XTH':
        col_bytes = (pg_h + 7) // 8
        plane_size = col_bytes * pg_w
        plane0 = np.frombuffer(pixel_data[:plane_size], dtype=np.uint8)
        plane1 = np.frombuffer(pixel_data[plane_size:plane_size * 2], dtype=np.uint8)

        bits0 = np.unpackbits(plane0).reshape(pg_w, col_bytes * 8).T[:pg_h, ::-1]
        bits1 = np.unpackbits(plane1).reshape(pg_w, col_bytes * 8).T[:pg_h, ::-1]

        levels = bits0 | (bits1 << 1)
        lut = np.array([255, 170, 85, 0], dtype=np.uint8)
        img_array = lut[levels]

        return Image.fromarray(img_array, mode='L')
    else:
        row_bytes = (pg_w + 7) // 8
        bits = np.unpackbits(np.frombuffer(pixel_data, dtype=np.uint8))
        pixels = bits.reshape(-1, row_bytes * 8)[:pg_h, :pg_w]
        img_array = (pixels * 255).astype(np.uint8)
        return Image.fromarray(img_array, mode='L')


def read_xtc_page_count(xtc_data):
    """Return the number of pages in an XTC file."""
    return struct.unpack_from('<H', xtc_data, 6)[0]


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
