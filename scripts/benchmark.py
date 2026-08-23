# benchmark.py — Parameter sweep benchmark for comic converter pipeline
# Profiles manga/comics across conversion settings using math metrics
# and optional AI vision scoring (CLIP via local vision-tool server).
#
# Usage:
#   python scripts/benchmark.py                        # all titles, smart sweep
#   python scripts/benchmark.py --vision               # add CLIP perceptual scoring
#   python scripts/benchmark.py --mode quick           # one-at-a-time sweep
#   python scripts/benchmark.py --mode full            # full grid (slow)
#   python scripts/benchmark.py --titles "Berserk,Akira"  # specific titles
#   python scripts/benchmark.py --pages 3              # pages sampled per title
#   python scripts/benchmark.py --report results.csv   # custom output path
#
# Requires: numpy, Pillow, scikit-image (for SSIM)
# Optional: requests (for --vision), vision-tool server at localhost:9090
#
# Gotchas:
# - Full grid is ~1920 combos per page. With 5 pages × 20 titles = 192k runs.
#   Use --mode smart (default) which does one-at-a-time then focused grid.
# - Imports from src/ so run from project root or set PYTHONPATH.
# - CBR files need unar installed (brew install unar on macOS).
# - Native C dithering compiles on first use — first run may be slower.
# - --vision adds ~500ms per combo (CLIP scoring). First call ~6s (model load).
# - Vision server must be running: launchctl load ~/Library/LaunchAgents/com.local.vision-tool.plist

import sys
import os
import csv
import json
import time
import tempfile
import shutil
import argparse
import zipfile
import io
from pathlib import Path
from itertools import product
from collections import defaultdict

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))
from xtc_pipeline import (
    to_grayscale, apply_contrast, apply_gamma, denoise_median,
    find_content_bounds, dither, resize_with_padding,
    TARGET_WIDTH, TARGET_HEIGHT
)
from extract import EXTRACTORS, natural_sort_key, is_image

# --- Parameter definitions ---

DITHER_ALGOS = ['floyd', 'sierra-lite', 'atkinson']
GAMMA_RANGE = [round(0.5 + i * 0.1, 1) for i in range(16)]  # 0.5 to 2.0
CONTRAST_LEVELS = {
    'off': 0,
    'light': 1,
    'normal': 2,
    'strong': 3,
    'max': 4,
}
SHARPEN_LEVELS = {
    'off': 0.0,
    'light': 0.3,
    'normal': 0.7,
    'strong': 1.2,
}
DENOISE_OPTIONS = [False, True]

DEFAULTS = {
    'dither': 'atkinson',
    'gamma': 1.0,
    'contrast': 2,       # "Normal" (level 2)
    'sharpen': 0.7,      # "Normal"
    'denoise': False,
}

# --- Metric functions ---

def compute_histogram_stats(img_array):
    """Mean brightness, std dev, clipping at 0 and 255."""
    flat = img_array.ravel().astype(np.float64)
    total = len(flat)
    return {
        'mean_brightness': float(np.mean(flat)),
        'std_brightness': float(np.std(flat)),
        'clip_black_pct': float(np.sum(flat == 0) / total * 100),
        'clip_white_pct': float(np.sum(flat == 255) / total * 100),
    }


def compute_entropy(img_array):
    """Shannon entropy — information content per pixel."""
    flat = img_array.ravel().astype(np.uint8)
    hist = np.bincount(flat, minlength=256).astype(np.float64)
    hist = hist[hist > 0]
    probs = hist / hist.sum()
    return float(-np.sum(probs * np.log2(probs)))


def compute_edge_density(img_array):
    """Sobel edge density — measures text/line readability after processing."""
    if img_array.dtype != np.float64:
        arr = img_array.astype(np.float64)
    else:
        arr = img_array
    # Sobel kernels
    if arr.shape[0] < 3 or arr.shape[1] < 3:
        return 0.0
    gx = np.zeros_like(arr)
    gy = np.zeros_like(arr)
    gx[1:-1, 1:-1] = (
        -arr[:-2, :-2] + arr[:-2, 2:]
        - 2 * arr[1:-1, :-2] + 2 * arr[1:-1, 2:]
        - arr[2:, :-2] + arr[2:, 2:]
    )
    gy[1:-1, 1:-1] = (
        -arr[:-2, :-2] - 2 * arr[:-2, 1:-1] - arr[:-2, 2:]
        + arr[2:, :-2] + 2 * arr[2:, 1:-1] + arr[2:, 2:]
    )
    magnitude = np.sqrt(gx ** 2 + gy ** 2)
    threshold = 30.0
    edge_pixels = np.sum(magnitude > threshold)
    total = arr.shape[0] * arr.shape[1]
    return float(edge_pixels / total * 100)


def compute_ssim(original, processed):
    """Structural similarity between original grayscale and processed output.
    Uses scikit-image if available, falls back to simplified implementation."""
    try:
        from skimage.metrics import structural_similarity
        orig_resized = Image.fromarray(original.astype(np.uint8), mode='L')
        orig_resized = resize_with_padding(orig_resized, TARGET_WIDTH, TARGET_HEIGHT)
        orig_arr = np.array(orig_resized, dtype=np.float64)
        proc_arr = processed.astype(np.float64)
        if orig_arr.shape != proc_arr.shape:
            return 0.0
        return float(structural_similarity(orig_arr, proc_arr, data_range=255))
    except ImportError:
        return _ssim_simple(original, processed)


def _ssim_simple(original, processed):
    """Simplified SSIM when scikit-image isn't available."""
    orig_resized = Image.fromarray(original.astype(np.uint8), mode='L')
    orig_resized = resize_with_padding(orig_resized, TARGET_WIDTH, TARGET_HEIGHT)
    orig_arr = np.array(orig_resized, dtype=np.float64)
    proc_arr = processed.astype(np.float64)
    if orig_arr.shape != proc_arr.shape:
        return 0.0

    C1 = (0.01 * 255) ** 2
    C2 = (0.03 * 255) ** 2
    mu_x = np.mean(orig_arr)
    mu_y = np.mean(proc_arr)
    sig_x = np.std(orig_arr)
    sig_y = np.std(proc_arr)
    sig_xy = np.mean((orig_arr - mu_x) * (proc_arr - mu_y))
    ssim = ((2 * mu_x * mu_y + C1) * (2 * sig_xy + C2)) / \
           ((mu_x ** 2 + mu_y ** 2 + C1) * (sig_x ** 2 + sig_y ** 2 + C2))
    return float(ssim)


def compute_bw_ratio(img_array):
    """Black/white pixel ratio for dithered 1-bit output."""
    flat = img_array.ravel()
    black = np.sum(flat < 128)
    total = len(flat)
    return {
        'black_pct': float(black / total * 100),
        'white_pct': float((total - black) / total * 100),
    }


def compute_contrast_ratio(img_array):
    """Ratio between darkest and lightest 5% of pixels.
    Only meaningful on continuous-tone (pre-dither) images."""
    flat = np.sort(img_array.ravel().astype(np.float64))
    n = len(flat)
    pct5 = max(1, n // 20)
    dark_avg = np.mean(flat[:pct5])
    light_avg = np.mean(flat[-pct5:])
    if dark_avg < 1:
        dark_avg = 1
    return float(light_avg / dark_avg)


VISION_URL = 'http://localhost:9090'

CLIP_PROMPTS_POSITIVE = [
    'clear readable manga page with sharp lines and good contrast',
    'detailed black and white comic art with crisp linework',
]
CLIP_PROMPTS_NEGATIVE = [
    'noisy grainy image with poor contrast and muddy details',
    'washed out blurry image with lost detail',
    'over-processed image with crushed blacks and harsh artifacts',
]
CLIP_PROMPTS = CLIP_PROMPTS_POSITIVE + CLIP_PROMPTS_NEGATIVE


def vision_score(image_path):
    """Score an image against quality prompts using CLIP via local vision server.
    Returns dict with clip_quality (positive - negative avg), individual scores."""
    import requests as req
    try:
        resp = req.post(f'{VISION_URL}/score', json={
            'image': str(image_path),
            'prompts': CLIP_PROMPTS,
        }, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        scores = data['scores']

        pos_avg = sum(scores[:len(CLIP_PROMPTS_POSITIVE)]) / len(CLIP_PROMPTS_POSITIVE)
        neg_avg = sum(scores[len(CLIP_PROMPTS_POSITIVE):]) / len(CLIP_PROMPTS_NEGATIVE)

        return {
            'clip_quality': round(pos_avg - neg_avg, 6),
            'clip_positive': round(pos_avg, 6),
            'clip_negative': round(neg_avg, 6),
            'clip_best_match': data['best_match'],
            'clip_ms': round(data['elapsed_ms'], 1),
        }
    except Exception as e:
        return {
            'clip_quality': 0.0,
            'clip_positive': 0.0,
            'clip_negative': 0.0,
            'clip_best_match': f'error: {e}',
            'clip_ms': 0.0,
        }


def check_vision_server():
    """Check if the vision-tool server is running."""
    import requests as req
    try:
        resp = req.get(f'{VISION_URL}/health', timeout=5)
        return resp.status_code == 200
    except Exception:
        return False


def compute_all_metrics(original_gray, pre_dither_uint8, processed_uint8):
    """Compute all metrics for a single processed image.
    pre_dither_uint8: the grayscale image after contrast/gamma/resize but before dithering.
    processed_uint8: the final dithered output."""
    m = {}
    # Post-dither stats (for reference/analysis)
    m.update(compute_histogram_stats(processed_uint8))
    m['entropy'] = compute_entropy(processed_uint8)
    m['ssim'] = compute_ssim(original_gray, processed_uint8)
    bw = compute_bw_ratio(processed_uint8)
    m.update(bw)

    # Pre-dither metrics (used for scoring — not distorted by binarization)
    m['pre_dither_edge_density'] = compute_edge_density(pre_dither_uint8)
    m['contrast_ratio'] = compute_contrast_ratio(pre_dither_uint8)
    pre_stats = compute_histogram_stats(pre_dither_uint8)
    m['pre_dither_mean'] = pre_stats['mean_brightness']
    m['pre_dither_std'] = pre_stats['std_brightness']
    m['pre_dither_clip_black'] = pre_stats['clip_black_pct']
    m['pre_dither_clip_white'] = pre_stats['clip_white_pct']
    m['pre_dither_entropy'] = compute_entropy(pre_dither_uint8)

    # File size estimate (PNG compression of the output)
    img = Image.fromarray(processed_uint8, mode='L')
    buf = io.BytesIO()
    img.save(buf, format='PNG', optimize=True)
    m['file_size_bytes'] = buf.tell()

    return m


# --- Pipeline runner (mirrors xtc_pipeline.process_page without rotation) ---

def run_pipeline(gray, params):
    """Run the conversion pipeline with given parameters.
    Returns (pre_dither_uint8, dithered_uint8) — both as numpy arrays."""
    arr = gray.copy()

    if params['denoise']:
        arr = denoise_median(arr)

    bounds = find_content_bounds(arr)
    if bounds:
        x, y, w, h = bounds
        if w < arr.shape[1] or h < arr.shape[0]:
            arr = arr[y:y + h, x:x + w]

    if params['contrast'] > 0:
        arr = apply_contrast(arr, params['contrast'])

    arr = apply_gamma(arr, params['gamma'])

    pil_gray = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), mode='L')
    pil_gray = resize_with_padding(pil_gray, TARGET_WIDTH, TARGET_HEIGHT)

    pre_dither = np.array(pil_gray, dtype=np.uint8)
    gray_arr = np.array(pil_gray, dtype=np.float32)
    dithered = dither(gray_arr, algorithm=params['dither'], sharpen=params['sharpen'])
    return pre_dither, dithered


# --- Page sampling ---

def sample_pages_from_archive(archive_path, num_pages=5):
    """Extract a few representative pages from a comic archive.
    Picks evenly spaced pages (skipping cover) to capture variety."""
    ext = archive_path.suffix.lower()
    if ext not in EXTRACTORS:
        return []

    tmp_dir = Path(tempfile.mkdtemp(prefix='benchmark_'))
    try:
        EXTRACTORS[ext](archive_path, tmp_dir)
        pages = sorted(
            [p for p in tmp_dir.iterdir()
             if p.suffix.lower() in {'.jpg', '.jpeg', '.png'}],
            key=lambda f: natural_sort_key(f.name)
        )
        if not pages:
            return []

        # Skip cover (page 0), sample evenly from the rest
        content = pages[1:] if len(pages) > 1 else pages
        if len(content) <= num_pages:
            indices = list(range(len(content)))
        else:
            step = len(content) / num_pages
            indices = [int(step * i + step / 2) for i in range(num_pages)]

        sampled = []
        for idx in indices:
            img = Image.open(content[idx])
            gray = to_grayscale(img)
            sampled.append({
                'filename': content[idx].name,
                'gray': gray,
                'width': img.width,
                'height': img.height,
            })
        return sampled
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# --- Sweep strategies ---

def generate_one_at_a_time():
    """Vary one parameter at a time from defaults. Fast baseline."""
    combos = [DEFAULTS.copy()]  # baseline

    for g in GAMMA_RANGE:
        if g != DEFAULTS['gamma']:
            c = DEFAULTS.copy()
            c['gamma'] = g
            combos.append(c)

    for name, level in CONTRAST_LEVELS.items():
        if level != DEFAULTS['contrast']:
            c = DEFAULTS.copy()
            c['contrast'] = level
            combos.append(c)

    for name, val in SHARPEN_LEVELS.items():
        if val != DEFAULTS['sharpen']:
            c = DEFAULTS.copy()
            c['sharpen'] = val
            combos.append(c)

    for algo in DITHER_ALGOS:
        if algo != DEFAULTS['dither']:
            c = DEFAULTS.copy()
            c['dither'] = algo
            combos.append(c)

    c = DEFAULTS.copy()
    c['denoise'] = True
    combos.append(c)

    return combos


def generate_full_grid():
    """Full parameter grid. ~1920 combinations."""
    combos = []
    for d, g, (_, cl), (_, sh), dn in product(
        DITHER_ALGOS,
        GAMMA_RANGE,
        CONTRAST_LEVELS.items(),
        SHARPEN_LEVELS.items(),
        DENOISE_OPTIONS,
    ):
        combos.append({
            'dither': d,
            'gamma': g,
            'contrast': cl,
            'sharpen': sh,
            'denoise': dn,
        })
    return combos


def generate_smart_sweep():
    """One-at-a-time baseline + focused grid around key interactions.
    Tests ~120 combinations — 15x less than full grid, captures most signal."""
    combos = generate_one_at_a_time()
    seen = set()
    for c in combos:
        seen.add(_combo_key(c))

    # Cross dither x contrast (the two most impactful parameters)
    for d in DITHER_ALGOS:
        for _, cl in CONTRAST_LEVELS.items():
            c = DEFAULTS.copy()
            c['dither'] = d
            c['contrast'] = cl
            k = _combo_key(c)
            if k not in seen:
                combos.append(c)
                seen.add(k)

    # Cross gamma x contrast (common interaction)
    for g in [0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.5]:
        for _, cl in CONTRAST_LEVELS.items():
            c = DEFAULTS.copy()
            c['gamma'] = g
            c['contrast'] = cl
            k = _combo_key(c)
            if k not in seen:
                combos.append(c)
                seen.add(k)

    # Cross sharpen x dither (sharpening interacts with dither pattern)
    for d in DITHER_ALGOS:
        for _, sh in SHARPEN_LEVELS.items():
            c = DEFAULTS.copy()
            c['dither'] = d
            c['sharpen'] = sh
            k = _combo_key(c)
            if k not in seen:
                combos.append(c)
                seen.add(k)

    # Denoise x dither (denoise smoothing affects dither quality)
    for d in DITHER_ALGOS:
        c = DEFAULTS.copy()
        c['dither'] = d
        c['denoise'] = True
        k = _combo_key(c)
        if k not in seen:
            combos.append(c)
            seen.add(k)

    return combos


def _combo_key(c):
    return (c['dither'], c['gamma'], c['contrast'], c['sharpen'], c['denoise'])


# --- Title discovery ---

def discover_titles(input_dir):
    """Find comic archives in input/, group by title."""
    titles = {}
    for f in sorted(input_dir.iterdir(), key=lambda p: natural_sort_key(p.name)):
        if f.suffix.lower() in {'.cbz', '.cbr', '.cb7'}:
            # Group numbered Civil War files under one title
            name = f.stem
            # Strip leading numbers like "001 ", "007 "
            stripped = name.lstrip('0123456789 ')
            if stripped:
                name = stripped
            # Use first file per title group
            base = name.split(' Ch.')[0].split(' Vol.')[0].rstrip(' 0123456789')
            if base not in titles:
                titles[base] = f
    return titles


def contrast_name(level):
    for name, val in CONTRAST_LEVELS.items():
        if val == level:
            return name
    return str(level)


def sharpen_name(val):
    for name, v in SHARPEN_LEVELS.items():
        if v == val:
            return name
    return str(val)


# --- Main benchmark ---

def run_benchmark(input_dir, mode='smart', num_pages=5, titles_filter=None,
                  report_path=None, use_vision=False):
    input_dir = Path(input_dir)
    if not input_dir.exists():
        print(f"Error: {input_dir} not found")
        sys.exit(1)

    if use_vision:
        if not check_vision_server():
            print("Error: Vision server not running at localhost:9090")
            print("Start it: launchctl load ~/Library/LaunchAgents/com.local.vision-tool.plist")
            sys.exit(1)
        print("Vision scoring: ON (CLIP via localhost:9090)")

    titles = discover_titles(input_dir)
    if titles_filter:
        filter_set = {t.strip().lower() for t in titles_filter.split(',')}
        titles = {k: v for k, v in titles.items()
                  if any(f in k.lower() for f in filter_set)}

    if not titles:
        print("No titles found in input/")
        sys.exit(1)

    if mode == 'quick':
        combos = generate_one_at_a_time()
    elif mode == 'full':
        combos = generate_full_grid()
    else:
        combos = generate_smart_sweep()

    print(f"Benchmark: {len(titles)} titles, {num_pages} pages each, {len(combos)} parameter combos")
    total_runs = len(titles) * num_pages * len(combos)
    print(f"Mode: {mode} | Total runs: ~{total_runs:,}", end='')
    if use_vision:
        est_min = total_runs * 0.5 / 60
        print(f" | Est. vision time: ~{est_min:.0f} min")
    else:
        print()
    print()

    if report_path is None:
        tag = f'benchmark_{mode}'
        if use_vision:
            tag += '_vision'
        report_path = Path('scripts') / f'{tag}_{time.strftime("%Y%m%d_%H%M%S")}.csv'
    else:
        report_path = Path(report_path)

    report_path.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        'title', 'page', 'page_w', 'page_h',
        'dither', 'gamma', 'contrast', 'contrast_name', 'sharpen', 'sharpen_name', 'denoise',
        'ssim', 'entropy', 'black_pct', 'white_pct',
        'mean_brightness', 'std_brightness', 'clip_black_pct', 'clip_white_pct',
        'pre_dither_edge_density', 'pre_dither_entropy', 'pre_dither_mean', 'pre_dither_std',
        'pre_dither_clip_black', 'pre_dither_clip_white', 'contrast_ratio',
        'file_size_bytes', 'processing_time_ms',
    ]
    if use_vision:
        fieldnames.extend(['clip_quality', 'clip_positive', 'clip_negative',
                           'clip_best_match', 'clip_ms'])

    all_results = []
    title_summaries = {}

    # Temp dir for vision scoring images
    vision_tmp = Path(tempfile.mkdtemp(prefix='benchmark_vision_')) if use_vision else None

    try:
        with open(report_path, 'w', newline='') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()

            for ti, (title, archive_path) in enumerate(titles.items()):
                print(f"[{ti + 1}/{len(titles)}] {title} ({archive_path.name})")
                pages = sample_pages_from_archive(archive_path, num_pages)
                if not pages:
                    print(f"  Skipped — no pages extracted")
                    continue

                label = "combos" if not use_vision else "combos+CLIP"
                print(f"  Sampled {len(pages)} pages, running {len(combos)} {label} each...")
                title_results = []

                for pi, page in enumerate(pages):
                    gray = page['gray']

                    for ci, params in enumerate(combos):
                        t0 = time.perf_counter()
                        pre_dither, processed = run_pipeline(gray, params)
                        elapsed_ms = (time.perf_counter() - t0) * 1000

                        metrics = compute_all_metrics(gray, pre_dither, processed)
                        metrics['processing_time_ms'] = round(elapsed_ms, 1)

                        if use_vision:
                            tmp_path = vision_tmp / f't{ti}_p{pi}_c{ci}.png'
                            Image.fromarray(processed, mode='L').save(tmp_path)
                            clip = vision_score(tmp_path)
                            metrics.update(clip)
                            tmp_path.unlink(missing_ok=True)

                        row = {
                            'title': title,
                            'page': page['filename'],
                            'page_w': page['width'],
                            'page_h': page['height'],
                            'dither': params['dither'],
                            'gamma': params['gamma'],
                            'contrast': params['contrast'],
                            'contrast_name': contrast_name(params['contrast']),
                            'sharpen': params['sharpen'],
                            'sharpen_name': sharpen_name(params['sharpen']),
                            'denoise': params['denoise'],
                        }
                        row.update(metrics)
                        writer.writerow(row)
                        all_results.append(row)
                        title_results.append(row)

                    done = (pi + 1) * len(combos)
                    total = len(pages) * len(combos)
                    print(f"  Page {pi + 1}/{len(pages)}: {done}/{total} {label} done", end='\r')

                print()

                if title_results:
                    summary = _summarize_title(title, title_results, use_vision)
                    title_summaries[title] = summary
    finally:
        if vision_tmp:
            shutil.rmtree(vision_tmp, ignore_errors=True)

    print()
    print(f"Results saved to {report_path}")
    print(f"Total rows: {len(all_results)}")
    print()

    _print_report(title_summaries, all_results, use_vision)

    summary_path = report_path.with_suffix('.json')
    with open(summary_path, 'w') as f:
        json.dump({
            'mode': mode,
            'vision': use_vision,
            'num_titles': len(titles),
            'num_pages': num_pages,
            'num_combos': len(combos),
            'total_runs': len(all_results),
            'titles': title_summaries,
        }, f, indent=2, default=str)
    print(f"Summary saved to {summary_path}")

    return all_results, title_summaries


def _summarize_title(title, results, use_vision=False):
    """Find best parameters for a title based on composite score."""
    scored = []
    for r in results:
        score = _composite_score(r, use_vision)
        scored.append((score, r))

    scored.sort(key=lambda x: x[0], reverse=True)
    best = scored[0][1]
    worst = scored[-1][1]

    # Find default's score
    default_score = None
    for score, r in scored:
        if (r['dither'] == DEFAULTS['dither'] and
            r['gamma'] == DEFAULTS['gamma'] and
            r['contrast'] == DEFAULTS['contrast'] and
            r['sharpen'] == DEFAULTS['sharpen'] and
            r['denoise'] == DEFAULTS['denoise']):
            default_score = score
            break

    return {
        'best_params': {
            'dither': best['dither'],
            'gamma': best['gamma'],
            'contrast': best['contrast'],
            'contrast_name': best['contrast_name'],
            'sharpen': best['sharpen'],
            'sharpen_name': best['sharpen_name'],
            'denoise': best['denoise'],
        },
        'best_score': round(scored[0][0], 4),
        'worst_score': round(scored[-1][0], 4),
        'default_score': round(default_score, 4) if default_score else None,
        'default_rank': next(
            (i + 1 for i, (_, r) in enumerate(scored)
             if r['dither'] == DEFAULTS['dither'] and
                r['gamma'] == DEFAULTS['gamma'] and
                r['contrast'] == DEFAULTS['contrast'] and
                r['sharpen'] == DEFAULTS['sharpen'] and
                r['denoise'] == DEFAULTS['denoise']),
            None
        ),
        'total_combos': len(scored),
        'best_metrics': {
            'ssim': round(best['ssim'], 4),
            'pre_dither_entropy': round(best.get('pre_dither_entropy', 0), 3),
            'pre_dither_edge_density': round(best.get('pre_dither_edge_density', 0), 2),
            'pre_dither_std': round(best.get('pre_dither_std', 0), 1),
            'clip_quality': round(best.get('clip_quality', 0), 4) if use_vision else None,
        },
    }


def _composite_score(r, use_vision=False):
    """Weighted composite quality score. Higher is better.

    All detail/contrast/entropy metrics are from the PRE-DITHER image to avoid
    the dithering pattern itself inflating scores. SSIM is post-dither vs original
    (the actual fidelity measure). Clipping penalties prevent degenerate extremes.

    When vision scoring is active, CLIP quality gets 25% of the weight (the
    perceptual "does this look like a good manga page" signal), and math metrics
    are proportionally reduced."""
    ssim_score = r['ssim']

    pre_entropy = r.get('pre_dither_entropy', 5.0)
    entropy_score = min(pre_entropy / 7.0, 1.0)

    pre_edges = r.get('pre_dither_edge_density', 10.0)
    edge_score = min(pre_edges / 20.0, 1.0)

    pre_std = r.get('pre_dither_std', 70.0)
    std_score = min(pre_std / 85.0, 1.0)

    clip_black = r.get('pre_dither_clip_black', 0)
    clip_white = r.get('pre_dither_clip_white', 0)
    clip_penalty = 0.0
    if clip_black > 15:
        clip_penalty += (clip_black - 15) * 0.015
    if clip_white > 40:
        clip_penalty += (clip_white - 40) * 0.01
    clip_penalty = min(clip_penalty, 0.3)

    size = r['file_size_bytes']
    size_score = min(size / 20000, 1.0)

    if use_vision and r.get('clip_quality', 0) != 0:
        # clip_quality is typically 0.02-0.12 (positive - negative prompt scores)
        # Normalize to 0-1 range: 0.02 → 0, 0.12 → 1
        cq = r['clip_quality']
        clip_score = max(0, min((cq - 0.02) / 0.10, 1.0))

        return (0.25 * clip_score +
                0.25 * ssim_score +
                0.15 * entropy_score +
                0.10 * edge_score +
                0.10 * std_score +
                0.15 * size_score
                - clip_penalty)

    return (0.35 * ssim_score +
            0.20 * entropy_score +
            0.15 * edge_score +
            0.15 * std_score +
            0.15 * size_score
            - clip_penalty)


def _print_report(title_summaries, all_results, use_vision=False):
    """Print a readable summary to console."""
    print("=" * 80)
    label = "BENCHMARK RESULTS (math + vision)" if use_vision else "BENCHMARK RESULTS"
    print(label)
    print("=" * 80)

    for title, summary in sorted(title_summaries.items()):
        bp = summary['best_params']
        print(f"\n{title}")
        print(f"  Best: dither={bp['dither']}, gamma={bp['gamma']}, "
              f"contrast={bp['contrast_name']}, sharpen={bp['sharpen_name']}, "
              f"denoise={bp['denoise']}")
        print(f"  Score: {summary['best_score']} (best) | "
              f"{summary['default_score']} (defaults) | "
              f"{summary['worst_score']} (worst)")
        if summary['default_rank']:
            pct = (1 - summary['default_rank'] / summary['total_combos']) * 100
            print(f"  Default rank: #{summary['default_rank']}/{summary['total_combos']} "
                  f"(top {pct:.0f}%)")
        m = summary['best_metrics']
        metrics_str = (f"  Metrics: SSIM={m['ssim']}, entropy={m['pre_dither_entropy']}, "
                       f"edges={m['pre_dither_edge_density']}%, std={m['pre_dither_std']}")
        if use_vision and m.get('clip_quality') is not None:
            metrics_str += f", CLIP={m['clip_quality']}"
        print(metrics_str)

    # Cross-title analysis
    print(f"\n{'=' * 80}")
    print("CROSS-TITLE ANALYSIS")
    print("=" * 80)

    # Which parameters win most often?
    param_wins = defaultdict(int)
    for title, summary in title_summaries.items():
        bp = summary['best_params']
        param_wins[('dither', bp['dither'])] += 1
        param_wins[('gamma', bp['gamma'])] += 1
        param_wins[('contrast', bp['contrast_name'])] += 1
        param_wins[('sharpen', bp['sharpen_name'])] += 1
        param_wins[('denoise', bp['denoise'])] += 1

    print("\nMost-winning parameter values:")
    for param in ['dither', 'gamma', 'contrast', 'sharpen', 'denoise']:
        relevant = {k: v for k, v in param_wins.items() if k[0] == param}
        if relevant:
            winner = max(relevant, key=relevant.get)
            print(f"  {param}: {winner[1]} ({relevant[winner]}/{len(title_summaries)} titles)")

    # Are current defaults optimal?
    defaults_optimal = sum(1 for s in title_summaries.values()
                          if s['default_rank'] == 1)
    defaults_top10 = sum(1 for s in title_summaries.values()
                        if s['default_rank'] and
                        s['default_rank'] <= max(1, s['total_combos'] // 10))
    print(f"\nCurrent defaults: optimal for {defaults_optimal}/{len(title_summaries)} titles, "
          f"top 10% for {defaults_top10}/{len(title_summaries)} titles")

    # Style clusters (are different art styles best with different settings?)
    if len(title_summaries) > 3:
        # Group by best dither algorithm
        by_dither = defaultdict(list)
        for title, s in title_summaries.items():
            by_dither[s['best_params']['dither']].append(title)
        if len(by_dither) > 1:
            print("\nStyle clusters by best dither algorithm:")
            for algo, titles_list in sorted(by_dither.items()):
                print(f"  {algo}: {', '.join(titles_list)}")


def main():
    parser = argparse.ArgumentParser(description='Comic converter parameter benchmark')
    parser.add_argument('--mode', choices=['quick', 'smart', 'full'], default='smart',
                        help='Sweep strategy (default: smart)')
    parser.add_argument('--pages', type=int, default=5,
                        help='Pages to sample per title (default: 5)')
    parser.add_argument('--titles', type=str, default=None,
                        help='Comma-separated title filter (default: all)')
    parser.add_argument('--report', type=str, default=None,
                        help='Output CSV path (default: auto-named in scripts/)')
    parser.add_argument('--input-dir', type=str, default='input',
                        help='Input directory (default: input/)')
    parser.add_argument('--vision', action='store_true',
                        help='Add CLIP perceptual scoring via local vision server')
    args = parser.parse_args()

    run_benchmark(
        input_dir=args.input_dir,
        mode=args.mode,
        num_pages=args.pages,
        titles_filter=args.titles,
        report_path=args.report,
        use_vision=args.vision,
    )


if __name__ == '__main__':
    main()
