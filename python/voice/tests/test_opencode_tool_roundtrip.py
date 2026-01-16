"""Opt-in tests for Conversator tool calls hitting OpenCode.

These are meant for manual debugging of Conversator's OpenCode relay layer
WITHOUT running Gemini Live.

Run:
    ./scripts/start-conversator.sh  # in another terminal
    cd python/voice
    RUN_OPENCODE_TESTS=1 pytest -q -k opencode_tool_roundtrip -s
"""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path

import pytest

from conversator_voice.config import ConversatorConfig
from conversator_voice.handlers import ToolHandler
from conversator_voice.opencode_client import OpenCodeClient


pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_OPENCODE_TESTS", "").lower() not in ("1", "true", "yes"),
    reason="Set RUN_OPENCODE_TESTS=1 to run OpenCode tool round-trip tests",
)


async def _wait_for_thread_completion(handler: ToolHandler, thread_id: str, timeout_s: float = 45.0):
    start = time.monotonic()
    while time.monotonic() - start < timeout_s:
        thread = handler.session_state.get_thread(thread_id)
        assert thread is not None

        if thread.status in ("has_response", "awaiting_user", "error"):
            return thread

        await asyncio.sleep(0.1)

    raise AssertionError(f"Timed out waiting for thread {thread_id} to complete")


@pytest.mark.asyncio
async def test_send_to_thread_roundtrip_gets_response_and_announcement(tmp_path: Path) -> None:
    client = OpenCodeClient(base_url="http://localhost:4096")
    try:
        if not await client.health_check():
            pytest.skip("OpenCode server not reachable at http://localhost:4096")

        handler = ToolHandler(
            opencode=client,
            config=ConversatorConfig(root_project_dir=str(tmp_path)),
        )

        result = await handler.handle_send_to_thread(
            message=(
                "Reply with 1-2 short sentences about UX for a calculator app. "
                "Do not ask questions."
            ),
            create_new_thread=True,
            subagent="brainstormer",
            topic="calculator",
            focus=True,
        )

        assert result["status"] == "queued"
        thread_id = result["thread_id"]

        thread = await _wait_for_thread_completion(handler, thread_id)
        assert thread.last_response is not None
        assert thread.last_response.strip()

        pending = handler.session_state.pop_announcement()
        assert pending is not None
        assert pending.kind == "response_ready"
    finally:
        await client.close()
