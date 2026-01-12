#!/bin/bash
# Stop Conversator orchestration layer

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

PID_FILE="${PROJECT_ROOT}/.conversator/cache/conversator.pid"

if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if kill -0 "$PID" 2>/dev/null; then
        echo "Stopping Conversator (PID: $PID)..."
        kill "$PID"
        rm "$PID_FILE"
        echo "Stopped."
    else
        echo "Process $PID not running, cleaning up PID file"
        rm "$PID_FILE"
    fi
else
    echo "No PID file found. Conversator may not be running."
    echo "Try: pkill -f 'opencode serve'"
fi
