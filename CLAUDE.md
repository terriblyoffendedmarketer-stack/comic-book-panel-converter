# Comic Book Panel Converter

Converts comic book files (CBZ/CBR/CB7) into e-reader optimized formats: XTC for XTe Ink X4 (native format, zero decode overhead) and EPUB for Kindle. Also downloads manga from MangaDex, MangaPill, and 1manga.

## Status

**Phase:** Full web app with multi-source manga download, volume selection. Deployed at comic-converter.fly.dev.
**Current:** Three-tab web UI at `http://localhost:8080`:
- **Convert tab**: Drop files or pick from input/, select device(s), choose dithering algorithm, click Convert. Collapsible Advanced section with gamma, contrast, sharpening, denoise controls. Cancel button. Open input/output folder links.
- **Download tab**: Three sources (MangaDex, MangaPill, 1manga). Per-volume selection with Select All, custom chapter range picker. Cancel button. Download only (no auto-convert).
- **Preview tab**: View converted EPUBs/XTCs at exact device viewport. Arrow key navigation.
**Conversion modes:**
- **XTe Ink**: Overlapping thirds (xtcjs algorithm) with gutter snapping, landscape rotation, 3 dithering options (Floyd-Steinberg/Sierra Lite/Atkinson). Native C dithering via ctypes. Outputs XTC native format (1-bit packed, instant page turns on CrossPoint).
- **Kindle**: KCC for fixed-layout EPUB with virtual panel view.
**Defaults:** Floyd-Steinberg dithering, gamma 1.0, contrast Normal, sharpen Normal, denoise OFF, continuous overlap OFF, landscape flip OFF.
**Tested on:** Civil War collection (104 files), Amazing SpiderMan, Riddler, Sandman, Punpun, Chainsaw Man (MangaDex), Berserk.
**Known issue:** Downloads on Fly.io fill the 1GB volume and freeze the tool. Need auto-cleanup for download-only workflows (conversion path already auto-deletes).
**Next:**
1. Fix Fly.io download storage cleanup (BLOCKER for test corpus downloads)
2. Download remaining test corpus manga (A Silent Voice, Spy x Family, Vinland Saga, Blame!, Dragon Ball, others — see memory)
3. Contribute gutter snapping + spread detection to xtcjs as PRs (fork exists at terriblyoffendedmarketer-stack/xtcjs)
4. Settings analyzer (standalone tool to profile diverse manga and discover optimal presets)
5. Live preview, tool separation

## Roadmap

1. [x] Page extraction from CBZ/CBR/CB7 (natural sorting, ComicInfo.xml parsing)
2. [x] Panel detection — Kumiko + panel grouping (merge splits, group rows, full-bleed fallback)
3. [x] Reading order logic (LTR/RTL auto-detected from ComicInfo.xml)
4. [x] EPUB output — two paths: KCC for Kindle, overlapping thirds for XTe Ink
5. [x] CLI device selection (`--device kindle|xteink`)
6. [x] Cover image support (OPF metadata + cover.xhtml, never split)
7. [x] Web UI — Flask app with drag-drop upload, device checkboxes, progress, download links
8. [x] Overlapping thirds (xtcjs algorithm) — segments rotated to landscape, gutter-snapped
9. [x] E-ink optimization — Floyd-Steinberg dithering, autocontrast, sharpen
10. [x] MangaDex download — search, volume selection, auto-convert pipeline
11. [x] EPUB previewer — exact device viewport with page navigation
12. [x] Auto-start (launchd) — always available at localhost:8080
13. [x] PWA manifest — installable as app from browser
14. [x] Cloud deployment (Fly.io) — live at comic-converter.fly.dev
15. [x] Landscape-first mode — segments rotated 90° for landscape reading (xtcjs default)
16. [x] Continuous scroll mode — uniform overlap across page boundaries (no jarring breaks)
17. [x] Direct file upload to OPDS catalog — moved to separate Vercel tool
18. [x] XTC preview — decode and render XTG pages in Preview tab
19. [x] Native C dithering — ctypes-loaded .so for Floyd-Steinberg/Sierra Lite/Atkinson (83x faster)
20. [x] Pipeline decoupling — download and convert are independent operations
21. [x] Removed Device/OPDS tab — handled by separate Vercel tool
22. [x] Advanced controls — gamma, contrast, sharpening, denoise under collapsible Advanced section
23. [ ] Settings analyzer — standalone tool to profile diverse manga/comics and discover optimal presets
24. [ ] Live preview — real-time preview of conversion settings before full processing
25. [ ] Tool separation — 2 repos: converter with preview, downloader
26. [ ] PDF input support
27. [ ] Mihon chapter combining — merge downloaded chapter CBZs into volumes

## Overlapping Thirds — xtcjs Algorithm (xtc_pipeline.py)

Replicates the [xtcjs](https://github.com/varo6/xtcjs) `calculateOverlapSegments()` with gutter snapping:

1. **`calculate_overlap_segments(w, h)`** — xtcjs math: `scale = 800/w`, `segmentHeight = floor(480/scale)`, 3 overlapping segments (more only if overlap < 5%).
2. **`snap_segments_to_gutters()`** — Adjusts segment start positions to nearest panel gutter within 15% of segment height.
3. **`process_page()`** — Full pipeline: grayscale → denoise (optional) → content trim → contrast → gamma → rotate → resize → sharpen → dither. All params configurable via Advanced UI.
4. **Dithering** — Native C implementations via ctypes (`dither_native.c` → `.so`). Floyd-Steinberg (balanced), Sierra Lite (sharper), Atkinson (high contrast). Serpentine scanning, ±96 error clamping. Python fallback if .so missing.
5. Panel detection (`find_panel_rows`, `find_gutter_centers`) only used for snapping; skipped for manga.

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
- Panel detection parallelized via subprocesses (not threads — OpenCV holds GIL, fork deadlocks on macOS)
- Cloud mode auto-deletes source CBZs after conversion to avoid filling Fly.io volume (1 GB default)
- `cc` may be aliased to `claude` on dev machines — use `/usr/bin/gcc` explicitly when compiling dither_native.c
- dither_native.so is architecture-specific — excluded from git and Docker context, compiled during Docker build

## File Map

- `CLAUDE.md` — this file
- `src/web_app.py` — Flask web app: convert, download, preview (the primary interface)
- `src/xtc_pipeline.py` — XTe Ink conversion pipeline: overlapping thirds, preprocessing, native C dithering
- `src/dither_native.c` — C implementations of Floyd-Steinberg/Sierra Lite/Atkinson dithering (compiled to .so)
- `src/mangadex.py` — MangaDex API wrapper (search, volumes, download as CBZ)
- `src/mangapill.py` — MangaPill scraper (largest English library)
- `src/onemanga.py` — 1manga.co scraper (sequential CDN images)
- `src/convert.py` — CLI entry point, dual-path: `--device kindle|xteink`
- `src/extract.py` — extracts pages from CBZ/CBR/CB7, parses ComicInfo.xml
- `src/detect_panels.py` — panel detection + grouping
- `src/panel_worker.py` — subprocess worker for parallel panel detection (spawned by web_app.py)
- `src/kumiko/` — Kumiko library patched for OpenCV 5.0
- `src/build_epub.py` — view-per-page EPUB builder with viewport, cover, rotation (Kindle path)
- `src/build_xtc.py` — XTG/XTC format builder for XTe Ink (1-bit packed pages, native CrossPoint format)
- `src/templates/index.html` — web UI (tabs: Convert, Download, Preview)
- `src/static/` — PWA icons (icon-192.png, icon-512.png)
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
- `reference/xtcjs/` — xtcjs source reference (image.ts, dithering.ts, canvas.ts, converter.ts, README.md)

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
