# analyze_orientation.py — Profiles comics by panel orientation distribution
# Usage: python scripts/analyze_orientation.py [comic1.cbr] [comic2.cbz] ...
#        python scripts/analyze_orientation.py --all  (analyzes everything in input/)
#
# Extracts first 20 content pages, runs panel detection + grouping,
# reports landscape vs portrait vs square breakdown per book.
# Helps decide whether a book should be treated as landscape-first or portrait-first.
#
# Gotchas:
# - Skips first 3 pages (typically covers/credits) to focus on actual content
# - Double-width pages (spreads) counted as full-page, not analyzed for orientation

import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))
from extract import extract
from detect_panels import detect_panels, group_panels_into_views
from PIL import Image


def analyze_book(comic_path, max_pages=20, skip_front=3):
    comic_path = Path(comic_path)
    name = comic_path.stem[:50]

    old_stdout = sys.stdout
    sys.stdout = open(os.devnull, 'w')
    try:
        pages_dir = extract(comic_path)
    finally:
        sys.stdout.close()
        sys.stdout = old_stdout

    skip = ('_debug', '_grouped')
    pages = sorted([p for p in pages_dir.glob('page_*.*')
                    if p.suffix.lower() in ('.jpg', '.png', '.jpeg')
                    and not any(s in p.name for s in skip)])

    content_pages = pages[skip_front:skip_front + max_pages]
    if not content_pages:
        content_pages = pages[:max_pages]

    landscape = portrait = square = full_page = spread = 0

    for page_path in content_pages:
        img = Image.open(page_path)
        pw, ph = img.size

        if pw > ph * 1.5:
            spread += 1
            continue

        raw = detect_panels(str(page_path))
        views = group_panels_into_views(raw, pw, ph)

        for v in views:
            x, y, w, h = v
            is_full = (x == 0 and y == 0 and w == pw and h == ph)
            if is_full:
                full_page += 1
            elif w > h * 1.3:
                landscape += 1
            elif h > w * 1.3:
                portrait += 1
            else:
                square += 1

    total = landscape + portrait + square + full_page
    if total == 0:
        return None

    result = {
        'name': name,
        'pages_analyzed': len(content_pages),
        'spreads_skipped': spread,
        'total_views': total,
        'landscape': landscape,
        'portrait': portrait,
        'square': square,
        'full_page': full_page,
        'landscape_pct': round(landscape * 100 / total),
        'portrait_pct': round(portrait * 100 / total),
        'recommendation': 'LANDSCAPE' if landscape > total * 0.55 else 'PORTRAIT',
    }
    return result


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/analyze_orientation.py [--all | comic1.cbr ...]")
        sys.exit(1)

    if '--all' in sys.argv:
        input_dir = Path('input')
        comics = sorted(input_dir.glob('*.cb?'))
    else:
        comics = [Path(a) for a in sys.argv[1:] if not a.startswith('-')]

    results = []
    for comic in comics:
        try:
            print(f"Analyzing: {comic.name[:60]}...", end='', flush=True)
            r = analyze_book(comic)
            if r:
                results.append(r)
                print(f" {r['recommendation']} (L:{r['landscape_pct']}% P:{r['portrait_pct']}%)")
            else:
                print(" (no panels found)")
        except Exception as e:
            print(f" ERROR: {e}")

    if results:
        print(f"\n{'='*70}")
        print(f"{'Book':<40} {'Views':>5} {'Land%':>5} {'Port%':>5} {'Rec':<10}")
        print(f"{'-'*40} {'-'*5} {'-'*5} {'-'*5} {'-'*10}")
        for r in results:
            print(f"{r['name'][:40]:<40} {r['total_views']:>5} {r['landscape_pct']:>4}% {r['portrait_pct']:>4}% {r['recommendation']:<10}")


if __name__ == '__main__':
    main()
