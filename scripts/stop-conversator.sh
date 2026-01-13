#!/bin/bash
# Stop Conversator orchestration layer

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

PID_FILE="${PROJECT_ROOT}/.conversator/cache/conversator.pid"
PORT="${CONVERSATOR_PORT:-4096}"

if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if kill -0 "$PID" 2>/dev/null; then
        echo "Stopping Conversator (PID: $PID)..."

        # Send SIGTERM for graceful shutdown
        kill "$PID"

        # Wait up to 5 seconds for graceful shutdown
        echo "Waiting for graceful shutdown..."
        for i in {1..5}; do
            if ! kill -0 "$PID" 2>/dev/null; then
                echo "Process terminated gracefully."
                break
            fi
            sleep 1
        done

        # If still running, force kill
        if kill -0 "$PID" 2>/dev/null; then
            echo "Process still running, sending SIGKILL..."
            kill -9 "$PID"
            sleep 1
        fi

        rm -f "$PID_FILE"

        # Wait for port to be released (up to 10 seconds)
        echo "Waiting for port $PORT to be released..."
        for i in {1..10}; do
            if ! nc -z localhost "$PORT" 2>/dev/null; then
                echo "Port $PORT released."
                break
            fi
            if [ "$i" -eq 10 ]; then
                echo "Warning: Port $PORT may still be in TIME_WAIT state."
            fi
            sleep 1
        done

        echo "Stopped."
    else
        echo "Process $PID not running, cleaning up PID file"
        rm -f "$PID_FILE"
    fi
else
    echo "No PID file found. Conversator may not be running."
    echo "Try: pkill -f 'opencode serve'"
fi
