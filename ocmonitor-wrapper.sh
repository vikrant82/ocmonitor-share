#!/bin/bash
# OpenCode Monitor Global Wrapper Script
# This script allows ocmonitor to be run from anywhere without activating the virtual environment

# Get the directory where this script is located (the project directory)
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Path to the virtual environment's ocmonitor
OCMONITOR_SCRIPT="$PROJECT_DIR/venv/bin/ocmonitor"

# Check if ocmonitor exists
if [ ! -f "$OCMONITOR_SCRIPT" ]; then
    echo "Error: ocmonitor not found at $OCMONITOR_SCRIPT"
    echo "Please run install.sh from the project directory"
    exit 1
fi

# Execute ocmonitor with all arguments passed to this script
exec "$OCMONITOR_SCRIPT" "$@"
