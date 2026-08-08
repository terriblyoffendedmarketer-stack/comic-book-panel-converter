#!/bin/bash
# Analyzes all comics in input/ to check if they're landscape or portrait dominant
# This helps you understand which orientation works best for each book
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"
source venv/bin/activate

echo "========================================"
echo "  ORIENTATION ANALYZER"
echo "  Checking landscape vs portrait for each comic"
echo "========================================"
echo ""

python scripts/analyze_orientation.py --all

echo ""
echo ""
echo "  LANDSCAPE = most panels are wider than tall"
echo "    → book reads better held sideways"
echo ""
echo "  PORTRAIT  = most panels are taller than wide"
echo "    → book reads better held upright"
echo ""
read -p "Press Enter to close this window..."
