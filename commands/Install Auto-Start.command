#!/bin/bash
# Installs a launchd service so the Comic Book Converter starts on login.
# After running, the app is always available at http://localhost:8080
# Double-click this file to install.

cd "$(dirname "$0")/.."
PROJECT_DIR="$(pwd)"
PLIST_NAME="com.comicconverter.webapp"
PLIST_PATH="$HOME/Library/LaunchAgents/${PLIST_NAME}.plist"

if [ ! -d "venv" ]; then
    echo "Virtual environment not found. Run setup first."
    read -p "Press Enter to close..."
    exit 1
fi

# Create the launchd plist
cat > "$PLIST_PATH" << PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${PLIST_NAME}</string>
    <key>ProgramArguments</key>
    <array>
        <string>${PROJECT_DIR}/venv/bin/python</string>
        <string>${PROJECT_DIR}/src/web_app.py</string>
    </array>
    <key>WorkingDirectory</key>
    <string>${PROJECT_DIR}</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>${PROJECT_DIR}/logs/web_app.log</string>
    <key>StandardErrorPath</key>
    <string>${PROJECT_DIR}/logs/web_app.err</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PORT</key>
        <string>8080</string>
    </dict>
</dict>
</plist>
PLIST

mkdir -p "${PROJECT_DIR}/logs"

# Load the service
launchctl unload "$PLIST_PATH" 2>/dev/null
launchctl load "$PLIST_PATH"

echo ""
echo "  ================================="
echo "  Auto-start installed!"
echo "  ================================="
echo ""
echo "  The converter now starts on login."
echo "  Open http://localhost:8080 anytime."
echo ""
echo "  To stop: double-click 'Uninstall Auto-Start.command'"
echo ""
read -p "Press Enter to close..."
