#!/bin/bash
# Removes the auto-start service for the Comic Book Converter.
# Double-click this file to uninstall.

PLIST_NAME="com.comicconverter.webapp"
PLIST_PATH="$HOME/Library/LaunchAgents/${PLIST_NAME}.plist"

if [ -f "$PLIST_PATH" ]; then
    launchctl unload "$PLIST_PATH" 2>/dev/null
    rm "$PLIST_PATH"
    echo ""
    echo "  Auto-start removed."
    echo "  The converter will no longer start on login."
    echo ""
else
    echo ""
    echo "  Auto-start was not installed."
    echo ""
fi

read -p "Press Enter to close..."
