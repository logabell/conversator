"""Tests for tool handlers - with mocked external services."""

import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

import pytest

from conversator_voice.handlers import ToolHandler
from conversator_voice.state import StateStore
from conversator_voice.models import (
    TaskEvent,
    InboxItem,
    create_task_created_payload,
)
from conversator_voice.prompt_manager import PromptManager


class TestCheckStatusHandler:
    """Tests for handle_check_status."""

    @pytest.fixture
    def temp_db(self):
        """Create temporary database."""
        with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as f:
            yield f.name

    @pytest.fixture
    def state_store(self, temp_db):
        """Create StateStore with temp database."""
        store = StateStore(temp_db)
        yield store
        store.close()

    @pytest.fixture
    def mock_opencode(self):
        """Create mock OpenCode client."""
        client = AsyncMock()
        client.get_status = AsyncMock(return_value={})
        return client

    @pytest.fixture
    def handler(self, mock_opencode, state_store):
        """Create ToolHandler with mocked dependencies."""
        return ToolHandler(opencode=mock_opencode, state=state_store)

    def _add_task(self, state_store, task_id, title, status="draft"):
        """Helper to add a task to state."""
        event = TaskEvent(
            time=datetime.utcnow(),
            type="TaskCreated",
            task_id=task_id,
            payload=create_task_created_payload(title, status)
        )
        state_store.append_event(event)

    @pytest.mark.asyncio
    async def test_status_with_no_tasks(self, handler):
        """Status returns empty when no tasks."""
        result = await handler.handle_check_status()

        assert result["active_count"] == 0
        assert "No active tasks" in result["summary"]

    @pytest.mark.asyncio
    async def test_status_with_one_task(self, handler, state_store):
        """Status reports single active task."""
        self._add_task(state_store, "task-001", "Test Task")

        result = await handler.handle_check_status()

        assert result["active_count"] == 1
        assert "One active task" in result["summary"]
        assert "Test Task" in result["summary"]

    @pytest.mark.asyncio
    async def test_status_with_multiple_tasks(self, handler, state_store):
        """Status reports multiple tasks."""
        self._add_task(state_store, "task-001", "Task One")
        self._add_task(state_store, "task-002", "Task Two")

        result = await handler.handle_check_status()

        assert result["active_count"] == 2
        assert "2 active tasks" in result["summary"]

    @pytest.mark.asyncio
    async def test_status_includes_inbox_count(self, handler, state_store):
        """Status includes unread notification count."""
        self._add_task(state_store, "task-001", "Test Task")
        item = InboxItem(
            summary="Build completed",
            severity="info",
            refs={"task_id": "task-001"}
        )
        state_store.add_inbox_item(item)

        result = await handler.handle_check_status()

        assert result["unread_notifications"] == 1
        assert "unread" in result["summary"].lower()


class TestMemoryHandler:
    """Tests for handle_add_to_memory."""

    @pytest.fixture
    def temp_workspace(self):
        """Create temporary workspace."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / ".conversator"
            workspace.mkdir()
            (workspace / "memory").mkdir()
            yield workspace

    @pytest.fixture
    def handler(self, temp_workspace):
        """Create handler with temp workspace."""
        mock_opencode = AsyncMock()
        handler = ToolHandler(opencode=mock_opencode)
        handler._memory_index_path = temp_workspace / "memory" / "index.yaml"
        handler._atomic_memory_path = temp_workspace / "memory" / "atomic.jsonl"
        return handler

    @pytest.mark.asyncio
    async def test_add_memory_creates_entry(self, handler):
        """Memory entry is saved to JSONL."""
        result = await handler.handle_add_to_memory(
            content="Use TypeScript for new code",
            keywords=["typescript", "language"]
        )

        assert result["saved"] is True

        # Check JSONL file
        content = handler._atomic_memory_path.read_text()
        entry = json.loads(content.strip())
        assert entry["content"] == "Use TypeScript for new code"
        assert "typescript" in entry["keywords"]

    @pytest.mark.asyncio
    async def test_add_memory_updates_index(self, handler):
        """Memory keywords are indexed."""
        await handler.handle_add_to_memory(
            content="Always write tests",
            keywords=["testing", "quality"]
        )

        # Check index file
        import yaml
        index = yaml.safe_load(handler._memory_index_path.read_text())
        assert "testing" in index.get("keywords", {})
        assert "quality" in index.get("keywords", {})

    @pytest.mark.asyncio
    async def test_add_memory_with_importance(self, handler):
        """Memory importance is recorded."""
        await handler.handle_add_to_memory(
            content="Security: Always validate input",
            keywords=["security"],
            importance="high"
        )

        content = handler._atomic_memory_path.read_text()
        entry = json.loads(content.strip())
        assert entry["importance"] == "high"


class TestAutoRouting:
    """Tests for automatic agent routing."""

    @pytest.fixture
    def temp_workspace(self):
        """Create temporary workspace."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            drafts = workspace / ".conversator" / "plans" / "drafts"
            drafts.mkdir(parents=True)
            yield workspace

    @pytest.fixture
    def handler(self):
        """Create handler."""
        mock_opencode = AsyncMock()
        return ToolHandler(opencode=mock_opencode)

    @pytest.mark.asyncio
    async def test_routes_complex_to_claude_code(self, handler, temp_workspace):
        """Complex keywords route to claude-code."""
        plan_file = temp_workspace / ".conversator" / "plans" / "drafts" / "test.md"
        plan_file.write_text("""
        # Architecture Refactor
        Major refactoring of the authentication system.
        This involves security considerations and restructuring.
        """)

        agent = await handler._auto_route(plan_file)

        assert agent == "claude-code"

    @pytest.mark.asyncio
    async def test_routes_simple_to_opencode_fast(self, handler, temp_workspace):
        """Simple tasks route to opencode-fast."""
        plan_file = temp_workspace / ".conversator" / "plans" / "drafts" / "test.md"
        plan_file.write_text("""
        # Add button
        Add a logout button to the header.
        """)

        agent = await handler._auto_route(plan_file)

        assert agent == "opencode-fast"

    @pytest.mark.asyncio
    async def test_routes_large_to_claude_code(self, handler, temp_workspace):
        """Large plans (>5000 chars) route to claude-code."""
        plan_file = temp_workspace / ".conversator" / "plans" / "drafts" / "test.md"
        plan_file.write_text("A" * 5500)  # Over 5000 chars

        agent = await handler._auto_route(plan_file)

        assert agent == "claude-code"

    @pytest.mark.asyncio
    async def test_routes_multi_file_to_claude_code(self, handler, temp_workspace):
        """Tasks with many file refs route to claude-code."""
        plan_file = temp_workspace / ".conversator" / "plans" / "drafts" / "test.md"
        plan_file.write_text("""
        # Multi-file change
        <file path="src/a.ts"><intent>Change A</intent></file>
        <file path="src/b.ts"><intent>Change B</intent></file>
        <file path="src/c.ts"><intent>Change C</intent></file>
        <file path="src/d.ts"><intent>Change D</intent></file>
        <file path="src/e.ts"><intent>Change E</intent></file>
        <file path="src/f.ts"><intent>Change F</intent></file>
        """)

        agent = await handler._auto_route(plan_file)

        assert agent == "claude-code"


class TestInboxHandler:
    """Tests for inbox handlers."""

    @pytest.fixture
    def temp_db(self):
        """Create temporary database."""
        with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as f:
            yield f.name

    @pytest.fixture
    def state_store(self, temp_db):
        """Create StateStore."""
        store = StateStore(temp_db)
        yield store
        store.close()

    @pytest.fixture
    def handler(self, state_store):
        """Create handler with state store."""
        mock_opencode = AsyncMock()
        return ToolHandler(opencode=mock_opencode, state=state_store)

    @pytest.mark.asyncio
    async def test_check_inbox_empty(self, handler):
        """Empty inbox returns appropriate message."""
        result = await handler.handle_check_inbox()

        assert result["count"] == 0
        assert "No notifications" in result["summary"]

    @pytest.mark.asyncio
    async def test_check_inbox_with_items(self, handler, state_store):
        """Inbox returns items grouped by severity."""
        state_store.add_inbox_item(InboxItem(summary="Approval needed", severity="blocking", refs={"task_id": "task-1"}))
        state_store.add_inbox_item(InboxItem(summary="Build failed", severity="error", refs={"task_id": "task-1"}))
        state_store.add_inbox_item(InboxItem(summary="Task completed", severity="info", refs={"task_id": "task-1"}))

        result = await handler.handle_check_inbox()

        assert result["count"] == 3
        assert "blocking" in result["summary"].lower()
        assert "error" in result["summary"].lower()

    @pytest.mark.asyncio
    async def test_acknowledge_all(self, handler, state_store):
        """Acknowledging all clears inbox."""
        state_store.add_inbox_item(InboxItem(summary="Item 1", severity="info", refs={"task_id": "task-1"}))
        state_store.add_inbox_item(InboxItem(summary="Item 2", severity="info", refs={"task_id": "task-1"}))

        result = await handler.handle_acknowledge_inbox()

        assert result["acknowledged"] == 2

        # Verify inbox is empty
        check = await handler.handle_check_inbox()
        assert check["count"] == 0


class TestPlannerSession:
    """Tests for planner engagement."""

    @pytest.fixture
    def mock_opencode(self):
        """Create mock OpenCode client."""
        client = AsyncMock()
        return client

    @pytest.fixture
    def handler(self, mock_opencode):
        """Create handler."""
        return ToolHandler(opencode=mock_opencode)

    @pytest.mark.asyncio
    async def test_engage_planner_returns_questions(self, handler, mock_opencode):
        """Planner returning questions sets needs_input status."""
        async def mock_engage(*args, **kwargs):
            yield {"type": "message", "content": "Where should the button go?"}

        mock_opencode.engage_subagent = mock_engage

        result = await handler.handle_engage_planner("Add logout button")

        assert result["status"] == "needs_input"
        assert "questions" in result

    @pytest.mark.asyncio
    async def test_engage_planner_returns_ready(self, handler, mock_opencode):
        """Planner signaling ready sets ready status."""
        async def mock_engage(*args, **kwargs):
            yield {"type": "message", "content": "Plan written. READY_FOR_BUILDER: logout-button.md"}

        mock_opencode.engage_subagent = mock_engage

        result = await handler.handle_engage_planner("Add logout button")

        assert result["status"] == "ready"
        assert result["plan_file"] == "logout-button.md"


class TestFilenameExtraction:
    """Tests for extracting filename from READY_FOR_BUILDER signal."""

    @pytest.fixture
    def handler(self):
        """Create handler."""
        mock_opencode = AsyncMock()
        return ToolHandler(opencode=mock_opencode)

    def test_extracts_simple_filename(self, handler):
        """Extracts simple filename."""
        content = "Done! READY_FOR_BUILDER: logout-button.md"
        filename = handler._extract_filename(content)
        assert filename == "logout-button.md"

    def test_extracts_filename_with_path(self, handler):
        """Extracts filename even with partial path."""
        content = "READY_FOR_BUILDER: drafts/auth-refactor.md"
        filename = handler._extract_filename(content)
        assert filename == "drafts/auth-refactor.md"

    def test_returns_unknown_if_not_found(self, handler):
        """Returns unknown.md if signal not found."""
        content = "Some other message without the signal"
        filename = handler._extract_filename(content)
        assert filename == "unknown.md"
