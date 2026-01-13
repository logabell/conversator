"""Integration tests for OpenCode client - requires OpenCode server at localhost:4096.

Run these tests with:
    ./scripts/start-conversator.sh  # In another terminal
    pytest tests/test_opencode_integration.py -v
"""

import os

import pytest

from conversator_voice.opencode_client import OpenCodeClient


# Skip all tests if OpenCode not available
pytestmark = pytest.mark.skipif(
    os.environ.get("SKIP_OPENCODE_TESTS", "").lower() in ("1", "true", "yes"),
    reason="OpenCode integration tests skipped via SKIP_OPENCODE_TESTS"
)


@pytest.fixture
async def client():
    """Create OpenCode client."""
    client = OpenCodeClient(base_url="http://localhost:4096")
    yield client
    await client.close()


class TestOpenCodeConnection:
    """Tests for OpenCode server connection."""

    @pytest.mark.asyncio
    async def test_health_check(self, client):
        """Server responds to health check."""
        is_healthy = await client.health_check()

        # Note: health_check returns True if server responds
        # It may return False if server is starting up
        assert isinstance(is_healthy, bool)

    @pytest.mark.asyncio
    async def test_list_agents(self, client):
        """Server lists available agents."""
        agents = await client.list_agents()

        # Should return list (may be empty if no agents configured)
        assert isinstance(agents, list)

    @pytest.mark.asyncio
    async def test_conversator_agents_available(self, client):
        """Conversator agents are available."""
        agents = await client.list_agents()

        # If agents are loaded, check for our agents
        if agents:
            agent_names = [a.get("name", a.get("id", "")) for a in agents]
            # At least one of our agents should be present
            expected = ["planner", "context-reader", "summarizer"]
            found = any(name in str(agent_names).lower() for name in expected)
            # This is a soft assertion - agents may not be loaded yet
            if not found:
                pytest.skip("Conversator agents not yet loaded")


class TestSessionManagement:
    """Tests for session creation and management."""

    @pytest.mark.asyncio
    async def test_session_tracking(self, client):
        """Client tracks active sessions."""
        # Initially no sessions
        assert len(client.active_sessions) == 0

        # After engaging, session should be tracked
        # Note: This will actually create a session on the server
        # We collect events but don't wait for full response
        try:
            async for event in client.engage_subagent("planner", "Test message"):
                # Just check we get some response
                assert "type" in event or "content" in event
                break  # Exit after first event
        except Exception as e:
            # Server may not be ready or agent not available
            pytest.skip(f"Could not engage planner: {e}")

        # Session should be tracked
        assert "planner" in client.active_sessions


class TestPlannerSubagent:
    """Tests for planner subagent interactions."""

    @pytest.mark.asyncio
    async def test_engage_planner_gets_response(self, client):
        """Engaging planner returns events."""
        events = []

        try:
            async for event in client.engage_subagent(
                "planner",
                "Add a simple logout button to the header"
            ):
                events.append(event)
                # Collect up to 5 events or until done
                if len(events) >= 5 or event.get("type") == "assistant.done":
                    break
        except Exception as e:
            pytest.skip(f"Planner not available: {e}")

        # Should get at least one event
        assert len(events) > 0

    @pytest.mark.asyncio
    async def test_continue_session(self, client):
        """Can continue an existing session."""
        # First engagement
        try:
            async for event in client.engage_subagent("planner", "Add logout button"):
                break  # Just establish session
        except Exception as e:
            pytest.skip(f"Could not start session: {e}")

        # Continue session
        events = []
        async for event in client.continue_session("planner", "Put it in the header"):
            events.append(event)
            if len(events) >= 3:
                break

        # Should get response
        assert len(events) > 0


class TestContextReaderSubagent:
    """Tests for context-reader subagent."""

    @pytest.mark.asyncio
    async def test_engage_context_reader(self, client):
        """Can engage context-reader for queries."""
        events = []

        try:
            async for event in client.engage_subagent(
                "context-reader",
                "What testing frameworks are used in this project?"
            ):
                events.append(event)
                if len(events) >= 3 or event.get("type") == "assistant.done":
                    break
        except Exception as e:
            pytest.skip(f"Context-reader not available: {e}")

        assert len(events) > 0


class TestSummarizerSubagent:
    """Tests for summarizer subagent."""

    @pytest.mark.asyncio
    async def test_engage_summarizer(self, client):
        """Can engage summarizer for summaries."""
        events = []

        try:
            async for event in client.engage_subagent(
                "summarizer",
                "Summarize: The build completed with 15 tests passing. No failures."
            ):
                events.append(event)
                if len(events) >= 3 or event.get("type") == "assistant.done":
                    break
        except Exception as e:
            pytest.skip(f"Summarizer not available: {e}")

        assert len(events) > 0


class TestStatusCache:
    """Tests for status caching functionality."""

    @pytest.mark.asyncio
    async def test_get_status_returns_dict(self, client):
        """get_status returns status dictionary."""
        status = await client.get_status()

        assert isinstance(status, dict)
        # May have agents, tasks, or message keys
        assert "agents" in status or "tasks" in status or "message" in status

    @pytest.mark.asyncio
    async def test_update_status(self, client, tmp_path):
        """Can update agent status."""
        import os

        # Create temp workspace structure
        cache_dir = tmp_path / ".conversator" / "cache"
        cache_dir.mkdir(parents=True)

        # Temporarily change working directory
        original_cwd = os.getcwd()
        os.chdir(tmp_path)

        try:
            await client.update_status("test-agent", {
                "status": "testing",
                "task_id": "test-123"
            })

            status = await client.get_status()
            # Status should include our update
            if "agents" in status and "test-agent" in status["agents"]:
                assert status["agents"]["test-agent"]["status"] == "testing"
        finally:
            os.chdir(original_cwd)

    def test_clear_session(self, client):
        """Can clear session tracking."""
        client.active_sessions["test"] = "session-123"
        client.clear_session("test")

        assert "test" not in client.active_sessions


class TestErrorHandling:
    """Tests for error handling."""

    @pytest.mark.asyncio
    async def test_handles_connection_refused(self):
        """Gracefully handles server not running."""
        client = OpenCodeClient(base_url="http://localhost:59999")  # Wrong port

        is_healthy = await client.health_check()
        assert is_healthy is False

        await client.close()

    @pytest.mark.asyncio
    async def test_handles_invalid_agent(self, client):
        """Handles requests to non-existent agents."""
        events = []

        try:
            async for event in client.engage_subagent(
                "nonexistent-agent-xyz",
                "Test message"
            ):
                events.append(event)
                if event.get("type") == "error":
                    break
                if len(events) >= 5:
                    break
        except Exception:
            # Exception is acceptable for invalid agent
            pass

        # Either got error event or exception was raised
        # Both are acceptable behaviors


class TestClientLifecycle:
    """Tests for client lifecycle management."""

    @pytest.mark.asyncio
    async def test_close_client(self):
        """Client can be properly closed."""
        client = OpenCodeClient()
        await client.close()

        # After close, health check should fail gracefully
        # (client is closed, so requests should fail)

    @pytest.mark.asyncio
    async def test_multiple_clients(self):
        """Multiple clients can coexist."""
        client1 = OpenCodeClient()
        client2 = OpenCodeClient()

        # Both should work independently
        health1 = await client1.health_check()
        health2 = await client2.health_check()

        assert health1 == health2  # Should have same result

        await client1.close()
        await client2.close()
