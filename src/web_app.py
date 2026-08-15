# web_app.py — Simple web UI for comic book conversion
# Usage: python src/web_app.py (then open http://localhost:5000)
# Requires: flask, plus all pipeline dependencies
#
# Gotchas:
# - Must run from project root (paths are relative to it).
# - Large files (100+ MB) are fine — Flask handles chunked uploads.
# - Conversion runs in a background thread; frontend polls /status.
# - KCC for Kindle modifies sys.argv — wrapped to restore it.

import sys
import json
import uuid
import shutil
import threading
from pathlib import Path

from flask import Flask, render_template, request, jsonify, send_from_directory

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / 'src'))

from extract import extract, detect_reading_direction
from detect_panels import detect_panels
from split_page import split_page, process_for_eink, process_cover_for_eink
from build_epub import build_epub
from PIL import Image
import re


def natural_sort_key(s):
    return [int(c) if c.isdigit() else c.lower() for c in re.split(r'(\d+)', str(s))]


app = Flask(__name__, template_folder=str(ROOT / 'src' / 'templates'))
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024  # 500 MB

INPUT_DIR = ROOT / 'input'
OUTPUT_DIR = ROOT / 'output'
INPUT_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

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


def convert_xteink_thirds(comic_path, manga, title, progress):
    """Convert for XTe Ink using panel-aware overlapping thirds + e-ink dithering."""
    device = DEVICE_PROFILES['xteink']
    out_dir = OUTPUT_DIR / device['folder']
    out_dir.mkdir(parents=True, exist_ok=True)

    progress("Extracting pages...")
    pages_dir = extract(comic_path, output_base=ROOT / 'output')

    skip = ("_debug", "_grouped")
    pages = sorted(
        [p for p in pages_dir.iterdir()
         if p.suffix.lower() in {'.jpg', '.jpeg', '.png'} and not any(s in p.name for s in skip)],
        key=lambda f: natural_sort_key(f.name)
    )

    if not pages:
        raise ValueError(f"No pages found in {pages_dir}")

    views_dir = ROOT / 'output' / f"{pages_dir.name}_views"
    views_dir.mkdir(parents=True, exist_ok=True)

    total_pages = len(pages)
    cover_path = None

    for page_idx, page_path in enumerate(pages):
        progress(f"Processing page {page_idx + 1} of {total_pages}...")
        img = Image.open(page_path)
        w, h = img.size

        if page_idx == 0:
            cover = process_cover_for_eink(img, device['width'], device['height'])
            vp = views_dir / f"page_{page_idx:04d}_view_00.jpg"
            cover.save(vp, "JPEG", quality=95)
            cover_path = vp
            continue

        panels = detect_panels(page_path, manga=manga)
        regions = split_page(img, panels)

        for ri, (rx, ry, rw, rh) in enumerate(regions):
            crop = img.crop((rx, ry, rx + rw, ry + rh))
            processed = process_for_eink(crop, device['width'], device['height'])
            vp = views_dir / f"page_{page_idx:04d}_view_{ri:02d}.jpg"
            processed.save(vp, "JPEG", quality=92)

    progress("Building EPUB...")
    epub_path = build_epub(
        views_dir,
        title=title,
        output_path=out_dir / f"{title}.epub",
        cover_image_path=cover_path,
        manga=manga,
        max_width=device['width'],
        max_height=device['height'],
    )

    shutil.rmtree(pages_dir, ignore_errors=True)
    shutil.rmtree(views_dir, ignore_errors=True)

    return str(epub_path)


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


def run_conversion(job_id, filepath, devices):
    """Run conversion in background thread."""
    job = jobs[job_id]

    def progress(msg):
        job['messages'].append(msg)

    try:
        comic_path = Path(filepath)
        title = comic_path.stem

        direction, reason = detect_reading_direction(comic_path)
        manga = (direction == 'rtl')
        progress(f"Detected: {'Manga (RTL)' if manga else 'Western (LTR)'} — {reason}")

        results = []

        if 'xteink' in devices:
            path = convert_xteink_thirds(comic_path, manga, title, progress)
            if path:
                results.append({
                    'device': 'XTe Ink X4',
                    'filename': Path(path).name,
                    'folder': 'XTe Ink',
                    'path': path,
                })

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
        job['status'] = 'error'
        job['error'] = str(e)
        progress(f"Error: {e}")


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/files')
def list_files():
    """List comic files in input/ folder."""
    extensions = {'.cbz', '.cbr', '.cb7'}
    files = []
    if INPUT_DIR.exists():
        for f in sorted(INPUT_DIR.iterdir(), key=lambda x: x.name.lower()):
            if f.suffix.lower() in extensions:
                size_mb = f.stat().st_size / (1024 * 1024)
                files.append({'name': f.name, 'size': f"{size_mb:.1f} MB"})
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

    if not filename:
        return jsonify({'error': 'No file specified'}), 400
    if not devices:
        return jsonify({'error': 'No output format selected'}), 400

    filepath = INPUT_DIR / filename
    if not filepath.exists():
        return jsonify({'error': f'File not found: {filename}'}), 404

    job_id = str(uuid.uuid4())[:8]
    jobs[job_id] = {
        'status': 'processing',
        'messages': [],
        'results': [],
        'filename': filename,
    }

    thread = threading.Thread(target=run_conversion, args=(job_id, filepath, devices))
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


@app.route('/output/<path:filepath>')
def download_file(filepath):
    """Serve converted files."""
    return send_from_directory(str(OUTPUT_DIR), filepath, as_attachment=True)


@app.route('/open-output')
def open_output():
    """Open output folder in Finder."""
    import subprocess
    subprocess.Popen(['open', str(OUTPUT_DIR)])
    return jsonify({'ok': True})


if __name__ == '__main__':
    import os
    port = int(os.environ.get('PORT', 5000))
    print(f"\n  Comic Book Converter")
    print(f"  Open http://localhost:{port} in your browser\n")
    print(f"  Input:  {INPUT_DIR}/")
    print(f"  Output: {OUTPUT_DIR}/\n")
    app.run(host='127.0.0.1', port=port, debug=False)
