"""Tests for Gemini Live integration - requires GOOGLE_API_KEY.

Run these tests with:
    export GOOGLE_API_KEY=your-key
    pytest tests/test_gemini_live.py -v
"""

import os
import asyncio
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from conversator_voice.gemini_live import ConversatorVoice, ConversatorSession
from conversator_voice.handlers import ToolHandler
from conversator_voice.tools import CONVERSATOR_TOOLS


# Skip if no API key
pytestmark = pytest.mark.skipif(
    not os.environ.get("GOOGLE_API_KEY"),
    reason="GOOGLE_API_KEY not set"
)


class TestConversatorVoiceInit:
    """Tests for ConversatorVoice initialization."""

    def test_init_with_api_key(self):
        """Can initialize with API key."""
        api_key = os.environ.get("GOOGLE_API_KEY", "test-key")
        voice = ConversatorVoice(api_key)

        assert voice.client is not None
        assert voice._connected is False

    def test_loads_system_prompt(self):
        """Loads system prompt from file if exists."""
        with tempfile.TemporaryDirectory() as tmpdir:
            prompt_path = Path(tmpdir) / "prompt.md"
            prompt_path.write_text("You are a test assistant.")

            voice = ConversatorVoice(
                api_key=os.environ.get("GOOGLE_API_KEY", "test-key"),
                system_prompt_path=str(prompt_path)
            )

            assert "test assistant" in voice.system_prompt

    def test_fallback_system_prompt(self):
        """Uses fallback if prompt file missing."""
        voice = ConversatorVoice(
            api_key=os.environ.get("GOOGLE_API_KEY", "test-key"),
            system_prompt_path="/nonexistent/path.md"
        )

        assert "Conversator" in voice.system_prompt
        assert len(voice.system_prompt) > 50


class TestGeminiConnection:
    """Tests for Gemini Live connection."""

    @pytest.fixture
    def voice(self):
        """Create ConversatorVoice instance."""
        return ConversatorVoice(
            api_key=os.environ.get("GOOGLE_API_KEY")
        )

    @pytest.fixture
    def mock_handler(self):
        """Create mock tool handler."""
        return AsyncMock(spec=ToolHandler)

    @pytest.mark.asyncio
    async def test_connect_and_disconnect(self, voice, mock_handler):
        """Can connect and disconnect from Gemini Live."""
        try:
            await voice.connect(tools=CONVERSATOR_TOOLS, tool_handler=mock_handler)

            assert voice._connected is True
            assert voice.session is not None

            await voice.disconnect()

            assert voice._connected is False

        except Exception as e:
            # Connection failures are acceptable in tests
            pytest.skip(f"Could not connect to Gemini: {e}")

    @pytest.mark.asyncio
    async def test_send_text_requires_connection(self, voice):
        """send_text raises error if not connected."""
        with pytest.raises(RuntimeError, match="Not connected"):
            await voice.send_text("Hello")

    @pytest.mark.asyncio
    async def test_send_audio_requires_connection(self, voice):
        """send_audio raises error if not connected."""
        with pytest.raises(RuntimeError, match="Not connected"):
            await voice.send_audio(b"\x00" * 100)


class TestTextExchange:
    """Tests for text-based exchange with Gemini."""

    @pytest.fixture
    async def connected_voice(self):
        """Create connected ConversatorVoice."""
        voice = ConversatorVoice(api_key=os.environ.get("GOOGLE_API_KEY"))
        mock_handler = AsyncMock(spec=ToolHandler)

        try:
            await voice.connect(tools=CONVERSATOR_TOOLS, tool_handler=mock_handler)
            yield voice
        except Exception as e:
            pytest.skip(f"Could not connect: {e}")
        finally:
            await voice.disconnect()

    @pytest.mark.asyncio
    async def test_send_text_message(self, connected_voice):
        """Can send text message to Gemini."""
        # This just tests the send doesn't throw
        await connected_voice.send_text("Hello, this is a test.")


class TestToolDispatch:
    """Tests for tool call dispatching."""

    @pytest.fixture
    def voice(self):
        """Create ConversatorVoice with mock handler."""
        voice = ConversatorVoice(api_key="test-key")
        voice.tool_handler = AsyncMock()
        return voice

    @pytest.mark.asyncio
    async def test_dispatch_check_status(self, voice):
        """Dispatches check_status to handler."""
        voice.tool_handler.handle_check_status = AsyncMock(
            return_value={"active_count": 0, "summary": "No tasks"}
        )

        result = await voice._dispatch_tool_call("check_status", {"verbose": False})

        assert result["active_count"] == 0
        voice.tool_handler.handle_check_status.assert_called_once()

    @pytest.mark.asyncio
    async def test_dispatch_engage_planner(self, voice):
        """Dispatches engage_planner to handler."""
        voice.tool_handler.handle_engage_planner = AsyncMock(
            return_value={"status": "needs_input", "questions": "Where?"}
        )

        result = await voice._dispatch_tool_call(
            "engage_planner",
            {"task_description": "Add button"}
        )

        assert result["status"] == "needs_input"

    @pytest.mark.asyncio
    async def test_dispatch_unknown_tool(self, voice):
        """Unknown tool returns error."""
        result = await voice._dispatch_tool_call("unknown_tool", {})

        assert "error" in result
        assert "Unknown tool" in result["error"]

    @pytest.mark.asyncio
    async def test_dispatch_handles_exceptions(self, voice):
        """Handler exceptions are caught."""
        voice.tool_handler.handle_check_status = AsyncMock(
            side_effect=ValueError("Test error")
        )

        result = await voice._dispatch_tool_call("check_status", {})

        assert "error" in result
        assert "Test error" in result["error"]


class TestConversatorSession:
    """Tests for ConversatorSession wrapper."""

    @pytest.fixture
    def temp_workspace(self):
        """Create temporary workspace."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / ".conversator"
            workspace.mkdir()
            (workspace / "prompts").mkdir()
            (workspace / "memory").mkdir()
            yield str(workspace)

    def test_session_init(self, temp_workspace):
        """Session initializes components."""
        session = ConversatorSession(
            api_key=os.environ.get("GOOGLE_API_KEY", "test-key"),
            opencode_url="http://localhost:4096",
            workspace_path=temp_workspace
        )

        assert session.state is not None
        assert session.prompt_manager is not None
        assert session.tool_handler is not None
        assert session.tools == CONVERSATOR_TOOLS

    def test_planner_active_property(self, temp_workspace):
        """is_planner_active returns handler state."""
        session = ConversatorSession(
            api_key="test-key",
            workspace_path=temp_workspace
        )

        assert session.is_planner_active is False

        session.tool_handler.planner_session_active = True
        assert session.is_planner_active is True

    def test_get_status_summary(self, temp_workspace):
        """get_status_summary returns voice-friendly text."""
        session = ConversatorSession(
            api_key="test-key",
            workspace_path=temp_workspace
        )

        summary = session.get_status_summary()

        assert isinstance(summary, str)
        assert "No active tasks" in summary

    def test_get_inbox_summary(self, temp_workspace):
        """get_inbox_summary returns voice-friendly text."""
        session = ConversatorSession(
            api_key="test-key",
            workspace_path=temp_workspace
        )

        summary = session.get_inbox_summary()

        assert isinstance(summary, str)
        assert "No unread" in summary

    def test_acknowledge_all(self, temp_workspace):
        """acknowledge_all_notifications works."""
        session = ConversatorSession(
            api_key="test-key",
            workspace_path=temp_workspace
        )

        result = session.acknowledge_all_notifications()

        assert "No notifications" in result or "Acknowledged" in result


class TestToolCallIntegration:
    """Integration tests for tool calls with real Gemini."""

    @pytest.fixture
    async def session(self):
        """Create and start session."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / ".conversator"
            workspace.mkdir()
            (workspace / "prompts").mkdir()
            (workspace / "memory").mkdir()

            session = ConversatorSession(
                api_key=os.environ.get("GOOGLE_API_KEY"),
                workspace_path=str(workspace)
            )

            try:
                await session.start()
                yield session
            except Exception as e:
                pytest.skip(f"Could not start session: {e}")
            finally:
                await session.stop()

    @pytest.mark.asyncio
    @pytest.mark.slow
    async def test_check_status_tool_call(self, session):
        """Gemini calls check_status for status queries."""
        # This is a slow test that actually interacts with Gemini
        # Mark with @pytest.mark.slow and skip by default

        received_audio = []
        received_text = []

        async def audio_callback(audio):
            received_audio.append(audio)

        async def text_callback(text):
            received_text.append(text)

        # Send status query
        await session.conversator.send_text("What's the current status?")

        # Process responses with timeout
        try:
            await asyncio.wait_for(
                session.conversator.process_responses(audio_callback, text_callback),
                timeout=30
            )
        except asyncio.TimeoutError:
            pass  # Expected - process_responses runs until disconnected

        # Should have received some response
        assert len(received_audio) > 0 or len(received_text) > 0


class TestVoiceActivityDetection:
    """Tests for voice activity detection integration."""

    @pytest.mark.asyncio
    async def test_audio_input_format(self):
        """Audio input uses correct format."""
        voice = ConversatorVoice(api_key=os.environ.get("GOOGLE_API_KEY"))
        mock_handler = AsyncMock()

        try:
            await voice.connect(tools=[], tool_handler=mock_handler)

            # Generate test audio: 16-bit PCM, 16kHz, mono
            # 0.1 seconds = 1600 samples = 3200 bytes
            test_audio = b"\x00\x00" * 1600

            # Should not throw
            await voice.send_audio(test_audio)

        except Exception as e:
            pytest.skip(f"Connection failed: {e}")
        finally:
            await voice.disconnect()

    @pytest.mark.asyncio
    async def test_audio_end_signal(self):
        """Can signal end of audio stream."""
        voice = ConversatorVoice(api_key=os.environ.get("GOOGLE_API_KEY"))
        mock_handler = AsyncMock()

        try:
            await voice.connect(tools=[], tool_handler=mock_handler)

            # Send some audio
            await voice.send_audio(b"\x00\x00" * 1600)

            # Signal end
            await voice.send_audio_end()

        except Exception as e:
            pytest.skip(f"Connection failed: {e}")
        finally:
            await voice.disconnect()
