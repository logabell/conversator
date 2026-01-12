#!/bin/bash
# Start Conversator voice interface with local microphone (VoxType/Wayland)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Check for required environment variable
if [ -z "$GOOGLE_API_KEY" ]; then
    echo "Error: GOOGLE_API_KEY environment variable not set"
    echo "Export your Gemini API key: export GOOGLE_API_KEY=your-key"
    exit 1
fi

# Check if conversator layer is running
if ! curl -s "http://localhost:8001/health" > /dev/null 2>&1; then
    echo "Warning: Conversator orchestration layer not running"
    echo "Start it with: ./scripts/start-conversator.sh"
    echo ""
    echo "Starting anyway (voice will work but subagents won't)..."
fi

echo "Starting Conversator voice interface (local mic via VoxType)..."
cd "$PROJECT_ROOT"

# Run the Python voice service
python -m conversator_voice --source local
