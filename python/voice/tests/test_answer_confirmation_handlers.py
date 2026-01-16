import tempfile
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from conversator_voice.config import ConversatorConfig
from conversator_voice.handlers import ToolHandler
from conversator_voice.subagent_conversation import SubagentConversationState, SubagentQuestion


@pytest.mark.asyncio
async def test_continue_brainstormer_stages_then_commits_on_ack() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        (root / "calculator").mkdir()

        handler = ToolHandler(
            opencode=AsyncMock(), config=ConversatorConfig(root_project_dir=str(root))
        )

        conv = SubagentConversationState(subagent_name="brainstormer", session_id="sess")
        conv.questions = [
            SubagentQuestion(index=1, text="Who is the target user?"),
            SubagentQuestion(index=2, text="What is the platform?"),
        ]
        handler.session_state.active_subagent_conversation = conv

        first = await handler.handle_continue_brainstormer("Kids")
        assert first["status"] == "needs_input"
        assert conv.questions[0].answered is True
        assert conv.current_question_number == 2


@pytest.mark.asyncio
async def test_final_review_allows_edit_before_send() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        (root / "calculator").mkdir()

        opencode = AsyncMock()

        async def send_to_session(session_id: str, agent: str, message: str):
            assert session_id == "sess"
            assert agent == "brainstormer"
            # Ensure edited answer makes it into the payload.
            assert "Updated platform" in message
            yield {"type": "message", "content": "Thanks!"}

        opencode.send_to_session = send_to_session

        handler = ToolHandler(
            opencode=opencode, config=ConversatorConfig(root_project_dir=str(root))
        )

        conv = SubagentConversationState(subagent_name="brainstormer", session_id="sess")
        conv.questions = [
            SubagentQuestion(index=1, text="Who is the target user?"),
            SubagentQuestion(index=2, text="What is the platform?"),
        ]
        handler.session_state.active_subagent_conversation = conv

        await handler.handle_continue_brainstormer("Kids")
        final = await handler.handle_continue_brainstormer("Web")
        assert final["status"] == "awaiting_confirmation"

        choose = await handler.handle_continue_brainstormer("yes")
        assert "Which question number" in choose["say"]

        which = await handler.handle_continue_brainstormer("2")
        assert "updated answer" in which["say"].lower()

        updated = await handler.handle_continue_brainstormer("Updated platform")
        assert "Any other changes" in updated["say"]

        sent = await handler.handle_continue_brainstormer("no")
        assert sent["status"] == "complete"


@pytest.mark.asyncio
async def test_yes_prefix_with_more_content_is_not_treated_as_ack() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        (root / "calculator").mkdir()

        handler = ToolHandler(
            opencode=AsyncMock(), config=ConversatorConfig(root_project_dir=str(root))
        )

        # Stage a draft that's awaiting a "send it" style acknowledgement.
        from conversator_voice.relay_draft import RelayDraft

        handler.session_state.active_draft = RelayDraft(
            target_subagent="brainstormer",
            topic="calculator app",
            message="I want to brainstorm.",
            stage="awaiting_confirmation",
        )

        handler.handle_send_to_thread = AsyncMock(return_value={"status": "queued"})

        result = await handler.handle_continue_brainstormer("Yes, I want this to be web-based")
        assert result["status"] == "awaiting_confirmation"
        assert handler.handle_send_to_thread.call_count == 0
        assert handler.session_state.active_draft is not None


@pytest.mark.asyncio
async def test_continue_brainstormer_sends_draft_on_no_thats_it() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        (root / "calculator").mkdir()

        opencode = AsyncMock()
        opencode.create_session = AsyncMock(return_value="sess-1")

        handler = ToolHandler(
            opencode=opencode, config=ConversatorConfig(root_project_dir=str(root))
        )
        handler._run_thread_request = AsyncMock(return_value=None)

        first = await handler.handle_engage_brainstormer("calculator app")
        assert first["status"] == "needs_detail"

        second = await handler.handle_continue_brainstormer("No, that's it.")
        assert second["status"] == "queued"
        assert second["subagent"] == "brainstormer"
        assert handler.session_state.active_draft is None
