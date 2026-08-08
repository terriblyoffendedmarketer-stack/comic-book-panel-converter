# preview.py — Preview panel-split results at exact device resolution
# Usage: python src/preview.py <epub-or-panels-dir> [--device kindle|xteink]
# Opens an HTML preview in the browser simulating the target device screen.
#
# Device profiles:
#   kindle  = Kindle Paperwhite Gen 7 (PW3/4): 1072x1448, 6" 300ppi
#   xteink  = XTe Ink X4: 800x480, 4.3" 220ppi (landscape-ish)
#
# Gotchas:
# - XTe Ink X4 is 800x480 which is landscape by default.
#   In KOReader it can be rotated to portrait (480x800).
# - Preview renders at 1:2 scale on retina displays for readability.

import sys
import os
import re
import base64
import webbrowser
import tempfile
from pathlib import Path
from PIL import Image
from io import BytesIO

DEVICES = {
    'kindle': {
        'name': 'Kindle Paperwhite 7th Gen',
        'width': 1072,
        'height': 1448,
        'ppi': 300,
        'screen_inches': 6.0,
    },
    'xteink': {
        'name': 'XTe Ink X4 (portrait mode)',
        'width': 480,
        'height': 800,
        'ppi': 220,
        'screen_inches': 4.3,
    },
}


def image_to_data_uri(img_path, max_width, max_height):
    img = Image.open(img_path)
    if img.mode == 'RGBA':
        img = img.convert('RGB')

    # Resize to fit device
    w, h = img.size
    ratio = min(max_width / w, max_height / h)
    if ratio < 1:
        img = img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)

    buf = BytesIO()
    img.save(buf, 'JPEG', quality=90)
    b64 = base64.b64encode(buf.getvalue()).decode()
    return f"data:image/jpeg;base64,{b64}", img.size


def natural_sort_key(s):
    return [int(c) if c.isdigit() else c.lower() for c in re.split(r'(\d+)', str(s))]


def build_preview(panels_dir, device_key='kindle'):
    panels_dir = Path(panels_dir)
    device = DEVICES[device_key]

    panel_files = sorted(
        [f for f in panels_dir.iterdir()
         if f.suffix.lower() in {'.jpg', '.jpeg', '.png'} and '_debug' not in f.name],
        key=lambda f: natural_sort_key(f.name)
    )

    if not panel_files:
        print(f"No images found in {panels_dir}")
        sys.exit(1)

    dw, dh = device['width'], device['height']
    # Display at 50% scale for screen viewing
    display_scale = 0.5
    display_w = int(dw * display_scale)
    display_h = int(dh * display_scale)

    slides_html = []
    for i, pf in enumerate(panel_files):
        data_uri, (iw, ih) = image_to_data_uri(pf, dw, dh)
        slides_html.append(f'''
        <div class="slide" id="slide-{i}" style="display:{'flex' if i == 0 else 'none'}">
            <img src="{data_uri}" style="max-width:{display_w}px;max-height:{display_h}px;object-fit:contain;"/>
        </div>''')

    html = f'''<!DOCTYPE html>
<html>
<head>
<title>Preview - {device['name']}</title>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ background:#1a1a1a; color:#fff; font-family:system-ui; display:flex; flex-direction:column; align-items:center; height:100vh; }}
.device-frame {{
    width:{display_w + 20}px; height:{display_h + 20}px;
    border:2px solid #555; border-radius:8px; background:#000;
    display:flex; align-items:center; justify-content:center;
    margin-top:20px; position:relative;
}}
.slide {{ display:flex; align-items:center; justify-content:center; }}
.controls {{
    margin-top:15px; display:flex; gap:15px; align-items:center;
}}
button {{
    background:#333; color:#fff; border:1px solid #555; padding:8px 20px;
    border-radius:4px; cursor:pointer; font-size:14px;
}}
button:hover {{ background:#444; }}
.info {{
    margin-top:10px; font-size:13px; color:#888; text-align:center;
}}
.counter {{ font-size:16px; min-width:80px; text-align:center; }}
.device-label {{
    margin-top:15px; font-size:14px; color:#aaa;
}}
</style>
</head>
<body>
<div class="device-label">{device['name']} ({dw}x{dh} @ {device['ppi']}ppi)</div>
<div class="device-frame">
    {"".join(slides_html)}
</div>
<div class="controls">
    <button onclick="nav(-1)">← Prev</button>
    <span class="counter" id="counter">1 / {len(panel_files)}</span>
    <button onclick="nav(1)">Next →</button>
</div>
<div class="info">
    Arrow keys or click to navigate. Showing {len(panel_files)} panels from {panels_dir.name}
</div>
<script>
let current = 0;
const total = {len(panel_files)};
function nav(dir) {{
    document.getElementById('slide-'+current).style.display = 'none';
    current = Math.max(0, Math.min(total-1, current+dir));
    document.getElementById('slide-'+current).style.display = 'flex';
    document.getElementById('counter').textContent = (current+1)+' / '+total;
}}
document.addEventListener('keydown', e => {{
    if (e.key === 'ArrowRight' || e.key === ' ') nav(1);
    if (e.key === 'ArrowLeft') nav(-1);
}});
</script>
</body>
</html>'''

    preview_path = panels_dir.parent / f"preview_{device_key}.html"
    preview_path.write_text(html)
    webbrowser.open(f"file://{preview_path.resolve()}")
    print(f"Preview opened: {preview_path}")
    print(f"  Device: {device['name']} ({dw}x{dh})")
    print(f"  Panels: {len(panel_files)}")
    return preview_path


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python src/preview.py <panels-directory> [--device kindle|xteink]")
        sys.exit(1)

    target = sys.argv[1]
    device = 'kindle'
    if '--device' in sys.argv:
        idx = sys.argv.index('--device')
        if idx + 1 < len(sys.argv):
            device = sys.argv[idx + 1]

    if device not in DEVICES:
        print(f"Unknown device '{device}'. Available: {', '.join(DEVICES.keys())}")
        sys.exit(1)

    build_preview(Path(target), device)
