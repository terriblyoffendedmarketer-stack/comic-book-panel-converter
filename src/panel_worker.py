# panel_worker.py — Subprocess worker for parallel panel detection
# Usage: echo '{"pages": [...], "manga": false}' | python src/panel_worker.py
# Reads JSON from stdin, outputs JSON results to stdout.
# Designed to be spawned by web_app.py for parallel processing.

import json
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
from detect_panels import detect_panels
from pathlib import Path


def main():
    data = json.loads(sys.stdin.read())
    pages = data["pages"]
    manga = data.get("manga", False)

    results = {}
    for page_path in pages:
        panels = detect_panels(Path(page_path), manga=manga)
        results[page_path] = panels

    json.dump(results, sys.stdout)


if __name__ == "__main__":
    main()
