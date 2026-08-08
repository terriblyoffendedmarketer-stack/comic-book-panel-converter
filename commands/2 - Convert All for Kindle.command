#!/bin/bash
# Converts ALL comic files in the input/ folder for Kindle Paperwhite
# Output EPUBs go to the output/ folder
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"
source venv/bin/activate

echo "========================================"
echo "  KINDLE CONVERTER"
echo "  Converting all comics in input/"
echo "========================================"
echo ""

mkdir -p output

count=0
for file in input/*.cb? input/*.cbz input/*.cbr; do
    [ -f "$file" ] || continue
    count=$((count + 1))
    echo ""
    echo "────────────────────────────────────────"
    echo "  File $count: $(basename "$file")"
    echo "────────────────────────────────────────"
    python src/convert.py "$file" --device kindle
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
echo "  DONE! Converted $count files."
echo "  Opening output folder..."
echo "========================================"
open "$PROJECT_DIR/output"
echo ""
read -p "Press Enter to close this window..."
