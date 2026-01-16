#!/bin/bash
# Stop the OpenCode builder instance started by scripts/start-builders.sh
#
# Safety: only stops processes referenced by PID files under .conversator/cache.

PROJECT_ROOT="$(dirname "$(dirname "${BASH_SOURCE[0]}")")"
CACHE_DIR="${PROJECT_ROOT}/.conversator/cache"

echo "Stopping OpenCode builder instance..."

stop_by_pid() {
    local pidfile=$1
    local name=$2
    if [ -f "$pidfile" ]; then
        pid=$(cat "$pidfile")
        if kill -0 "$pid" 2>/dev/null; then
            kill "$pid" || true
            echo "  Stopped ${name} (pid ${pid})"
        fi
        rm -f "$pidfile"
    fi
}

# Current builder helper pid
stop_by_pid "${CACHE_DIR}/builder.pid" "opencode-builder"

# Legacy pid files (older helper versions)
stop_by_pid "${CACHE_DIR}/builder-fast.pid" "opencode-fast"
stop_by_pid "${CACHE_DIR}/builder-pro.pid" "opencode-pro"

echo "Done."
