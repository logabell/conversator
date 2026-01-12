#!/bin/bash
# Initialize the .conversator workspace directory structure
# This script is idempotent - safe to run multiple times
#
# Directory structure:
# - conversator/agents/     Version-controlled agents (tracked in git)
# - .conversator/           Runtime state (partially gitignored)
# - .conversator/opencode/  Isolated OpenCode config (fully gitignored)

set -e

WORKSPACE_ROOT="${1:-.conversator}"
AGENTS_SOURCE="conversator/agents"

echo "Initializing Conversator workspace at $WORKSPACE_ROOT"

# Create runtime directory structure
mkdir -p "$WORKSPACE_ROOT/prompts"
mkdir -p "$WORKSPACE_ROOT/plans/drafts"
mkdir -p "$WORKSPACE_ROOT/plans/active"
mkdir -p "$WORKSPACE_ROOT/plans/completed"
mkdir -p "$WORKSPACE_ROOT/cache/completions"
mkdir -p "$WORKSPACE_ROOT/memory/episodic"
mkdir -p "$WORKSPACE_ROOT/scratchpad"

# Create isolated OpenCode config directory (runtime only, gitignored)
mkdir -p "$WORKSPACE_ROOT/opencode/agent"

# Initialize JSON files if they don't exist
if [ ! -f "$WORKSPACE_ROOT/cache/agent-status.json" ]; then
    echo '{"agents": {}, "updated_at": null}' > "$WORKSPACE_ROOT/cache/agent-status.json"
fi

if [ ! -f "$WORKSPACE_ROOT/memory/index.yaml" ]; then
    cat > "$WORKSPACE_ROOT/memory/index.yaml" << 'EOF'
# Memory index - keyword to file/topic mappings
# Format: keyword: [file1, file2, ...]
keywords: {}
files: {}
EOF
fi

if [ ! -f "$WORKSPACE_ROOT/memory/atomic.jsonl" ]; then
    touch "$WORKSPACE_ROOT/memory/atomic.jsonl"
fi

if [ ! -f "$WORKSPACE_ROOT/scratchpad/checklist.md" ]; then
    cat > "$WORKSPACE_ROOT/scratchpad/checklist.md" << 'EOF'
# Conversator Checklist

## Active Tasks
<!-- Tasks currently being worked on -->

## Ideas
<!-- Captured ideas and notes -->

## Blocked
<!-- Tasks waiting on something -->
EOF
fi

if [ ! -f "$WORKSPACE_ROOT/scratchpad/ideas.md" ]; then
    cat > "$WORKSPACE_ROOT/scratchpad/ideas.md" << 'EOF'
# Ideas & Notes

<!-- Captured during conversation, to be processed later -->
EOF
fi

# Sync version-controlled agents to runtime OpenCode directory
if [ -d "$AGENTS_SOURCE" ]; then
    echo "Syncing agents from $AGENTS_SOURCE to $WORKSPACE_ROOT/opencode/agent/"
    cp "$AGENTS_SOURCE"/*.md "$WORKSPACE_ROOT/opencode/agent/" 2>/dev/null || true
else
    echo "Warning: Version-controlled agents not found at $AGENTS_SOURCE"
    echo "  Expected: conversator/agents/*.md"
fi

echo ""
echo "Workspace initialized successfully!"
echo ""
echo "Directory structure:"
find "$WORKSPACE_ROOT" -type d | head -20
echo ""
echo "Runtime agents (copied from $AGENTS_SOURCE):"
ls -la "$WORKSPACE_ROOT/opencode/agent/" 2>/dev/null || echo "  (none yet)"
