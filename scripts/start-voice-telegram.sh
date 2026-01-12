#!/bin/bash
# Start Conversator voice interface via Telegram bot

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Check for required environment variables
if [ -z "$GOOGLE_API_KEY" ]; then
    echo "Error: GOOGLE_API_KEY environment variable not set"
    exit 1
fi

if [ -z "$TELEGRAM_BOT_TOKEN" ]; then
    echo "Error: TELEGRAM_BOT_TOKEN environment variable not set"
    echo "Create a Telegram bot via @BotFather and export its token"
    exit 1
fi

# Check if conversator layer is running
if ! curl -s "http://localhost:8001/health" > /dev/null 2>&1; then
    echo "Warning: Conversator orchestration layer not running"
    echo "Start it with: ./scripts/start-conversator.sh"
fi

echo "Starting Conversator voice interface (Telegram bot)..."
cd "$PROJECT_ROOT"

python -m conversator_voice --source telegram --telegram-token "$TELEGRAM_BOT_TOKEN"
