# Comic Book Panel Converter

Converts comic book files (CBZ/CBR/CB7) into e-reader optimized EPUBs for Kindle and XTe Ink X4. Also downloads manga from MangaDex.

## Status

**Phase:** Full web app with MangaDex integration, EPUB previewer, and auto-start.
**Current:** Three-tab web UI at `http://localhost:8080`:
- **Convert tab**: Drop files or pick from input/, select device(s), click Convert. Output to `output/XTe Ink/` and `output/Kindle/`.
- **MangaDex tab**: Search manga, select volumes, download as CBZ to input/. Optional auto-convert after download.
- **Preview tab**: View converted EPUBs at exact device viewport (480x800 XTe Ink or 1072x1448 Kindle). Arrow key navigation.
**Conversion modes:**
- **XTe Ink**: Panel-aware overlapping thirds — splits pages into 2-3 overlapping strips snapped to gutters. E-ink optimized.
- **Kindle**: KCC for fixed-layout EPUB with virtual panel view.
**Tested on:** Civil War collection (104 files), Amazing SpiderMan, Riddler, Sandman, Punpun, Chainsaw Man (MangaDex).
**Next:** Cloud deployment (Railway/Fly.io), landscape-first mode.

## Roadmap

1. [x] Page extraction from CBZ/CBR/CB7 (natural sorting, ComicInfo.xml parsing)
2. [x] Panel detection — Kumiko + panel grouping (merge splits, group rows, full-bleed fallback)
3. [x] Reading order logic (LTR/RTL auto-detected from ComicInfo.xml)
4. [x] EPUB output — two paths: KCC for Kindle, overlapping thirds for XTe Ink
5. [x] CLI device selection (`--device kindle|xteink`)
6. [x] Cover image support (OPF metadata + cover.xhtml, never split)
7. [x] Web UI — Flask app with drag-drop upload, device checkboxes, progress, download links
8. [x] Panel-aware overlapping thirds — splits at gutters, not through panels
9. [x] E-ink dithering — grayscale, auto-contrast, sharpen for XTe Ink
10. [x] MangaDex download — search, volume selection, auto-convert pipeline
11. [x] EPUB previewer — exact device viewport with page navigation
12. [x] Auto-start (launchd) — always available at localhost:8080
13. [x] PWA manifest — installable as app from browser
14. [~] Cloud deployment (Fly.io) — Dockerfile + fly.toml ready, needs `fly deploy`
15. [ ] Landscape-first mode — auto-detect dominant orientation
16. [ ] PDF input support
17. [ ] Mihon chapter combining — merge downloaded chapter CBZs into volumes

## Panel-Aware Overlapping Thirds (split_page.py)

Snaps split boundaries to panel gutters — never cuts through artwork:

1. **`find_panel_rows()`** — Groups detected panels into horizontal rows (>40% vertical overlap).
2. **`find_gutter_centers()`** — Finds y-coordinates of gutters between panel rows.
3. **`compute_split_points()`** — Calculates ideal split points, snaps each to nearest gutter within 15% of page height.
4. **`determine_splits()`** — Full-bleed → 1 view. 2 rows → 2 strips. 3+ rows → 3 strips.
5. **`process_for_eink()`** — Grayscale, auto-contrast, sharpen, resize to 480x800, white-padded.

## Manga Sources

Three download sources available via the Download tab:

### MangaDex (mangadex.py)
- Direct API v5 integration, best for fan translations
- Limited English library — licensed manga gets DMCA'd
- Rate-limited (0.15s between page downloads)

### MangaPill (mangapill.py)
- HTML scraping, no Cloudflare protection
- Largest English manga library (Punpun, Baccano, etc.)
- Images on cdn.readdetectiveconan.com

### 1manga (onemanga.py)
- HTML scraping with sequential CDN image URLs
- Has volume info in chapter listings
- Images on imgx.mghcdn.com (needs Referer header)

## Research Notes

### KCC (Kindle Comic Converter) — Kindle output
- Device profiles: KPW (Paperwhite), KCS (Colorsoft), KS (Scribe)
- Produces fixed-layout EPUB; virtual panel view is a Kindle firmware feature
- Needs `7zz` binary → `brew install p7zip`, `ln -sf /opt/homebrew/bin/7z /opt/homebrew/bin/7zz`

### Kumiko — XTe Ink panel detection
- Sobel edge → threshold → contours → LSD split → merge → expand → fix numbering
- NOT pip-installable (`pip install kumiko` = wrong package)
- **OpenCV 5.0 patch** in `src/kumiko/page.py`
- Bundled in `src/kumiko/`

### What doesn't work (don't retry)
- Threshold + contours on manga (gutters merge with white background)
- KCC's comic2panel.py (vertical-only, designed for webtoons)

## Pipeline Gotchas

- `brew install unrar` doesn't exist on macOS → use `brew install unar`
- `ebooklib book.set_cover()` is broken → manually create EpubImage + OPF metadata
- `ebooklib` strips viewport meta → post-process EPUB zip to inject
- Port 5000 conflicts with macOS AirPlay Receiver → uses port 8080
- KCC needs `7zz` binary → symlink from `7z` if using p7zip
- MangaDex rate limit is 5 req/sec — downloads sleep 0.15s between pages

## File Map

- `CLAUDE.md` — this file
- `src/web_app.py` — Flask web app: convert, MangaDex download, EPUB preview (the primary interface)
- `src/mangadex.py` — MangaDex API wrapper (search, volumes, download as CBZ)
- `src/mangapill.py` — MangaPill scraper (largest English library)
- `src/onemanga.py` — 1manga.co scraper (sequential CDN images)
- `src/split_page.py` — panel-aware overlapping thirds splitter + e-ink optimization
- `src/convert.py` — CLI entry point, dual-path: `--device kindle|xteink`
- `src/extract.py` — extracts pages from CBZ/CBR/CB7, parses ComicInfo.xml
- `src/detect_panels.py` — panel detection + grouping
- `src/kumiko/` — Kumiko library patched for OpenCV 5.0
- `src/build_epub.py` — view-per-page EPUB builder with viewport, cover, rotation
- `src/templates/index.html` — web UI (tabs: Convert, MangaDex, Preview)
- `src/static/` — PWA icons (icon-192.png, icon-512.png)
- `src/preview.py` — legacy HTML preview at device dimensions
- `scripts/analyze_orientation.py` — profiles comics by landscape vs portrait ratio
- `commands/Launch Converter.command` — starts web UI in browser
- `commands/Install Auto-Start.command` — sets up launchd for always-on at localhost:8080
- `commands/Uninstall Auto-Start.command` — removes launchd service
- `input/` — comic files and MangaDex downloads (not in git)
- `output/` — converted EPUBs organized by device (not in git)
- `logs/` — web app logs when running via launchd (not in git)
- `requirements.txt` — Python dependencies
- `Dockerfile` — production container with all system deps
- `fly.toml` — Fly.io deployment config with health check and volume mount
- `Procfile` — gunicorn process definition
- `wsgi.py` — WSGI entry point for gunicorn
- `.dockerignore` — excludes venv, input, output from builds

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

# Web UI (recommended):
python src/web_app.py
# Then open http://localhost:8080

# Or double-click: commands/Launch Converter.command
# Or install auto-start: double-click commands/Install Auto-Start.command
#   → always available at http://localhost:8080, starts on login

# CLI usage:
python src/convert.py input/comic.cbz --device kindle --title "My Comic"
python src/convert.py input/comic.cbz --device xteink --title "My Comic"

# Deploy to Fly.io:
# 1. Install: brew install flyctl
# 2. Login: fly auth login
# 3. Launch: fly launch (uses fly.toml + Dockerfile)
# 4. Create volume: fly volumes create data --size 1 --region sjc
# 5. Deploy: fly deploy
# Your app gets a public URL like https://comic-converter.fly.dev
```
