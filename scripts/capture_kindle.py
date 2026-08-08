# capture_kindle.py — Captures screenshots from Kindle Mac app page by page
# Usage: python3 capture_kindle.py [--steps 60] [--output kindle_captures/]
#
# Captures each unique frame as the user navigates forward with Right arrow.
# Saves metadata with step numbers and image hashes for later analysis.
#
# Gotchas:
# - Window position is in points; screencapture -R uses points on retina
# - Need ~1s delay between keypress and capture for Kindle rendering
# - Kindle Mac uses Right arrow for next page (no panel view on desktop)

import subprocess
import time
import json
import hashlib
import sys
import numpy as np
from pathlib import Path
from PIL import Image

def get_kindle_window():
    result = subprocess.run(
        ['osascript', '-e',
         'tell application "System Events" to tell process "Kindle" to get {position, size} of window 1'],
        capture_output=True, text=True
    )
    parts = [int(x.strip()) for x in result.stdout.strip().split(',')]
    return {'x': parts[0], 'y': parts[1], 'w': parts[2], 'h': parts[3]}

def activate_kindle():
    subprocess.run(['osascript', '-e', 'tell application id "com.amazon.Lassen" to activate'], capture_output=True)
    time.sleep(0.5)

def capture_window(win, output_path):
    region = f"{win['x']},{win['y']},{win['w']},{win['h']}"
    subprocess.run(['screencapture', '-x', '-R', region, str(output_path)], capture_output=True)

def press_right():
    subprocess.run(
        ['osascript', '-e', 'tell application "System Events" to tell process "Kindle" to key code 124'],
        capture_output=True
    )

def image_hash(path):
    img = Image.open(path).resize((64, 64)).convert('L')
    return hashlib.md5(img.tobytes()).hexdigest()

def image_similarity(path1, path2):
    """Compare two images by pixel difference ratio. Returns 0.0 (identical) to 1.0 (completely different)."""
    img1 = np.array(Image.open(path1).resize((128, 128)).convert('L'), dtype=float)
    img2 = np.array(Image.open(path2).resize((128, 128)).convert('L'), dtype=float)
    diff = np.abs(img1 - img2).mean() / 255.0
    return diff

def crop_content(img_path, output_path):
    """Crop Kindle window chrome (title bar)."""
    img = Image.open(img_path)
    w, h = img.size
    top = 56  # retina title bar
    cropped = img.crop((0, top, w, h))
    cropped.save(output_path, 'PNG')
    return cropped.size

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--steps', type=int, default=60)
    parser.add_argument('--output', default=None)
    parser.add_argument('--delay', type=float, default=1.0)
    args = parser.parse_args()

    if args.output is None:
        args.output = str(Path(__file__).parent / 'kindle_captures')

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    print("=== Kindle Page Capture Script ===")
    print(f"Output: {output_dir}")
    print(f"Max steps: {args.steps}")

    activate_kindle()
    time.sleep(1)
    win = get_kindle_window()
    print(f"Window: {win}")

    captures = []
    prev_path = None
    frame_num = 0
    consecutive_same = 0

    for step in range(args.steps):
        raw_path = output_dir / f"_raw_{step:04d}.png"
        capture_window(win, raw_path)

        content_path = output_dir / f"_content_{step:04d}.png"
        content_size = crop_content(raw_path, content_path)

        current_hash = image_hash(content_path)

        # Check if content changed from previous
        if prev_path is not None:
            diff = image_similarity(prev_path, content_path)
            if diff < 0.01:  # essentially identical
                consecutive_same += 1
                if consecutive_same >= 3:
                    print(f"\n  No change for 3 steps — end of content. Stopping.")
                    raw_path.unlink(missing_ok=True)
                    content_path.unlink(missing_ok=True)
                    break
                raw_path.unlink(missing_ok=True)
                content_path.unlink(missing_ok=True)
                press_right()
                time.sleep(args.delay)
                continue
            consecutive_same = 0

        # Save with sequential frame number
        final_name = f"frame_{frame_num:03d}.png"
        final_path = output_dir / final_name
        content_path.rename(final_path)
        raw_path.unlink(missing_ok=True)

        # Compute similarity to previous frame for page-boundary detection
        sim_to_prev = None
        if prev_path is not None and prev_path.exists():
            sim_to_prev = image_similarity(prev_path, final_path)

        info = {
            'frame': frame_num,
            'step': step,
            'filename': final_name,
            'size': list(content_size),
            'hash': current_hash,
            'diff_from_prev': round(sim_to_prev, 4) if sim_to_prev is not None else None,
        }
        captures.append(info)

        diff_str = f"  diff={sim_to_prev:.3f}" if sim_to_prev is not None else ""
        print(f"  Frame {frame_num} (step {step}): {content_size[0]}x{content_size[1]}{diff_str}")

        prev_path = final_path
        frame_num += 1

        press_right()
        time.sleep(args.delay)

    # Save metadata
    meta_path = output_dir / 'captures.json'
    with open(meta_path, 'w') as f:
        json.dump({
            'book': 'The Riddler: Year One',
            'source': 'Kindle Unlimited (Mac app)',
            'total_frames': len(captures),
            'captures': captures,
        }, f, indent=2)

    print(f"\n=== Done! {len(captures)} unique frames captured ===")
    print(f"Metadata: {meta_path}")

if __name__ == '__main__':
    main()
