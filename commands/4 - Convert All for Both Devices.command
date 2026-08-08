#!/bin/bash
# Converts ALL comic files in input/ for BOTH Kindle and XTe Ink
# You get two EPUBs per comic — one optimized for each device
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"
source venv/bin/activate

echo "========================================"
echo "  DUAL DEVICE CONVERTER"
echo "  Converting all comics for Kindle + XTe Ink"
echo "========================================"
echo ""

mkdir -p output

count=0
for file in input/*.cb? input/*.cbz input/*.cbr; do
    [ -f "$file" ] || continue
    count=$((count + 1))
    name="$(basename "$file")"
    echo ""
    echo "════════════════════════════════════════"
    echo "  File $count: $name"
    echo "════════════════════════════════════════"
    echo ""
    echo "  → Kindle version..."
    python src/convert.py "$file" --device kindle
    echo ""
    echo "  → XTe Ink version..."
    python src/convert.py "$file" --device xteink
    echo ""
done

if [ $count -eq 0 ]; then
    echo "⚠  No comic files found in input/"
    echo ""
    echo "  Put your .cbr, .cbz, or .cb7 files in the input/ folder first."
    echo "  Double-click '1 - Open Input Folder' to open it."
fi

echo ""
echo "========================================"
echo "  DONE! Converted $count files for both devices."
echo "  Opening output folder..."
echo "========================================"
open "$PROJECT_DIR/output"
echo ""
read -p "Press Enter to close this window..."
