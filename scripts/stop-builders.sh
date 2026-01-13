#!/bin/bash
# Stop OpenCode builder instances

PROJECT_ROOT="$(dirname "$(dirname "${BASH_SOURCE[0]}")")"
CACHE_DIR="${PROJECT_ROOT}/.conversator/cache"

echo "Stopping OpenCode builder instances..."

# Stop by PID file
stop_by_pid() {
    local pidfile=$1
    local name=$2
    if [ -f "$pidfile" ]; then
        pid=$(cat "$pidfile")
        if kill -0 "$pid" 2>/dev/null; then
            kill "$pid"
            echo "  Stopped ${name} (pid ${pid})"
        fi
        rm -f "$pidfile"
    fi
}

stop_by_pid "${CACHE_DIR}/builder-fast.pid" "opencode-fast"
stop_by_pid "${CACHE_DIR}/builder-pro.pid" "opencode-pro"

# Also try to kill any opencode serve processes on the expected ports
pkill -f "opencode serve --port 8002" 2>/dev/null || true
pkill -f "opencode serve --port 8003" 2>/dev/null || true

echo "Done."
