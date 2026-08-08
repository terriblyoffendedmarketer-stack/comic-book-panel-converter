# Comic Book Panel Converter

Converts comic book files (CBZ/CBR/CB7) into e-reader optimized EPUBs for Kindle and XTe Ink X4.

## Status

**Phase:** Panel grouping intelligence implemented, ready for device testing.
**Current:** Two output paths working:
- **Kindle**: Uses KCC (Kindle Comic Converter) for fixed-layout EPUB with virtual panel view, metadata, image compression, cover. Kindle's panel view (Aa menu) handles zooming.
- **XTe Ink**: Kumiko panel detection + grouping → view-per-page EPUB (480x800). Groups narrow panels in same row, merges incorrectly-split panels, full-page fallback for splash art. Landscape views rotated 90° CW with orientation arrow.
**Tested on:** Riddler Year One, Sandman, Punpun (manga), Civil War. Riddler page 7 grouping matches Kindle Guided View exactly.
**Next:** Landscape-first mode (auto-detect orientation), real device testing, batch conversion.

## Roadmap

1. [x] Page extraction from CBZ/CBR/CB7 (natural sorting, ComicInfo.xml parsing)
2. [x] Panel detection — Kumiko + panel grouping (merge splits, group rows, full-bleed fallback)
3. [x] Reading order logic (LTR/RTL auto-detected from ComicInfo.xml)
4. [x] EPUB output — two paths: KCC for Kindle, Kumiko+custom for XTe Ink
5. [x] CLI device selection (`--device kindle|xteink`)
6. [x] Preview tool (preview.py)
7. [x] Cover image support (OPF metadata + cover.xhtml)
8. [x] Orientation analysis tool (scripts/analyze_orientation.py)
9. [x] Push to GitHub
10. [ ] Landscape-first mode — auto-detect dominant orientation, build EPUB in landscape when >55% views are landscape
11. [ ] Manga long-portrait splitting — split tall narrow panels into top/bottom for landscape mode
12. [ ] PDF input support
13. [ ] Batch conversion (process entire folder of comics)
14. [ ] UI (after CLI proves the concept)
15. [ ] Mihon automation — batch downloads, combine chapters (Phase 2)

## Panel Grouping Algorithm (detect_panels.py)

The key intelligence that makes our output match Kindle Guided View:

1. **`merge_split_panels()`** — Kumiko sometimes splits one panel into two vertically-stacked pieces. Merges narrow panels (<45% page width) with matching x/width and gap <50px.
2. **`group_panels_into_views()`** — Groups panels sharing the same row (>40% vertical overlap) when 2+ are narrow (<45% page width). Crops the bounding box of the group, preserving gutters.
3. **Full-bleed fallback** — If only 1 panel detected and it covers >50% page area → show full page.

Example: Riddler page 7 has 2 landscape panels + 3 narrow verticals. Raw Kumiko: 6 panels (left vertical incorrectly split). After grouping: 3 views — each landscape alone, 3 verticals grouped. Matches Kindle Guided View exactly.

## Orientation Intelligence (Future)

Analysis via `scripts/analyze_orientation.py` on first 20 content pages:

| Book | Landscape% | Portrait% | Recommendation |
|------|-----------|-----------|----------------|
| Riddler Year One | 69% | 10% | LANDSCAPE |
| Sandman v01 | 30% | 24% | PORTRAIT |
| Punpun ch1 (manga) | 63% | 18% | LANDSCAPE |
| Civil War #1 | 65% | 16% | LANDSCAPE |

Key insight: even manga (Punpun) is landscape-dominant after grouping. The threshold of >55% landscape views reliably separates landscape-first books from portrait-first ones (only Sandman stays portrait).

**Not yet implemented** — current pipeline always uses portrait orientation with landscape rotation. Landscape-first mode would: display the EPUB in landscape (800x480), show landscape panels naturally, group portrait panels when small.

**Manhwa (vertical scroll)** — deliberately unsupported. Scroll-based format doesn't map to page-based EPUBs.

## Research Notes

### KCC (Kindle Comic Converter) — Kindle output
- Device profiles: KPW (Paperwhite), KCS (Colorsoft), KS (Scribe)
- Produces fixed-layout EPUB; virtual panel view is a Kindle firmware feature (Aa menu)
- Needs `7zz` binary → `brew install p7zip`, `ln -sf /opt/homebrew/bin/7z /opt/homebrew/bin/7zz`

### Kumiko — XTe Ink output
- Sobel edge → threshold → contours → LSD split → merge → expand → fix numbering
- NOT pip-installable (`pip install kumiko` = wrong package, a Discord bot)
- **OpenCV 5.0 patch** in `src/kumiko/page.py` — LSD detect output format changed
- Bundled in `src/kumiko/` with the patch applied

### What doesn't work (don't retry)
- Threshold + contours on manga (gutters merge with white background)
- Morphological closing (kernel too large for 8-19px manga gutters)
- Projection-based splitting (horizontal only, misses vertical sub-panels)
- KCC's comic2panel.py (vertical-only, designed for webtoons)
- Alternative tools investigated: Comic Panel Extractor, go-comic-converter, ComicPanelSplitter — none improve on Kumiko

### Kindle Guided View
- Publisher-authored in Kindle Create (GUI-only, not scriptable)
- NOT algorithmic — hand-crafted panel splits per page
- Our grouping algorithm replicates the logic: wide panels alone, narrow panels grouped
- Reference captures in `reference/kindle_guided_view/` (20 frames from Kindle Unlimited Riddler)

## Pipeline Gotchas

- `brew install unrar` doesn't exist on macOS → use `brew install unar`, set `rarfile.UNRAR_TOOL = "unar"`
- `ebooklib book.set_cover()` is broken → manually create EpubImage + OPF metadata
- Debug images (`*_debug.jpg`, `*_grouped.jpg`) pollute panel glob → filter in process_directory()
- Run convert.py from project root, not `src/` — output paths are relative
- Cleanup step can delete EPUBs if saved in intermediate directory
- `ebooklib` strips viewport meta → post-process EPUB zip to inject
- Must use `rendition:layout pre-paginated` for Kindle fixed-layout
- Kindle ignores per-page orientation → rotate landscape panels in image
- KCC needs `7zz` binary → symlink from `7z` if using p7zip

## File Map

- `CLAUDE.md` — this file
- `src/convert.py` — main entry point, dual-path: `--device kindle` (KCC) or `--device xteink` (Kumiko panels)
- `src/extract.py` — extracts pages from CBZ/CBR/CB7, parses ComicInfo.xml for manga auto-detection
- `src/detect_panels.py` — panel detection + grouping (merge splits, group rows, full-bleed fallback)
- `src/kumiko/` — Kumiko library patched for OpenCV 5.0 (page.py, panel.py, segment.py, debug.py, html.py)
- `src/build_epub.py` — view-per-page EPUB builder with viewport, cover, landscape rotation + arrow overlay
- `src/preview.py` — HTML preview at exact device dimensions
- `scripts/analyze_orientation.py` — profiles comics by landscape vs portrait panel ratio
- `scripts/capture_kindle.py` — captures Kindle Mac app screenshots via AppleScript + screencapture
- `reference/kindle_guided_view/` — 20 captured frames from Kindle Unlimited Riddler for comparison
- `input/` — comic files (not in git)
- `output/` — converted EPUBs (not in git)
- `requirements.txt` — Python dependencies

## Target Devices

| Device | Resolution | PPI | Screen | Reader App |
|--------|-----------|-----|--------|------------|
| Kindle Paperwhite Gen 7 | 1072x1448 | 300 | 6" | Kindle |
| XTe Ink X4 | 480x800 (portrait) | 220 | 4.3" | CrossPoint |

## Setup & Run

```bash
# Clone and setup
git clone https://github.com/terriblyoffendedmarketer-stack/comic-book-panel-converter.git
cd comic-book-panel-converter
python3 -m venv venv
source venv/bin/activate
pip3 install -r requirements.txt
brew install p7zip unar
ln -sf /opt/homebrew/bin/7z /opt/homebrew/bin/7zz

# Convert a comic — drop files in input/, get EPUBs from output/
# For Kindle (whole-page EPUB, use Kindle's built-in panel view):
python src/convert.py input/comic.cbz --device kindle --title "My Comic"

# For XTe Ink (panel-grouped EPUB with rotation):
python src/convert.py input/comic.cbz --device xteink --title "My Comic"

# Manga auto-detected from ComicInfo.xml. Override with --manga or --ltr.
# Use --keep to preserve intermediate panel images for inspection.

# Analyze orientation profile:
python scripts/analyze_orientation.py input/comic.cbz

# Preview panels at device size:
python src/preview.py output/comic_panels/ --device xteink
```
