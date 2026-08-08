#!/bin/bash
# ONE-TIME SETUP — Run this once before using the converter for the first time
# Installs all the tools and libraries the converter needs
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

echo "========================================"
echo "  FIRST TIME SETUP"
echo "  Installing everything the converter needs"
echo "========================================"
echo ""

# Create virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
    echo "Creating Python environment..."
    python3 -m venv venv
    echo "  Done."
    echo ""
fi

source venv/bin/activate

echo "Installing Python packages..."
pip3 install -r requirements.txt 2>&1 | tail -5
echo "  Done."
echo ""

echo "Installing system tools (may ask for your password)..."
brew install p7zip unar 2>&1 | tail -3
echo ""

# Create the 7zz symlink that KCC needs
if [ -f /opt/homebrew/bin/7z ] && [ ! -f /opt/homebrew/bin/7zz ]; then
    ln -sf /opt/homebrew/bin/7z /opt/homebrew/bin/7zz
    echo "  Created 7zz symlink for KCC."
fi

# Create input and output folders
mkdir -p input output

echo ""
echo "========================================"
echo "  SETUP COMPLETE!"
echo ""
echo "  Next steps:"
echo "  1. Double-click '1 - Open Input Folder'"
echo "  2. Drop your .cbr / .cbz / .cb7 files in there"
echo "  3. Double-click a converter (2, 3, or 4)"
echo "  4. Grab your EPUBs from the output folder"
echo "========================================"
echo ""
read -p "Press Enter to close this window..."
