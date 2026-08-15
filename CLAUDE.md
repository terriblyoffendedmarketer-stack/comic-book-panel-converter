# Comic Book Panel Converter

Converts comic book files (CBZ/CBR/CB7) into e-reader optimized EPUBs for Kindle and XTe Ink X4.

## Status

**Phase:** Web UI converter with panel-aware overlapping thirds for XTe Ink.
**Current:** Three conversion modes:
- **Web UI**: Drop files or pick from input/, select device(s), click Convert. Output to `output/XTe Ink/` and `output/Kindle/`.
- **XTe Ink**: Panel-aware overlapping thirds — splits pages into 2-3 overlapping horizontal strips, snapping split boundaries to panel gutters. E-ink optimized (grayscale, contrast, sharpen). Cover preserved unsplit.
- **Kindle**: KCC for fixed-layout EPUB with virtual panel view.
**Tested on:** Civil War (CBR/CBZ collection, 104 files), Amazing SpiderMan, Riddler, Sandman, Punpun.
**Next:** Mihon manga download automation, landscape-first mode.

## Roadmap

1. [x] Page extraction from CBZ/CBR/CB7 (natural sorting, ComicInfo.xml parsing)
2. [x] Panel detection — Kumiko + panel grouping (merge splits, group rows, full-bleed fallback)
3. [x] Reading order logic (LTR/RTL auto-detected from ComicInfo.xml)
4. [x] EPUB output — two paths: KCC for Kindle, overlapping thirds for XTe Ink
5. [x] CLI device selection (`--device kindle|xteink`)
6. [x] Preview tool (preview.py)
7. [x] Cover image support (OPF metadata + cover.xhtml, never split)
8. [x] Orientation analysis tool (scripts/analyze_orientation.py)
9. [x] Push to GitHub
10. [x] Web UI — Flask app with drag-drop upload, device checkboxes, progress, download links
11. [x] Panel-aware overlapping thirds — splits at gutters, not through panels
12. [x] E-ink dithering — grayscale, auto-contrast, sharpen for XTe Ink
13. [ ] Mihon automation — download manga volumes, combine chapters
14. [ ] Landscape-first mode — auto-detect dominant orientation
15. [ ] Manga long-portrait splitting — split tall narrow panels for landscape
16. [ ] PDF input support
17. [ ] Batch CLI conversion (process entire folder)

## Panel-Aware Overlapping Thirds (split_page.py)

The key improvement over naive thirds splitting — snaps boundaries to panel gutters:

1. **`find_panel_rows()`** — Groups detected panels into horizontal rows (>40% vertical overlap).
2. **`find_gutter_centers()`** — Finds y-coordinates of gutters between panel rows.
3. **`compute_split_points()`** — Calculates ideal split points (even distribution), then snaps each to the nearest gutter within 15% of page height.
4. **`determine_splits()`** — Full-bleed pages → 1 view. 2 panel rows → 2 strips. 3+ rows → 3 strips.
5. **`process_for_eink()`** — Grayscale, auto-contrast, sharpen, resize to 480x800, white-padded.

Result: overlapping views that never cut through a panel. Each view shares ~15% of content with its neighbors for reading continuity.

## Panel Grouping Algorithm (detect_panels.py)

Legacy panel-by-panel mode (still available via CLI):

1. **`merge_split_panels()`** — Merges narrow panels (<45% page width) that Kumiko incorrectly split vertically.
2. **`group_panels_into_views()`** — Groups narrow panels in same row into combined views.
3. **Full-bleed fallback** — Single panel >50% page area → show full page.

## Research Notes

### KCC (Kindle Comic Converter) — Kindle output
- Device profiles: KPW (Paperwhite), KCS (Colorsoft), KS (Scribe)
- Produces fixed-layout EPUB; virtual panel view is a Kindle firmware feature (Aa menu)
- Needs `7zz` binary → `brew install p7zip`, `ln -sf /opt/homebrew/bin/7z /opt/homebrew/bin/7zz`

### Kumiko — XTe Ink panel detection
- Sobel edge → threshold → contours → LSD split → merge → expand → fix numbering
- NOT pip-installable (`pip install kumiko` = wrong package, a Discord bot)
- **OpenCV 5.0 patch** in `src/kumiko/page.py` — LSD detect output format changed
- Bundled in `src/kumiko/` with the patch applied

### What doesn't work (don't retry)
- Threshold + contours on manga (gutters merge with white background)
- Morphological closing (kernel too large for 8-19px manga gutters)
- Projection-based splitting (horizontal only, misses vertical sub-panels)
- KCC's comic2panel.py (vertical-only, designed for webtoons)

## Pipeline Gotchas

- `brew install unrar` doesn't exist on macOS → use `brew install unar`, set `rarfile.UNRAR_TOOL = "unar"`
- `ebooklib book.set_cover()` is broken → manually create EpubImage + OPF metadata
- Debug images (`*_debug.jpg`, `*_grouped.jpg`) pollute panel glob → filter in process_directory()
- `ebooklib` strips viewport meta → post-process EPUB zip to inject
- Must use `rendition:layout pre-paginated` for Kindle fixed-layout
- KCC needs `7zz` binary → symlink from `7z` if using p7zip
- Flask web app reads PORT env var — use `Launch Converter.command` to start

## File Map

- `CLAUDE.md` — this file
- `src/web_app.py` — Flask web UI for upload, convert, download (the primary interface)
- `src/split_page.py` — panel-aware overlapping thirds splitter + e-ink optimization
- `src/convert.py` — CLI entry point, dual-path: `--device kindle` (KCC) or `--device xteink` (panels)
- `src/extract.py` — extracts pages from CBZ/CBR/CB7, parses ComicInfo.xml for manga auto-detection
- `src/detect_panels.py` — panel detection + grouping (merge splits, group rows, full-bleed fallback)
- `src/kumiko/` — Kumiko library patched for OpenCV 5.0
- `src/build_epub.py` — view-per-page EPUB builder with viewport, cover, landscape rotation
- `src/templates/index.html` — web UI template (drop zone, file list, device checkboxes)
- `src/preview.py` — HTML preview at exact device dimensions
- `scripts/analyze_orientation.py` — profiles comics by landscape vs portrait panel ratio
- `scripts/capture_kindle.py` — captures Kindle Mac app screenshots
- `commands/` — double-clickable .command files for non-terminal usage
- `commands/Launch Converter.command` — starts web UI in browser
- `input/` — comic files (not in git)
- `output/` — converted EPUBs organized by device (not in git)
- `requirements.txt` — Python dependencies (includes flask)

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

# Web UI (recommended — no terminal needed after this):
python src/web_app.py
# Or double-click: commands/Launch Converter.command

# CLI usage:
python src/convert.py input/comic.cbz --device kindle --title "My Comic"
python src/convert.py input/comic.cbz --device xteink --title "My Comic"

# Manga auto-detected from ComicInfo.xml. Override with --manga or --ltr.
```
