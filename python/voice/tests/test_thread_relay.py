import tempfile
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from conversator_voice.config import ConversatorConfig
from conversator_voice.handlers import ToolHandler
from conversator_voice.state import StateStore
from conversator_voice.subagent_conversation import SubagentConversationState, SubagentQuestion


@pytest.mark.asyncio
async def test_thread_response_autopens_questions_when_foreground() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        (root / "calculator").mkdir()

        opencode = AsyncMock()

        async def send_to_session(session_id: str, subagent: str, message: str):
            assert session_id == "sess-1"
            assert subagent == "brainstormer"
            assert message == "hello"
            yield {
                "type": "message",
                "content": "1. Who is the target user?\n2. What is the platform?",
            }

        opencode.send_to_session = send_to_session

        state = StateStore(root / "state.sqlite")
        try:
            handler = ToolHandler(
                opencode=opencode,
                state=state,
                config=ConversatorConfig(root_project_dir=str(root)),
            )

            thread = handler.session_state.create_thread(
                subagent="brainstormer",
                topic="calculator",
                session_id="sess-1",
                focus=True,
            )

            await handler._run_thread_request(thread.thread_id, "hello")

            conv = handler.session_state.active_subagent_conversation
            assert conv is not None
            assert conv.subagent_name == "brainstormer"
            assert conv.total_questions == 2

            # Foreground threads should not create unread notifications.
            assert state.get_inbox(unread_only=True) == []
            assert len(state.get_inbox(unread_only=False)) == 1

            assert thread.status == "awaiting_user"

            pending = handler.session_state.pop_announcement()
            assert pending is not None
            assert "2 questions" in pending.text
            assert "First question" in pending.text
        finally:
            state.close()


@pytest.mark.asyncio
async def test_thread_response_with_questions_stays_in_inbox_when_busy() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        (root / "calculator").mkdir()

        opencode = AsyncMock()

        async def send_to_session(session_id: str, subagent: str, message: str):
            yield {
                "type": "message",
                "content": "1. Who is the target user?\n2. What is the platform?",
            }

        opencode.send_to_session = send_to_session

        state = StateStore(root / "state.sqlite")
        try:
            handler = ToolHandler(
                opencode=opencode,
                state=state,
                config=ConversatorConfig(root_project_dir=str(root)),
            )

            thread = handler.session_state.create_thread(
                subagent="brainstormer",
                topic="calculator",
                session_id="sess-1",
                focus=True,
            )

            # Simulate being in the middle of another foreground Q&A.
            handler.session_state.active_subagent_conversation = SubagentConversationState(
                subagent_name="planner",
                session_id="sess-other",
                questions=[SubagentQuestion(index=1, text="What is the goal?")],
            )

            await handler._run_thread_request(thread.thread_id, "hello")

            conv = handler.session_state.active_subagent_conversation
            assert conv is not None
            assert conv.subagent_name == "planner"

            # Background threads should create unread notifications.
            assert len(state.get_inbox(unread_only=True)) == 1

            assert thread.status == "has_response"

            pending = handler.session_state.pop_announcement()
            assert pending is not None
            assert "It's in your inbox" in pending.text
        finally:
            state.close()
