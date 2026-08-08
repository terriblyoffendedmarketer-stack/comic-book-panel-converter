#!/bin/bash
# Opens the output folder where your converted EPUBs are saved
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$PROJECT_DIR/output"
open "$PROJECT_DIR/output"
