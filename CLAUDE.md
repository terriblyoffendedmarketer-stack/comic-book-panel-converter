# Comic Book Panel Converter

Converts comic book files (CBZ/CBR/CB7/PDF) into panel-by-panel EPUBs optimized for small e-readers (Kindle, XTe Ink 4).

## Status

**Phase:** End-to-end pipeline working. Panel detection needs improvement.
**Current:** Full pipeline works: CBZ → panel detection → EPUB. Tested on Goodnight Punpun Ch.1 & Ch.2. Projection-based panel detection splits pages into horizontal rows well, but doesn't always catch vertical sub-panels within rows.
**Next:** Research existing panel detection libraries for better sub-panel detection. Test EPUBs on actual Kindle/XTe Ink to evaluate reading experience.

## Roadmap

1. [x] Project setup + CLAUDE.md
2. [x] Page extraction from CBZ/CBR/CB7
3. [~] Panel detection — projection-based works for rows, needs sub-panel splitting. RESEARCH existing solutions (Kumiko, etc.)
4. [x] Reading order logic (LTR for western, RTL for manga)
5. [ ] Confidence-based fallback (full page or quadrant split for irregular layouts)
6. [x] EPUB output generation (one panel per page, sized for e-reader)
6b. [x] Full pipeline script (convert.py — CBZ → panels → EPUB in one command)
7. [ ] PDF input support
8. [ ] CLI interface with flags (--manga, --device kindle/xte-ink, etc.)
9. [ ] UI (after CLI proves the concept)

## Design Decisions

- **No AI/ML for panel detection** — use traditional CV (gutter detection, edge detection, connected components). Deterministic and fast.
- **Confidence-based fallback** — if panel detection confidence is low, degrade gracefully (keep full page or split into quadrants) rather than guess wrong.
- **Reading order from spatial position** — group panels into rows by vertical position, sort rows top-to-bottom, sort within rows by horizontal position. Reverse horizontal for manga.
- **Output format: EPUB** — works on both Kindle (via Send-to-Kindle) and XTe Ink natively.
- **PDF is not harder than CBZ** — once you extract page images, the pipeline is identical.

## File Map

- `CLAUDE.md` — this file
- `src/extract.py` — extracts page images from CBZ/CBR/CB7 archives
- `src/detect_panels.py` — panel detection via projection-based gutter finding (WIP — needs sub-panel improvement)
- `src/build_epub.py` — assembles cropped panels into EPUB (one panel per page, Kindle-sized)
- `src/convert.py` — full pipeline: comic file → panels → EPUB (main entry point)
- `input/` — drop comic files here (currently has Goodnight Punpun Vol.1 ch1 & ch2)
- `output/` — extracted/converted output goes here

## Setup & Run

```bash
# Activate the virtual environment (already created)
cd "/Users/apple/Documents/Claude Code/Comic book converter"
source venv/bin/activate

# Dependencies already installed in venv. To reinstall:
pip install rarfile py7zr Pillow

# unar already installed via brew (for CBR support)

# Full pipeline: comic → panel-by-panel EPUB
python src/convert.py input/mycomic.cbz --manga --title "My Manga"

# Or step by step:
python src/extract.py input/mycomic.cbz
python src/detect_panels.py output/mycomic/ --manga
python src/build_epub.py output/mycomic_panels/ --title "My Manga"
```

## Tech Stack

- Python 3
- Pillow (image handling)
- rarfile + unar (CBR)
- py7zr (CB7)
- OpenCV (panel detection — upcoming)
- ebooklib (EPUB generation — upcoming)
