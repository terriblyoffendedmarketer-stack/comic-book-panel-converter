# web_app.py — Web UI for comic book conversion + MangaDex download
# Usage: python src/web_app.py (then open http://localhost:8080)
# Requires: flask, requests, plus all pipeline dependencies
#
# Gotchas:
# - Must run from project root (paths are relative to it).
# - Large files (100+ MB) are fine — Flask handles chunked uploads.
# - Conversion runs in a background thread; frontend polls /status.
# - KCC for Kindle modifies sys.argv — wrapped to restore it.
# - Port 5000 conflicts with macOS AirPlay Receiver — uses 8080.
# - MangaDex rate limit is 5 req/sec — downloads sleep between pages.
# - For cloud deploy: set DATA_DIR env var to persistent volume path.
# - HOST defaults to 0.0.0.0 when RAILWAY_ENVIRONMENT or FLY_APP_NAME is set.

import os
import sys
import json
import uuid
import shutil
import threading
import subprocess
import math
from pathlib import Path

from flask import Flask, render_template, request, jsonify, send_from_directory

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / 'src'))

from extract import extract, detect_reading_direction
from detect_panels import detect_panels
from xtc_pipeline import (get_segments, process_page, process_cover,
                          calculate_continuous_segments)
from build_epub import build_epub
from build_xtc import image_to_xtg, build_xtc
from mangadex import search_manga, get_volumes, download_volume_as_cbz
from mangapill import search_manga as mp_search, get_volumes as mp_volumes, download_volume_as_cbz as mp_download
from onemanga import search_manga as om_search, get_volumes as om_volumes, download_volume_as_cbz as om_download
from PIL import Image
import re

CLOUD = bool(os.environ.get('RAILWAY_ENVIRONMENT') or os.environ.get('FLY_APP_NAME'))


def natural_sort_key(s):
    return [int(c) if c.isdigit() else c.lower() for c in re.split(r'(\d+)', str(s))]


app = Flask(__name__,
            template_folder=str(ROOT / 'src' / 'templates'),
            static_folder=str(ROOT / 'src' / 'static'))
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024  # 500 MB

DATA_DIR = Path(os.environ.get('DATA_DIR', str(ROOT)))
INPUT_DIR = DATA_DIR / 'input'
OUTPUT_DIR = DATA_DIR / 'output'
INPUT_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

jobs = {}

DEVICE_PROFILES = {
    'xteink': {
        'name': 'XTe Ink X4',
        'width': 480,
        'height': 800,
        'folder': 'XTe Ink',
    },
    'kindle': {
        'name': 'Kindle Paperwhite',
        'kcc_profile': 'KPW',
        'width': 1072,
        'height': 1448,
        'folder': 'Kindle',
    },
}


NUM_WORKERS = max(1, min(6, os.cpu_count() - 2)) if os.cpu_count() else 4
PANEL_WORKER = str(ROOT / 'src' / 'panel_worker.py')


def detect_panels_parallel(pages, manga):
    """Detect panels for all pages using subprocesses (or in-process if single worker)."""
    if len(pages) <= 2 or NUM_WORKERS <= 1:
        return {str(p): detect_panels(p, manga=manga) for p in pages}

    batch_size = math.ceil(len(pages) / NUM_WORKERS)
    batches = [pages[i:i + batch_size] for i in range(0, len(pages), batch_size)]

    procs = []
    for batch in batches:
        proc = subprocess.Popen(
            [sys.executable, PANEL_WORKER],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            cwd=str(ROOT),
        )
        payload = json.dumps({'pages': [str(p) for p in batch], 'manga': manga})
        proc.stdin.write(payload.encode())
        proc.stdin.close()
        procs.append(proc)

    all_panels = {}
    for proc in procs:
        stdout, _ = proc.communicate(timeout=300)
        if proc.returncode == 0 and stdout:
            result = json.loads(stdout)
            for path, panels in result.items():
                all_panels[path] = [tuple(p) for p in panels]

    return all_panels


def convert_xteink_thirds(comic_path, manga, title, progress, is_cancelled=None, continuous=False, rotate_cw=False, dither_algo='floyd'):
    """Convert for XTe Ink using overlapping thirds + XTC native format."""
    device = DEVICE_PROFILES['xteink']
    tw, th = device['width'], device['height']
    out_dir = OUTPUT_DIR / device['folder']
    out_dir.mkdir(parents=True, exist_ok=True)

    progress("Extracting pages...")
    pages_dir = extract(comic_path, output_base=OUTPUT_DIR)

    try:
        skip = ("_debug", "_grouped")
        pages = sorted(
            [p for p in pages_dir.iterdir()
             if p.suffix.lower() in {'.jpg', '.jpeg', '.png'} and not any(s in p.name for s in skip)],
            key=lambda f: natural_sort_key(f.name)
        )

        if not pages:
            raise ValueError(f"No pages found in {pages_dir}")

        total_pages = len(pages)
        xtg_pages = []

        cover_img = Image.open(pages[0])
        cover = process_cover(cover_img, dither_algo=dither_algo, target_w=tw, target_h=th)
        xtg_pages.append(image_to_xtg(cover))

        content_pages = pages[1:]

        if continuous and content_pages:
            progress("Loading pages for continuous layout...")
            page_images = []
            for p in content_pages:
                if is_cancelled and is_cancelled():
                    return None
                page_images.append(Image.open(p))

            dims = [(img.width, img.height) for img in page_images]
            segments = calculate_continuous_segments(dims)
            progress(f"Generating {len(segments)} continuous segments...")

            for si, seg in enumerate(segments):
                if is_cancelled and is_cancelled():
                    return None
                if si % 50 == 0:
                    progress(f"Processing segment {si + 1} of {len(segments)}...")

                if seg[0] == 'landscape':
                    img = page_images[seg[1]]
                elif len(seg) == 3:
                    pi, y, h = seg
                    img = page_images[pi].crop((0, y, page_images[pi].width, y + h))
                else:
                    pi, y, h1, pi2, h2 = seg
                    img1 = page_images[pi]
                    img2 = page_images[pi2]
                    w = img1.width
                    composite = Image.new('L' if img1.mode == 'L' else 'RGB', (w, h1 + h2))
                    composite.paste(img1.crop((0, y, w, y + h1)), (0, 0))
                    composite.paste(img2.crop((0, 0, w, h2)), (0, h1))
                    img = composite

                processed = process_page(img, rotate_cw=rotate_cw, dither_algo=dither_algo, target_w=tw, target_h=th)
                xtg_pages.append(image_to_xtg(processed))
        else:
            skip_detection = manga or total_pages > 100
            panel_cache = {}
            if not skip_detection:
                progress(f"Detecting panels ({total_pages} pages, {NUM_WORKERS} workers)...")
                panel_cache = detect_panels_parallel(content_pages, manga)

            for page_idx, page_path in enumerate(content_pages):
                if is_cancelled and is_cancelled():
                    return None

                progress(f"Processing page {page_idx + 2} of {total_pages}...")
                img = Image.open(page_path)

                panels = [] if skip_detection else panel_cache.get(str(page_path), detect_panels(page_path, manga=manga))
                regions = get_segments(img.width, img.height, panels)

                for rx, ry, rw, rh in regions:
                    crop = img.crop((rx, ry, rx + rw, ry + rh))
                    processed = process_page(crop, rotate_cw=rotate_cw, dither_algo=dither_algo, target_w=tw, target_h=th)
                    xtg_pages.append(image_to_xtg(processed))

        progress("Building XTC...")
        xtc_path = out_dir / f"{title}.xtc"
        xtc_data = build_xtc(xtg_pages, title=title)
        xtc_path.write_bytes(xtc_data)

        return str(xtc_path)
    finally:
        shutil.rmtree(pages_dir, ignore_errors=True)


def convert_kindle(comic_path, manga, title, progress):
    """Convert for Kindle using KCC."""
    device = DEVICE_PROFILES['kindle']
    out_dir = OUTPUT_DIR / device['folder']
    out_dir.mkdir(parents=True, exist_ok=True)

    progress("Converting with KCC for Kindle...")
    try:
        from kindlecomicconverter.comic2ebook import main as kcc_main

        args = [
            '-p', device['kcc_profile'],
            '-f', 'EPUB',
            '--forcecolor',
            '-c', '1',
            '-o', str(out_dir),
        ]
        if title:
            args.extend(['-t', title])
        if manga:
            args.append('-m')
        args.append(str(comic_path))

        old_argv = sys.argv
        sys.argv = ['kcc-c2e'] + args
        try:
            kcc_main(args)
        finally:
            sys.argv = old_argv

        epubs = list(out_dir.glob("*.epub"))
        if epubs:
            return str(epubs[-1])
        return None
    except Exception as e:
        progress(f"KCC error: {e}")
        return None


def run_conversion(job_id, filepath, devices, continuous=False, rotate_cw=False, dither_algo='floyd'):
    """Run conversion in background thread."""
    job = jobs[job_id]

    def progress(msg):
        job['messages'].append(msg)

    def is_cancelled():
        return job.get('cancelled', False)

    try:
        comic_path = Path(filepath)
        title = comic_path.stem

        direction, reason = detect_reading_direction(comic_path)
        manga = (direction == 'rtl')
        progress(f"Detected: {'Manga (RTL)' if manga else 'Western (LTR)'} — {reason}")

        results = []

        if is_cancelled():
            return

        if 'xteink' in devices:
            path = convert_xteink_thirds(comic_path, manga, title, progress, is_cancelled, continuous=continuous, rotate_cw=rotate_cw, dither_algo=dither_algo)
            if is_cancelled():
                return
            if path:
                results.append({
                    'device': 'XTe Ink X4',
                    'filename': Path(path).name,
                    'folder': 'XTe Ink',
                    'path': path,
                })

        if is_cancelled():
            return

        if 'kindle' in devices:
            path = convert_kindle(comic_path, manga, title, progress)
            if path:
                results.append({
                    'device': 'Kindle Paperwhite',
                    'filename': Path(path).name,
                    'folder': 'Kindle',
                    'path': path,
                })

        job['results'] = results
        job['status'] = 'done'
        progress("Done!")

    except Exception as e:
        if not is_cancelled():
            job['status'] = 'error'
            job['error'] = str(e)
            progress(f"Error: {e}")


def run_mangadex_download(job_id, manga_id, manga_title, volume_nums):
    """Download manga volumes from MangaDex in background thread."""
    job = jobs[job_id]

    def progress(msg):
        job['messages'].append(msg)

    def is_cancelled():
        return job.get('cancelled', False)

    try:
        progress(f"Fetching volume data for {manga_title}...")
        all_volumes = get_volumes(manga_id)

        downloaded_files = []
        for vol_num in volume_nums:
            if is_cancelled():
                return

            if vol_num not in all_volumes:
                progress(f"Volume {vol_num} not found, skipping...")
                continue

            vol_data = all_volumes[vol_num]
            cbz_path = download_volume_as_cbz(
                manga_id, manga_title, vol_num,
                vol_data["chapters"], INPUT_DIR, progress
            )
            downloaded_files.append(cbz_path)
            Path(cbz_path).with_suffix('.manga').touch()
            log_download(cbz_path.name)

        job['results'] = [{'device': 'Downloaded', 'filename': p.name, 'folder': '_input', 'path': str(p)} for p in downloaded_files]
        job['status'] = 'done'
        progress("Done!")

    except Exception as e:
        job['status'] = 'error'
        job['error'] = str(e)
        progress(f"Error: {e}")


@app.route('/')
def index():
    return render_template('index.html', cloud=CLOUD)


@app.route('/health')
def health():
    return jsonify({'status': 'ok'})


@app.route('/manifest.json')
def manifest():
    return jsonify({
        "name": "Comic Book Converter",
        "short_name": "ComicConv",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#1a1a1a",
        "theme_color": "#4a90d9",
        "icons": [
            {"src": "/static/icon-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "/static/icon-512.png", "sizes": "512x512", "type": "image/png"},
        ]
    })


DOWNLOADS_LOG = DATA_DIR / '.downloaded'


def log_download(filename):
    """Track files downloaded by this tool."""
    DOWNLOADS_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(DOWNLOADS_LOG, 'a') as f:
        f.write(filename + '\n')


def get_downloaded_files():
    """Get set of filenames downloaded by this tool."""
    if not DOWNLOADS_LOG.exists():
        return set()
    return set(DOWNLOADS_LOG.read_text().strip().splitlines())


@app.route('/files')
def list_files():
    """List comic files in input/ folder."""
    extensions = {'.cbz', '.cbr', '.cb7'}
    downloaded = get_downloaded_files()
    files = []
    if INPUT_DIR.exists():
        for f in sorted(INPUT_DIR.iterdir(), key=lambda x: x.name.lower()):
            if f.suffix.lower() in extensions and f.stat().st_size > 0:
                size_mb = f.stat().st_size / (1024 * 1024)
                files.append({
                    'name': f.name,
                    'size': f"{size_mb:.1f} MB",
                    'downloaded': f.name in downloaded,
                })
    return jsonify(files)


@app.route('/upload', methods=['POST'])
def upload():
    """Upload comic file(s) to input/."""
    uploaded = []
    for f in request.files.getlist('files'):
        if f.filename:
            safe_name = Path(f.filename).name
            dest = INPUT_DIR / safe_name
            f.save(str(dest))
            size_mb = dest.stat().st_size / (1024 * 1024)
            uploaded.append({'name': safe_name, 'size': f"{size_mb:.1f} MB"})
    return jsonify(uploaded)


@app.route('/convert', methods=['POST'])
def start_convert():
    """Start conversion job."""
    data = request.json
    filename = data.get('filename')
    devices = data.get('devices', ['xteink'])
    continuous = data.get('continuous', False)
    rotate_cw = data.get('rotate_cw', False)
    dither_algo = data.get('dither', 'floyd')

    if not filename:
        return jsonify({'error': 'No file specified'}), 400
    if not devices:
        return jsonify({'error': 'No output format selected'}), 400

    filepath = INPUT_DIR / filename
    if not filepath.exists():
        return jsonify({'error': f'File not found: {filename}'}), 404

    if CLOUD:
        free_mb = shutil.disk_usage(str(DATA_DIR)).free / (1024 * 1024)
        file_mb = filepath.stat().st_size / (1024 * 1024)
        if free_mb < file_mb * 2:
            return jsonify({'error': f'Not enough disk space ({free_mb:.0f} MB free, need ~{file_mb*2:.0f} MB). Delete some files first.'}), 400

    job_id = str(uuid.uuid4())[:8]
    jobs[job_id] = {
        'status': 'processing',
        'messages': [],
        'results': [],
        'filename': filename,
    }

    thread = threading.Thread(target=run_conversion, args=(job_id, filepath, devices, continuous, rotate_cw, dither_algo))
    thread.daemon = True
    thread.start()

    return jsonify({'job_id': job_id})


@app.route('/status/<job_id>')
def get_status(job_id):
    """Poll conversion status."""
    job = jobs.get(job_id)
    if not job:
        return jsonify({'status': 'not_found'}), 404
    return jsonify(job)


@app.route('/cancel/<job_id>', methods=['POST'])
def cancel_job(job_id):
    """Cancel a running job."""
    job = jobs.get(job_id)
    if not job:
        return jsonify({'error': 'Job not found'}), 404
    job['cancelled'] = True
    job['status'] = 'done'
    job['messages'].append('Cancelled by user.')
    return jsonify({'ok': True})


@app.route('/output/<path:filepath>')
def download_file(filepath):
    """Serve converted files."""
    return send_from_directory(str(OUTPUT_DIR), filepath, as_attachment=True)


@app.route('/input/<path:filepath>')
def download_input_file(filepath):
    """Serve files from input/ (for downloading CBZs to local machine)."""
    return send_from_directory(str(INPUT_DIR), filepath, as_attachment=True)


@app.route('/open-folder/<folder>')
def open_folder(folder):
    """Open input or output folder in Finder (local only)."""
    if CLOUD:
        return jsonify({'error': 'Not available in cloud mode'}), 400
    import subprocess
    target = INPUT_DIR if folder == 'input' else OUTPUT_DIR
    subprocess.Popen(['open', str(target)])
    return jsonify({'ok': True})


@app.route('/cleanup/<path:filepath>', methods=['POST'])
def cleanup_file(filepath):
    """Delete a file from output after user has downloaded it."""
    target = OUTPUT_DIR / filepath
    if not target.exists():
        return jsonify({'ok': True})
    try:
        target.unlink()
        return jsonify({'ok': True})
    except OSError as e:
        return jsonify({'error': str(e)}), 500


@app.route('/cleanup-input/<path:filepath>', methods=['POST'])
def cleanup_input_file(filepath):
    """Delete a file from input and its associated output files."""
    target = INPUT_DIR / filepath
    if target.exists():
        try:
            target.unlink()
            target.with_suffix('.manga').unlink(missing_ok=True)
        except OSError as e:
            return jsonify({'error': str(e)}), 500
    stem = Path(filepath).stem
    for d in OUTPUT_DIR.iterdir() if OUTPUT_DIR.exists() else []:
        if d.is_dir() and stem in d.name:
            shutil.rmtree(d, ignore_errors=True)
        elif d.is_file() and stem in d.name:
            d.unlink(missing_ok=True)
    return jsonify({'ok': True})


@app.route('/disk-usage')
def disk_usage():
    """Report disk usage for input and output directories."""
    def dir_size(path):
        total = 0
        if path.exists():
            for f in path.rglob('*'):
                if f.is_file():
                    total += f.stat().st_size
        return total

    input_size = dir_size(INPUT_DIR)
    output_size = dir_size(OUTPUT_DIR)
    total = shutil.disk_usage(str(DATA_DIR))

    return jsonify({
        'input_mb': round(input_size / (1024 * 1024), 1),
        'output_mb': round(output_size / (1024 * 1024), 1),
        'disk_total_mb': round(total.total / (1024 * 1024), 1),
        'disk_used_mb': round(total.used / (1024 * 1024), 1),
        'disk_free_mb': round(total.free / (1024 * 1024), 1),
    })


# --- MangaDex routes ---

@app.route('/mangadex/search')
def mangadex_search():
    """Search MangaDex for manga."""
    q = request.args.get('q', '').strip()
    if not q:
        return jsonify([])
    unfiltered = request.args.get('unfiltered') == '1'
    try:
        results = search_manga(q, unfiltered=unfiltered)
        return jsonify(results)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/mangadex/volumes/<manga_id>')
def mangadex_volumes(manga_id):
    """Get available volumes for a manga."""
    unfiltered = request.args.get('unfiltered') == '1'
    try:
        volumes = get_volumes(manga_id, unfiltered=unfiltered)

        all_chapters = []
        for vol in volumes.values():
            all_chapters.extend(vol['chapters'])
        all_chapters.sort(key=lambda c: float(c["chapter"]) if c["chapter"].replace(".", "").isdigit() else 999)
        total_chapters = len(all_chapters)
        first_ch = all_chapters[0]['chapter'] if all_chapters else '1'
        last_ch = all_chapters[-1]['chapter'] if all_chapters else '1'

        vol_list = []
        for vol_num in sorted(volumes.keys(), key=lambda x: (x == 'Extras', float(x) if x != 'Extras' and x.replace('.', '').isdigit() else 999)):
            vol = volumes[vol_num]
            ch_range = f"Ch. {vol['chapters'][0]['chapter']}"
            if len(vol['chapters']) > 1:
                ch_range += f"–{vol['chapters'][-1]['chapter']}"
            vol_list.append({
                'volume': vol_num,
                'chapter_count': vol['chapter_count'],
                'chapter_range': ch_range,
            })
        return jsonify({
            'volumes': vol_list,
            'total_chapters': total_chapters,
            'first_chapter': first_ch,
            'last_chapter': last_ch,
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/mangadex/download', methods=['POST'])
def mangadex_download():
    """Start downloading manga volumes from MangaDex."""
    data = request.json
    manga_id = data.get('manga_id')
    manga_title = data.get('manga_title', 'Manga')
    volume_nums = data.get('volumes', [])

    if not manga_id or not volume_nums:
        return jsonify({'error': 'Missing manga_id or volumes'}), 400

    job_id = str(uuid.uuid4())[:8]
    jobs[job_id] = {
        'status': 'processing',
        'messages': [],
        'results': [],
        'filename': manga_title,
    }

    thread = threading.Thread(
        target=run_mangadex_download,
        args=(job_id, manga_id, manga_title, volume_nums)
    )
    thread.daemon = True
    thread.start()

    return jsonify({'job_id': job_id})


# --- Multi-source routes ---

@app.route('/source/search')
def source_search():
    """Search a manga source by name."""
    q = request.args.get('q', '').strip()
    source = request.args.get('source', 'mangapill')
    if not q:
        return jsonify([])
    try:
        if source == 'mangapill':
            return jsonify(mp_search(q))
        elif source == '1manga':
            return jsonify(om_search(q))
        else:
            return jsonify({'error': f'Unknown source: {source}'}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/source/volumes')
def source_volumes():
    """Get volumes/chapters for a manga from a source."""
    source = request.args.get('source', 'mangapill')
    manga_id = request.args.get('id', '')
    slug = request.args.get('slug', '')
    if not manga_id and not slug:
        return jsonify({'error': 'Missing id or slug'}), 400
    try:
        if source == 'mangapill':
            volumes = mp_volumes(manga_id, slug)
        elif source == '1manga':
            volumes = om_volumes(slug or manga_id)
        else:
            return jsonify({'error': f'Unknown source: {source}'}), 400

        all_chapters = []
        for vol in volumes.values():
            all_chapters.extend(vol['chapters'])
        all_chapters.sort(key=lambda c: float(c["chapter"]) if c["chapter"].replace(".", "").isdigit() else 999)
        total_chapters = len(all_chapters)
        first_ch = all_chapters[0]['chapter'] if all_chapters else '1'
        last_ch = all_chapters[-1]['chapter'] if all_chapters else '1'

        vol_list = []
        for vol_num in sorted(volumes.keys(), key=lambda x: (x == 'Extras', float(x) if x != 'Extras' and x.replace('.', '').isdigit() else 999)):
            vol = volumes[vol_num]
            ch_range = f"Ch. {vol['chapters'][0]['chapter']}"
            if len(vol['chapters']) > 1:
                ch_range += f"–{vol['chapters'][-1]['chapter']}"
            vol_list.append({
                'volume': vol_num,
                'chapter_count': vol['chapter_count'],
                'chapter_range': ch_range,
            })
        return jsonify({
            'volumes': vol_list,
            'total_chapters': total_chapters,
            'first_chapter': first_ch,
            'last_chapter': last_ch,
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/source/download', methods=['POST'])
def source_download():
    """Download manga from a non-MangaDex source."""
    data = request.json
    source = data.get('source', 'mangapill')
    manga_id = data.get('manga_id', '')
    manga_slug = data.get('manga_slug', '')
    manga_title = data.get('manga_title', 'Manga')
    volume_nums = data.get('volumes', [])

    if not volume_nums:
        return jsonify({'error': 'No volumes selected'}), 400

    job_id = str(uuid.uuid4())[:8]
    jobs[job_id] = {
        'status': 'processing',
        'messages': [],
        'results': [],
        'filename': manga_title,
    }

    thread = threading.Thread(
        target=run_source_download,
        args=(job_id, source, manga_id, manga_slug, manga_title, volume_nums)
    )
    thread.daemon = True
    thread.start()

    return jsonify({'job_id': job_id})


def run_source_download(job_id, source, manga_id, manga_slug, manga_title, volume_nums):
    job = jobs[job_id]

    def progress(msg):
        job['messages'].append(msg)

    def is_cancelled():
        return job.get('cancelled', False)

    try:
        progress(f"Fetching chapter data for {manga_title} from {source}...")
        if source == 'mangapill':
            all_volumes = mp_volumes(manga_id, manga_slug)
        elif source == '1manga':
            all_volumes = om_volumes(manga_slug or manga_id)
        else:
            progress(f"Unknown source: {source}")
            job['status'] = 'done'
            return

        all_chapters = []
        for vol in all_volumes.values():
            all_chapters.extend(vol['chapters'])
        all_chapters.sort(key=lambda c: float(c["chapter"]) if c["chapter"].replace(".", "").isdigit() else 999)

        downloaded_files = []
        for vol_num in volume_nums:
            if is_cancelled():
                return

            if vol_num.startswith('range:'):
                r = vol_num[6:].split('-')
                r_from, r_to = float(r[0]), float(r[1])
                chapters = [c for c in all_chapters if r_from <= float(c["chapter"]) <= r_to]
                if not chapters:
                    progress(f"No chapters in range {r_from}-{r_to}")
                    continue
                if source == 'mangapill':
                    cbz_path = mp_download(manga_title, chapters, INPUT_DIR, progress)
                elif source == '1manga':
                    cbz_path = om_download(manga_title, f"Ch{int(r_from)}-{int(r_to)}", chapters, INPUT_DIR, progress)
            elif vol_num not in all_volumes:
                progress(f"Volume {vol_num} not found, skipping...")
                continue
            else:
                vol_data = all_volumes[vol_num]
                if source == 'mangapill':
                    cbz_path = mp_download(manga_title, vol_data["chapters"], INPUT_DIR, progress)
                elif source == '1manga':
                    cbz_path = om_download(manga_title, vol_num, vol_data["chapters"], INPUT_DIR, progress)

            downloaded_files.append(cbz_path)
            Path(cbz_path).with_suffix('.manga').touch()
            log_download(cbz_path.name)

        job['results'] = [{'device': 'Downloaded', 'filename': p.name, 'folder': '_input', 'path': str(p)} for p in downloaded_files]
        progress("Done!")
        job['status'] = 'done'
    except Exception as e:
        progress(f"Error: {e}")
        job['status'] = 'done'


# --- Preview routes ---

@app.route('/preview/upload', methods=['POST'])
def preview_upload():
    """Upload a file directly for preview (goes to output/Uploads/)."""
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    f = request.files['file']
    if not f.filename:
        return jsonify({'error': 'No filename'}), 400
    folder = 'Uploads'
    out_dir = OUTPUT_DIR / folder
    out_dir.mkdir(parents=True, exist_ok=True)
    safe_name = Path(f.filename).name
    dest = out_dir / safe_name
    f.save(str(dest))
    return jsonify({'path': f'{folder}/{safe_name}'})


@app.route('/preview/list')
def preview_list():
    """List EPUB files available for preview."""
    epubs = []
    for folder in ['XTe Ink', 'Kindle', 'Uploads']:
        folder_path = OUTPUT_DIR / folder
        if folder_path.exists():
            for f in sorted(folder_path.iterdir(), key=lambda x: x.name.lower()):
                if f.suffix.lower() in ('.epub', '.xtc'):
                    size_mb = f.stat().st_size / (1024 * 1024)
                    epubs.append({
                        'name': f.name,
                        'folder': folder,
                        'size': f"{size_mb:.1f} MB",
                        'path': f"{folder}/{f.name}",
                    })
    return jsonify(epubs)


@app.route('/preview/pages/<path:file_path>')
def preview_pages(file_path):
    """Extract and serve page list from an EPUB or XTC."""
    full_path = OUTPUT_DIR / file_path
    if not full_path.exists():
        return jsonify({'error': 'File not found'}), 404

    pages = []
    if full_path.suffix.lower() == '.xtc':
        from build_xtc import read_xtc_page_count
        xtc_data = full_path.read_bytes()
        count = read_xtc_page_count(xtc_data)
        for i in range(count):
            pages.append({
                'index': i,
                'name': f'page_{i:04d}',
                'url': f'/preview/image/{file_path}/{i}',
            })
    else:
        import zipfile
        with zipfile.ZipFile(full_path, 'r') as zf:
            image_files = sorted([
                n for n in zf.namelist()
                if n.lower().endswith(('.jpg', '.jpeg', '.png'))
                and not n.startswith('__MACOSX')
            ])
            for i, name in enumerate(image_files):
                pages.append({
                    'index': i,
                    'name': name,
                    'url': f'/preview/image/{file_path}/{i}',
                })
    return jsonify(pages)


@app.route('/preview/image/<path:file_path>/<int:page_idx>')
def preview_image(file_path, page_idx):
    """Serve a single page image from an EPUB or XTC."""
    import io
    full_path = OUTPUT_DIR / file_path
    if not full_path.exists():
        return "File not found", 404

    if full_path.suffix.lower() == '.xtc':
        from build_xtc import read_xtc_page, read_xtc_page_count
        xtc_data = full_path.read_bytes()
        if page_idx >= read_xtc_page_count(xtc_data):
            return "Page not found", 404
        img = read_xtc_page(xtc_data, page_idx)
        if img is None:
            return "Page decode failed", 500
        buf = io.BytesIO()
        img.save(buf, format='PNG')
        buf.seek(0)
        from flask import Response
        return Response(buf.read(), mimetype='image/png')

    import zipfile
    with zipfile.ZipFile(full_path, 'r') as zf:
        image_files = sorted([
            n for n in zf.namelist()
            if n.lower().endswith(('.jpg', '.jpeg', '.png'))
            and not n.startswith('__MACOSX')
        ])
        if page_idx >= len(image_files):
            return "Page not found", 404

        img_data = zf.read(image_files[page_idx])
        ext = image_files[page_idx].rsplit('.', 1)[-1].lower()
        mime = 'image/jpeg' if ext in ('jpg', 'jpeg') else 'image/png'

        from flask import Response
        return Response(img_data, mimetype=mime)


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    default_host = '0.0.0.0' if CLOUD else '127.0.0.1'
    host = os.environ.get('HOST', default_host)
    print(f"\n  Comic Book Converter")
    print(f"  Open http://localhost:{port} in your browser\n")
    print(f"  Input:  {INPUT_DIR}/")
    print(f"  Output: {OUTPUT_DIR}/")
    if CLOUD:
        print(f"  Mode:   Cloud\n")
    else:
        print()
    app.run(host=host, port=port, debug=False)
