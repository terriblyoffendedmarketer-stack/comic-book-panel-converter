#!/bin/bash
# Opens the input folder where you drop your comic files
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$PROJECT_DIR/input"
open "$PROJECT_DIR/input"
