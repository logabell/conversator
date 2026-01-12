"""Gemini Live conversational agent for Conversator."""

import asyncio
from pathlib import Path
from typing import Any, Callable

from google import genai
from google.genai import types

from .handlers import ToolHandler
from .state import StateStore
from .models import ConversatorTask
from .prompt_manager import PromptManager


class ConversatorVoice:
    """Voice-first conversational agent using Gemini Live.

    This is the "brain" of Conversator - it has natural conversations
    with developers, understands intent, and dispatches to subagents
    and builders when appropriate.
    """

    def __init__(
        self,
        api_key: str,
        system_prompt_path: str = ".conversator/prompts/conversator.md"
    ):
        """Initialize Conversator voice agent.

        Args:
            api_key: Google API key for Gemini
            system_prompt_path: Path to system prompt file
        """
        self.client = genai.Client(api_key=api_key)
        self.system_prompt = self._load_system_prompt(system_prompt_path)
        self.session = None
        self.tool_handler: ToolHandler | None = None
        self._connected = False
        self._session_context = None

    def _load_system_prompt(self, path: str) -> str:
        """Load system prompt from file.

        Args:
            path: Path to system prompt file

        Returns:
            System prompt content
        """
        prompt_path = Path(path)
        if prompt_path.exists():
            return prompt_path.read_text()

        # Fallback default prompt
        return """You are Conversator, a voice-first development assistant.
Have natural conversations with developers about their code. When they
describe problems or tasks, help them refine their ideas.
Be concise - this is voice, not text."""

    async def connect(
        self,
        tools: list[dict[str, Any]],
        tool_handler: ToolHandler
    ) -> None:
        """Connect to Gemini Live with tools.

        Args:
            tools: List of tool definitions
            tool_handler: Handler for tool calls
        """
        self.tool_handler = tool_handler

        # Build config with voice activity detection (use defaults)
        config = types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            system_instruction=types.Content(
                parts=[types.Part(text=self.system_prompt)]
            ),
            # Speech config for output
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name="Puck"  # Options: Puck, Charon, Kore, Fenrir, Aoede
                    )
                )
            ),
        )

        # Connect using async context manager
        self._session_context = self.client.aio.live.connect(
            model="gemini-2.0-flash-exp",
            config=config
        )
        self.session = await self._session_context.__aenter__()
        self._connected = True

    async def disconnect(self) -> None:
        """Disconnect from Gemini Live."""
        if self._session_context:
            try:
                await self._session_context.__aexit__(None, None, None)
            except Exception:
                pass
            self._session_context = None
            self.session = None
        self._connected = False

    async def send_audio(self, audio_chunk: bytes) -> None:
        """Send audio input to Gemini.

        Args:
            audio_chunk: Raw PCM audio bytes (16-bit, 16kHz, mono)
        """
        if not self._connected or not self.session:
            raise RuntimeError("Not connected to Gemini Live")

        # Send audio using send_realtime_input with proper Blob format
        await self.session.send_realtime_input(
            audio=types.Blob(data=audio_chunk, mime_type="audio/pcm;rate=16000")
        )

    async def send_audio_end(self) -> None:
        """Signal end of audio stream to trigger VAD processing."""
        if not self._connected or not self.session:
            raise RuntimeError("Not connected to Gemini Live")

        await self.session.send_realtime_input(audio_stream_end=True)

    async def send_text(self, text: str) -> None:
        """Send text input to Gemini (for typed commands).

        Args:
            text: Text message
        """
        if not self._connected or not self.session:
            raise RuntimeError("Not connected to Gemini Live")

        await self.session.send(
            input=types.LiveClientContent(
                turns=[
                    types.Content(
                        role="user",
                        parts=[types.Part(text=text)]
                    )
                ]
            )
        )

    async def process_responses(
        self,
        audio_callback: Callable[[bytes], Any],
        text_callback: Callable[[str], Any] | None = None
    ) -> None:
        """Process responses from Gemini - audio, text, and tool calls.

        Args:
            audio_callback: Called with audio bytes for playback
            text_callback: Optional callback for text responses
        """
        if not self._connected or not self.session:
            raise RuntimeError("Not connected to Gemini Live")

        print("[Starting to receive responses from Gemini...]")
        response_count = 0
        async for response in self.session.receive():
            response_count += 1

            # Debug: show what type of response we got
            response_types = []
            if hasattr(response, 'server_content') and response.server_content:
                response_types.append('server_content')
            if hasattr(response, 'tool_call') and response.tool_call:
                response_types.append('tool_call')
            if hasattr(response, 'setup_complete') and response.setup_complete:
                response_types.append('setup_complete')
            if hasattr(response, 'data') and response.data:
                response_types.append(f'data({len(response.data)})')
            if hasattr(response, 'go_away') and response.go_away:
                response_types.append('GO_AWAY')
                print(f"[WARNING: Server sent GO_AWAY - session ending]")

            # Check for turn state flags and always show them
            if hasattr(response, 'server_content') and response.server_content:
                sc = response.server_content
                flags = []
                if hasattr(sc, 'turn_complete') and sc.turn_complete:
                    flags.append('TURN_COMPLETE')
                if hasattr(sc, 'generation_complete') and sc.generation_complete:
                    flags.append('GEN_COMPLETE')
                if hasattr(sc, 'interrupted') and sc.interrupted:
                    flags.append('INTERRUPTED')
                if hasattr(sc, 'input_transcription') and sc.input_transcription:
                    print(f"[Transcription: {sc.input_transcription}]")
                if flags:
                    print(f"[Response #{response_count}: {flags}]")

            if response_count <= 10 or response_count % 20 == 0:
                if response_types:
                    print(f"[Response #{response_count}: {response_types}]")
                else:
                    # Show actual attributes if we don't recognize the response
                    attrs = [a for a in dir(response) if not a.startswith('_')]
                    print(f"[Response #{response_count}: attrs={attrs[:10]}]")

            # Handle server content (audio/text responses)
            if hasattr(response, 'server_content') and response.server_content:
                await self._handle_server_content(
                    response.server_content,
                    audio_callback,
                    text_callback
                )

            # Handle tool calls
            if hasattr(response, 'tool_call') and response.tool_call:
                await self._handle_tool_calls(response.tool_call)

        # Response iterator completed - connection may have closed
        print(f"[WARNING: Gemini session receive() ended after {response_count} responses - connection may have closed]")

    async def _handle_server_content(
        self,
        content,
        audio_callback: Callable[[bytes], Any],
        text_callback: Callable[[str], Any] | None
    ) -> None:
        """Handle audio and text responses from Gemini.

        Args:
            content: Server content
            audio_callback: Callback for audio playback
            text_callback: Optional callback for text
        """
        # Check turn state flags
        if hasattr(content, "generation_complete") and content.generation_complete:
            print("[Generation complete]")

        if hasattr(content, "turn_complete") and content.turn_complete:
            print("[Turn complete - ready for next input]")

        if hasattr(content, "interrupted") and content.interrupted:
            print("[Interrupted by user]")

        # Handle model turn with parts
        if hasattr(content, "model_turn") and content.model_turn:
            for part in content.model_turn.parts:
                # Handle audio output
                if hasattr(part, "inline_data") and part.inline_data:
                    mime = getattr(part.inline_data, "mime_type", "")
                    if mime.startswith("audio/"):
                        await audio_callback(part.inline_data.data)

                # Handle text output
                if hasattr(part, "text") and part.text:
                    print(f"[Conversator]: {part.text}")
                    if text_callback:
                        await text_callback(part.text)

    async def _handle_tool_calls(
        self,
        tool_call: types.LiveServerToolCall
    ) -> None:
        """Handle tool calls from Gemini and send results back.

        Args:
            tool_call: Tool call from Gemini
        """
        if not self.tool_handler:
            return

        function_responses = []

        for call in tool_call.function_calls:
            result = await self._dispatch_tool_call(call.name, call.args or {})
            function_responses.append(
                types.FunctionResponse(
                    id=call.id,
                    name=call.name,
                    response=result
                )
            )

        # Send tool responses back to Gemini
        await self.session.send(
            input=types.LiveClientToolResponse(
                function_responses=function_responses
            )
        )

    async def _dispatch_tool_call(
        self,
        name: str,
        args: dict[str, Any]
    ) -> dict[str, Any]:
        """Dispatch a tool call to the appropriate handler.

        Args:
            name: Tool name
            args: Tool arguments

        Returns:
            Tool result
        """
        handlers = {
            "engage_planner": self.tool_handler.handle_engage_planner,
            "lookup_context": self.tool_handler.handle_lookup_context,
            "check_status": self.tool_handler.handle_check_status,
            "dispatch_to_builder": self.tool_handler.handle_dispatch_to_builder,
            "add_to_memory": self.tool_handler.handle_add_to_memory,
            "cancel_task": self.tool_handler.handle_cancel_task,
            "check_inbox": self.tool_handler.handle_check_inbox,
            "acknowledge_inbox": self.tool_handler.handle_acknowledge_inbox,
            "update_working_prompt": self.tool_handler.handle_update_working_prompt,
            "freeze_prompt": self.tool_handler.handle_freeze_prompt,
        }

        handler = handlers.get(name)
        if handler:
            try:
                return await handler(**args)
            except Exception as e:
                return {"error": str(e)}

        return {"error": f"Unknown tool: {name}"}


class ConversatorSession:
    """Manages a complete Conversator voice session."""

    def __init__(
        self,
        api_key: str,
        opencode_url: str = "http://localhost:8001",
        workspace_path: str = ".conversator"
    ):
        """Initialize session.

        Args:
            api_key: Google API key
            opencode_url: OpenCode server URL
            workspace_path: Path to .conversator workspace directory
        """
        from .opencode_client import OpenCodeClient
        from .tools import CONVERSATOR_TOOLS

        self.api_key = api_key
        self.workspace_path = Path(workspace_path)
        self.opencode = OpenCodeClient(opencode_url)

        # Initialize state store first
        self.state = StateStore(self.workspace_path / "state.sqlite")
        self.current_task: ConversatorTask | None = None

        # Initialize prompt manager
        self.prompt_manager = PromptManager(self.workspace_path, state=self.state)

        # Pass state and prompt_manager to tool handler
        self.tool_handler = ToolHandler(
            self.opencode,
            state=self.state,
            prompt_manager=self.prompt_manager
        )
        self.conversator = ConversatorVoice(api_key)
        self.tools = CONVERSATOR_TOOLS

    async def start(self) -> None:
        """Start the session and create initial task."""
        await self.conversator.connect(self.tools, self.tool_handler)

        # Create a new task for this session
        self.current_task = self.state.create_task(
            title="Voice Session",
            working_prompt_path=str(self.workspace_path / "prompts" / "current" / "working.md")
        )

        # Set up prompt manager for this task
        self.tool_handler.current_task_id = self.current_task.task_id
        await self.prompt_manager.init_working_prompt(
            self.current_task.task_id,
            title="Voice Session"
        )

        print(f"[State: Created task {self.current_task.task_id[:8]}...]")

    async def stop(self) -> None:
        """Stop the session and clean up."""
        await self.conversator.disconnect()
        await self.opencode.close()
        self.state.close()

    @property
    def is_planner_active(self) -> bool:
        """Check if planner is waiting for input."""
        return self.tool_handler.planner_session_active

    async def continue_planner(self, response: str) -> dict[str, Any]:
        """Continue planner conversation.

        Args:
            response: User's response to planner questions

        Returns:
            Planner result
        """
        return await self.tool_handler.handle_planner_response(response)

    # --- State Query Methods (for voice commands) ---

    def get_status_summary(self) -> str:
        """Get a voice-friendly summary of active tasks.

        Returns:
            Summary string suitable for voice output
        """
        active_tasks = self.state.get_active_tasks()

        if not active_tasks:
            return "No active tasks."

        if len(active_tasks) == 1:
            task = active_tasks[0]
            return f"One active task: {task.title}, status {task.status}."

        summaries = []
        for task in active_tasks[:5]:  # Limit to 5 for voice
            summaries.append(f"{task.title} ({task.status})")

        result = f"{len(active_tasks)} active tasks: " + ", ".join(summaries)
        if len(active_tasks) > 5:
            result += f", and {len(active_tasks) - 5} more."

        return result

    def get_inbox_summary(self) -> str:
        """Get a voice-friendly summary of unread inbox items.

        Returns:
            Summary string suitable for voice output
        """
        unread = self.state.get_inbox(unread_only=True)

        if not unread:
            return "No unread notifications."

        if len(unread) == 1:
            item = unread[0]
            return f"One notification: {item.summary}"

        # Group by severity
        blocking = [i for i in unread if i.severity == "blocking"]
        errors = [i for i in unread if i.severity == "error"]
        others = [i for i in unread if i.severity not in ("blocking", "error")]

        parts = []
        if blocking:
            parts.append(f"{len(blocking)} blocking")
        if errors:
            parts.append(f"{len(errors)} errors")
        if others:
            parts.append(f"{len(others)} other")

        result = f"{len(unread)} unread notifications: " + ", ".join(parts) + "."

        # Read the most important one
        important = blocking[0] if blocking else (errors[0] if errors else unread[0])
        result += f" Most important: {important.summary}"

        return result

    def cancel_current_task(self, reason: str = "User requested via voice") -> str:
        """Cancel the current task.

        Args:
            reason: Cancellation reason

        Returns:
            Confirmation message
        """
        if not self.current_task:
            return "No active task to cancel."

        if self.current_task.status in ("done", "failed", "canceled"):
            return f"Task already {self.current_task.status}."

        self.state.cancel_task(self.current_task.task_id, reason)
        self.current_task = self.state.get_task(self.current_task.task_id)

        return f"Task canceled: {self.current_task.title}"

    def acknowledge_all_notifications(self) -> str:
        """Mark all inbox items as read.

        Returns:
            Confirmation message
        """
        count = self.state.acknowledge_all_inbox()
        if count == 0:
            return "No notifications to acknowledge."
        return f"Acknowledged {count} notifications."
