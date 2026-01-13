"""End-to-end workflow tests - requires all services.

Prerequisites:
    - OpenCode running at localhost:4096
    - GOOGLE_API_KEY set

Run these tests with:
    ./scripts/start-conversator.sh  # In another terminal
    export GOOGLE_API_KEY=your-key
    pytest tests/test_e2e_workflow.py -v
"""

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from conversator_voice.state import StateStore
from conversator_voice.models import (
    TaskEvent,
    InboxItem,
    create_task_created_payload,
)
from conversator_voice.handlers import ToolHandler
from conversator_voice.prompt_manager import PromptManager
from conversator_voice.opencode_client import OpenCodeClient


# Skip if missing dependencies
def has_all_dependencies():
    """Check if all external dependencies are available."""
    has_api_key = bool(os.environ.get("GOOGLE_API_KEY"))
    # Note: OpenCode check would require network call
    return has_api_key


pytestmark = pytest.mark.skipif(
    not has_all_dependencies(),
    reason="Missing dependencies (GOOGLE_API_KEY or OpenCode)"
)


class TestStateEventWorkflow:
    """Test complete state event workflow."""

    @pytest.fixture
    def temp_workspace(self):
        """Create temporary workspace."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / ".conversator"
            workspace.mkdir()
            (workspace / "prompts").mkdir()
            (workspace / "memory").mkdir()
            (workspace / "plans" / "drafts").mkdir(parents=True)
            yield workspace

    @pytest.fixture
    def state_store(self, temp_workspace):
        """Create StateStore."""
        store = StateStore(temp_workspace / "state.sqlite")
        yield store
        store.close()

    @pytest.fixture
    def prompt_manager(self, temp_workspace, state_store):
        """Create PromptManager."""
        return PromptManager(temp_workspace, state=state_store)

    @pytest.mark.asyncio
    async def test_task_lifecycle_events(self, state_store):
        """Test complete task lifecycle through events."""
        # 1. Create task
        task = state_store.create_task(
            title="Add logout button",
            working_prompt_path=".conversator/prompts/test/working.md"
        )
        assert task.status == "draft"

        # 2. Get events
        events = state_store.get_events()
        assert len(events) == 1
        assert events[0].type == "TaskCreated"

        # 3. Update status through events
        state_store.update_task_status(
            task.task_id,
            "WorkingPromptUpdated",
            {"path": "working.md"}
        )

        # 4. Task survives restart
        task_id = task.task_id
        state_store.close()

        state_store2 = StateStore(state_store.db_path)
        recovered = state_store2.get_task(task_id)
        assert recovered is not None
        assert recovered.title == "Add logout button"
        state_store2.close()

    @pytest.mark.asyncio
    async def test_inbox_notification_workflow(self, state_store):
        """Test inbox notifications through task workflow."""
        # Create task
        task = state_store.create_task(title="Test Task")

        # Add notifications at different stages
        state_store.add_inbox_item(InboxItem(summary="Task created", severity="info", refs={"task_id": task.task_id}))
        state_store.add_inbox_item(InboxItem(summary="Missing tests", severity="warning", refs={"task_id": task.task_id}))
        state_store.add_inbox_item(InboxItem(summary="Build failed", severity="error", refs={"task_id": task.task_id}))
        state_store.add_inbox_item(InboxItem(summary="Approval needed", severity="blocking", refs={"task_id": task.task_id}))

        # Query unread
        unread = state_store.get_inbox(unread_only=True)
        assert len(unread) == 4

        # Blocking should be first (highest severity)
        assert unread[0].severity == "blocking"

        # Acknowledge one
        state_store.acknowledge_inbox(unread[0].inbox_id)

        # Now 3 unread
        unread = state_store.get_inbox(unread_only=True)
        assert len(unread) == 3


class TestPromptRefinementWorkflow:
    """Test prompt refinement through conversation."""

    @pytest.fixture
    def temp_workspace(self):
        """Create temporary workspace."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / ".conversator"
            workspace.mkdir()
            (workspace / "prompts").mkdir()
            (workspace / "memory").mkdir()
            yield workspace

    @pytest.fixture
    def prompt_manager(self, temp_workspace):
        """Create PromptManager."""
        return PromptManager(temp_workspace)

    @pytest.mark.asyncio
    async def test_incremental_prompt_refinement(self, prompt_manager):
        """Test building prompt through multiple updates."""
        task_id = "refine-test-12345678"

        # Initial task description
        await prompt_manager.init_working_prompt(task_id, "Add feature")

        # First refinement: clarify goal
        await prompt_manager.update_working_prompt(
            task_id,
            title="Add logout button",
            intent="Allow users to log out from the main navigation"
        )

        # Second refinement: add requirements
        await prompt_manager.update_working_prompt(
            task_id,
            requirements=["Clear session cookies", "Redirect to login page"]
        )

        # Third refinement: add constraints
        await prompt_manager.update_working_prompt(
            task_id,
            constraints=["Don't modify existing auth service"],
            context="User is authenticated via JWT stored in cookies"
        )

        # Check final state
        summary = prompt_manager.get_working_summary(task_id)
        assert "Add logout button" in summary
        assert "2 requirements" in summary
        assert "1 constraints" in summary

    @pytest.mark.asyncio
    async def test_freeze_generates_handoff_files(self, prompt_manager, temp_workspace):
        """Test freezing prompt creates both handoff files."""
        task_id = "freeze-test-12345678"

        # Build up prompt
        await prompt_manager.init_working_prompt(task_id, "Test Task")
        await prompt_manager.update_working_prompt(
            task_id,
            intent="Test freezing workflow",
            requirements=["Requirement 1", "Requirement 2"]
        )

        # Freeze
        md_path, json_path = await prompt_manager.freeze_to_handoff(task_id)

        # Check handoff.md structure
        md_content = md_path.read_text()
        assert "<task>" in md_content
        assert "<goal>" in md_content
        assert "<definition_of_done>" in md_content
        assert "<constraints>" in md_content
        assert "<gates>" in md_content

        # Check handoff.json structure
        json_content = json.loads(json_path.read_text())
        assert json_content["goal"] == "Test freezing workflow"
        assert len(json_content["definition_of_done"]) == 2
        assert "gates_required" in json_content


class TestHandlerIntegration:
    """Test handlers with mocked external services."""

    @pytest.fixture
    def temp_workspace(self):
        """Create temporary workspace."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / ".conversator"
            workspace.mkdir()
            (workspace / "prompts").mkdir()
            (workspace / "memory").mkdir()
            (workspace / "plans" / "drafts").mkdir(parents=True)
            yield workspace

    @pytest.fixture
    def state_store(self, temp_workspace):
        """Create StateStore."""
        store = StateStore(temp_workspace / "state.sqlite")
        yield store
        store.close()

    @pytest.fixture
    def prompt_manager(self, temp_workspace, state_store):
        """Create PromptManager."""
        return PromptManager(temp_workspace, state=state_store)

    @pytest.fixture
    def mock_opencode(self):
        """Create mock OpenCode client."""
        client = AsyncMock(spec=OpenCodeClient)
        client.get_status = AsyncMock(return_value={"agents": {}})
        return client

    @pytest.fixture
    def handler(self, mock_opencode, state_store, prompt_manager, temp_workspace):
        """Create ToolHandler."""
        handler = ToolHandler(
            opencode=mock_opencode,
            state=state_store,
            prompt_manager=prompt_manager
        )
        handler._memory_index_path = temp_workspace / "memory" / "index.yaml"
        handler._atomic_memory_path = temp_workspace / "memory" / "atomic.jsonl"
        return handler

    @pytest.mark.asyncio
    async def test_full_status_check(self, handler, state_store):
        """Test status check aggregates all sources."""
        # Create some tasks
        state_store.create_task(title="Task 1")
        state_store.create_task(title="Task 2")

        # Add inbox item
        tasks = state_store.get_active_tasks()
        state_store.add_inbox_item(InboxItem(summary="Test notification", severity="info", refs={"task_id": tasks[0].task_id}))

        # Check status
        result = await handler.handle_check_status()

        assert result["active_count"] == 2
        assert result["unread_notifications"] == 1
        assert "2 active tasks" in result["summary"]

    @pytest.mark.asyncio
    async def test_memory_and_retrieval(self, handler):
        """Test saving and retrieving memory."""
        # Save memory
        result = await handler.handle_add_to_memory(
            content="Always use TypeScript for new code",
            keywords=["typescript", "coding-standards"]
        )
        assert result["saved"] is True

        # Check file exists
        content = handler._atomic_memory_path.read_text()
        entry = json.loads(content.strip())
        assert "TypeScript" in entry["content"]
        assert "typescript" in entry["keywords"]


class TestCompleteWorkflow:
    """Test complete voice → handoff workflow."""

    @pytest.fixture
    def temp_workspace(self):
        """Create temporary workspace."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / ".conversator"
            workspace.mkdir()
            (workspace / "prompts").mkdir()
            (workspace / "memory").mkdir()
            (workspace / "plans" / "drafts").mkdir(parents=True)
            (workspace / "plans" / "active").mkdir()
            yield workspace

    @pytest.mark.asyncio
    async def test_voice_to_handoff_flow(self, temp_workspace):
        """Simulate complete voice → planner → handoff flow."""
        # Initialize components
        state = StateStore(temp_workspace / "state.sqlite")
        prompt_manager = PromptManager(temp_workspace, state=state)

        mock_opencode = AsyncMock()

        # Simulate planner responses - first call returns questions, second returns ready
        call_count = [0]

        async def mock_engage(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                # First call: planner asks questions
                yield {"type": "message", "content": "Where should the button go?"}
            else:
                # Second call: planner signals ready
                yield {"type": "message", "content": "READY_FOR_BUILDER: logout-button.md"}

        mock_opencode.engage_subagent = mock_engage
        mock_opencode.continue_session = mock_engage
        mock_opencode.get_status = AsyncMock(return_value={})

        handler = ToolHandler(
            opencode=mock_opencode,
            state=state,
            prompt_manager=prompt_manager
        )

        # 1. Create task (simulates voice: "I want to add a logout button")
        task = state.create_task(title="Voice Session")
        handler.current_task_id = task.task_id

        # 2. Initialize working prompt
        await prompt_manager.init_working_prompt(task.task_id, "Add logout button")

        # 3. Engage planner - first call asks questions
        result = await handler.handle_engage_planner(
            task_description="Add a logout button to the application"
        )

        # Planner asks questions
        assert result["status"] == "needs_input"
        assert "questions" in result

        # 4. User answers (simulates voice response)
        await prompt_manager.update_working_prompt(
            task.task_id,
            intent="Add logout button to header",
            requirements=["In the header", "Clear session on click"]
        )

        # 5. Continue planner - second call signals ready
        result2 = await handler.handle_engage_planner(
            task_description="In the header, clear session on click"
        )
        assert result2["status"] == "ready"

        # 6. Freeze to handoff
        md_path, json_path = await prompt_manager.freeze_to_handoff(task.task_id)

        # Verify handoff files
        assert md_path.exists()
        assert json_path.exists()

        # Verify handoff content
        json_content = json.loads(json_path.read_text())
        assert json_content["goal"] == "Add logout button to header"
        assert "In the header" in json_content["definition_of_done"]

        # 7. Verify state reflects workflow
        events = state.get_events()
        event_types = [e.type for e in events]
        assert "TaskCreated" in event_types

        state.close()


class TestCrashRecovery:
    """Test state recovery after crash."""

    @pytest.fixture
    def temp_db(self):
        """Create temporary database path."""
        with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as f:
            yield f.name

    @pytest.mark.asyncio
    async def test_task_survives_crash(self, temp_db):
        """Task state survives process crash and restart."""
        # Session 1: Create task and update
        state1 = StateStore(temp_db)
        task = state1.create_task(title="Crash Test Task")
        task_id = task.task_id

        state1.add_inbox_item(InboxItem(summary="Test notification", severity="info", refs={"task_id": task_id}))
        state1.update_task_status(task_id, "WorkingPromptUpdated", {"path": "test.md"})

        # Simulate crash (no clean close)
        state1.conn.close()

        # Session 2: Recover
        state2 = StateStore(temp_db)

        # Task should be recovered
        recovered = state2.get_task(task_id)
        assert recovered is not None
        assert recovered.title == "Crash Test Task"

        # Inbox should be recovered
        inbox = state2.get_inbox()
        assert len(inbox) == 1
        assert inbox[0].summary == "Test notification"

        # Events should be recovered
        events = state2.get_events()
        assert len(events) >= 1

        state2.close()

    @pytest.mark.asyncio
    async def test_partial_workflow_recovery(self, temp_db):
        """Partial workflow state can be recovered."""
        # Session 1: Start workflow
        state1 = StateStore(temp_db)
        task = state1.create_task(title="Partial Workflow")
        task_id = task.task_id

        # Add some progress events
        state1.update_task_status(task_id, "WorkingPromptUpdated", {"v": 1})
        state1.update_task_status(task_id, "QuestionsRaised", {"questions": ["Q1"]})
        state1.update_task_status(task_id, "UserAnswered", {"answer": "A1"})

        state1.conn.close()  # Crash

        # Session 2: Recover and continue
        state2 = StateStore(temp_db)

        # All events should be recovered
        events = state2.get_events(task_id=task_id)
        event_types = [e.type for e in events]

        assert "TaskCreated" in event_types
        assert "WorkingPromptUpdated" in event_types
        assert "QuestionsRaised" in event_types
        assert "UserAnswered" in event_types

        state2.close()
