#!/bin/bash
# Launch the Comic Book Converter web interface
# Double-click this file to start the converter in your browser.

cd "$(dirname "$0")/.."
PROJECT_DIR="$(pwd)"

# Check for virtual environment
if [ ! -d "venv" ]; then
    echo "Virtual environment not found. Run '0 - First Time Setup.command' first."
    read -p "Press Enter to close..."
    exit 1
fi

source venv/bin/activate

# Install flask if missing
pip show flask > /dev/null 2>&1 || pip install flask > /dev/null 2>&1

# Create input/output dirs
mkdir -p input output

echo ""
echo "  ================================="
echo "  Comic Book Converter"
echo "  ================================="
echo ""
echo "  Opening in your browser..."
echo "  To stop: close this window or press Ctrl+C"
echo ""

# Open browser after a short delay (server needs a moment to start)
(sleep 1 && open http://localhost:8080) &

# Start the web app
python src/web_app.py
