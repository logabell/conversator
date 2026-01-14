"""Gemini Live conversational agent for Conversator."""

import asyncio
import time
from pathlib import Path
from typing import Any, Callable, TYPE_CHECKING

from google import genai
from google.genai import types

from .config import ConversatorConfig
from .handlers import ToolHandler
from .state import StateStore
from .models import ConversatorTask, ToolResponse
from .prompt_manager import PromptManager
from .dashboard.conversation_logger import ConversationLogger

if TYPE_CHECKING:
    from .ambient_audio import AmbientAudioController


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
        self.conversation_logger: ConversationLogger | None = None
        self._connected = False
        self._session_context = None

        # Ambient audio controller for background music during work
        self.ambient_audio: "AmbientAudioController | None" = None

        # Voice source for playback control (needed for interrupt handling)
        self._voice_source = None

        # Announcement queue for voice feedback
        self._announcement_queue: asyncio.Queue[str] = asyncio.Queue()
        self._announcement_task: asyncio.Task | None = None

        # Session resumption and reconnection state
        self._session_handle: str | None = None  # Handle from SessionResumptionUpdate for reconnection
        self._reconnect_attempts: int = 0
        self._max_reconnect_attempts: int = 3
        self._reconnect_delay: float = 1.0  # Base delay in seconds
        self._max_reconnect_delay: float = 30.0  # Max delay after exponential backoff
        self._last_tools: list[dict] | None = None  # Store tools for reconnection
        self._go_away_received: bool = False  # Track if GO_AWAY was received

        # Generation state tracking (for audio coordination)
        self._is_generating: bool = False
        self._last_response_time: float = 0

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

    def set_ambient_audio(self, controller: "AmbientAudioController") -> None:
        """Set the ambient audio controller for background music.

        Args:
            controller: AmbientAudioController instance
        """
        self.ambient_audio = controller

    def set_voice_source(self, voice_source) -> None:
        """Set the voice source for playback control.

        This is needed to stop playback immediately when the user interrupts.

        Args:
            voice_source: Voice source instance with stop_playback() method
        """
        self._voice_source = voice_source

    async def announce(self, text: str, priority: str = "normal") -> None:
        """Send voice feedback to Gemini to speak.

        Consolidated announcement method replacing the previous triple system
        (_queue_announcement, _send_announcement_direct, __voice_announcement).

        Args:
            text: Text for Gemini to announce
            priority: "immediate" sends directly, "normal" queues for processing
        """
        if not self._connected or not self.session:
            print(f"[GeminiLive] Cannot announce - not connected")
            return

        if priority == "immediate":
            # Send directly (used for important feedback)
            try:
                await self.session.send(
                    input=types.LiveClientContent(
                        turns=[
                            types.Content(
                                role="user",
                                parts=[types.Part(text=f"[SYSTEM: Announce this to the user: {text}]")]
                            )
                        ]
                    )
                )
            except Exception as e:
                print(f"[GeminiLive] Failed to send announcement: {e}")
        else:
            # Queue for async processing
            await self._announcement_queue.put(text)

    async def _process_announcements(self) -> None:
        """Process queued announcements by sending them to Gemini.

        Runs as a background task, processing announcements from the queue.
        """
        while True:
            try:
                announcement = await asyncio.wait_for(
                    self._announcement_queue.get(),
                    timeout=0.5
                )
                print(f"[GeminiLive] Processing queued announcement: {announcement[:100]}...")
                if self._connected and self.session:
                    # Send announcement as a system message that Gemini should speak
                    await self.session.send(
                        input=types.LiveClientContent(
                            turns=[
                                types.Content(
                                    role="user",
                                    parts=[types.Part(text=f"[SYSTEM: Announce this to the user: {announcement}]")]
                                )
                            ]
                        )
                    )
                    print(f"[GeminiLive] Queued announcement sent")
                else:
                    print(f"[GeminiLive] Cannot send queued announcement - not connected")
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[GeminiLive] Announcement queue error: {e}")

    async def connect(
        self,
        tools: list[dict[str, Any]],
        tool_handler: ToolHandler,
        resume_handle: str | None = None
    ) -> None:
        """Connect to Gemini Live with tools.

        Args:
            tools: List of tool definitions
            tool_handler: Handler for tool calls
            resume_handle: Optional session handle for resuming a previous session
        """
        self.tool_handler = tool_handler

        # Store tools for potential reconnection
        self._last_tools = tools

        # Live API requires tools as raw dicts, not SDK types
        # See: https://ai.google.dev/gemini-api/docs/live-tools
        # Format: [{"function_declarations": [{"name": "...", "description": "...", "parameters": {...}}]}]
        tool_config = [{"function_declarations": tools}]

        tool_names = [t["name"] for t in tools]
        print(f"[DEBUG] Registering {len(tools)} tools with Live API: {', '.join(tool_names[:5])}{'...' if len(tools) > 5 else ''}")

        # Build session resumption config if we have a handle
        session_resumption_config = None
        if resume_handle:
            session_resumption_config = types.SessionResumptionConfig(
                handle=resume_handle
            )
            print(f"[GeminiLive] Resuming session with handle")
        else:
            # Request session resumption updates for future reconnection
            session_resumption_config = types.SessionResumptionConfig()
            print(f"[GeminiLive] Starting new session with resumption enabled")

        # Build config with tools, voice activity detection, and session resumption
        config = types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            system_instruction=types.Content(
                parts=[types.Part(text=self.system_prompt)]
            ),
            # Tools must be raw dicts for Live API
            tools=tool_config,
            # Speech config for output
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name="Kore"  # Options: Puck, Charon, Kore, Fenrir, Aoede
                    )
                )
            ),
            # VAD configuration to reduce premature turn endings and handle echo
            # - LOW start sensitivity: requires clearer speech onset, helps ignore echo
            # - LOW end sensitivity: waits longer before deciding speech ended
            # - Higher silence_duration_ms: prevents cutting off mid-sentence
            realtime_input_config=types.RealtimeInputConfig(
                automatic_activity_detection=types.AutomaticActivityDetection(
                    disabled=False,  # Keep server-side VAD enabled
                    start_of_speech_sensitivity=types.StartSensitivity.START_SENSITIVITY_LOW,
                    end_of_speech_sensitivity=types.EndSensitivity.END_SENSITIVITY_LOW,
                    prefix_padding_ms=100,  # Capture speech onset (default 20ms)
                    silence_duration_ms=500,  # Wait longer before ending turn (default 100ms)
                ),
            ),
            # Session resumption for reconnection support
            session_resumption=session_resumption_config,
        )

        # Connect using async context manager
        self._session_context = self.client.aio.live.connect(
            model="gemini-2.0-flash-exp",
            config=config
        )
        self.session = await self._session_context.__aenter__()
        self._connected = True
        self._go_away_received = False
        self._last_response_time = time.time()

        # Reset reconnect attempts on successful connection
        self._reconnect_attempts = 0

        # Start announcement processing task
        self._announcement_task = asyncio.create_task(self._process_announcements())

    async def disconnect(self) -> None:
        """Disconnect from Gemini Live."""
        # Stop announcement processing
        if self._announcement_task:
            self._announcement_task.cancel()
            try:
                await self._announcement_task
            except asyncio.CancelledError:
                pass
            self._announcement_task = None

        # Stop ambient audio
        if self.ambient_audio:
            self.ambient_audio.stop()

        if self._session_context:
            try:
                await self._session_context.__aexit__(None, None, None)
            except Exception:
                pass
            self._session_context = None
            self.session = None
        self._connected = False

    async def reconnect(self) -> bool:
        """Attempt to reconnect to Gemini Live with session resumption.

        Uses exponential backoff and the stored session handle if available.
        Follows the reconnection pattern from OpenCodeSSEClient.

        Returns:
            True if reconnection was successful, False otherwise
        """
        if self._reconnect_attempts >= self._max_reconnect_attempts:
            print(f"[Reconnect] Max attempts ({self._max_reconnect_attempts}) exceeded")
            return False

        self._reconnect_attempts += 1
        delay = min(
            self._reconnect_delay * (2 ** (self._reconnect_attempts - 1)),
            self._max_reconnect_delay
        )

        print(f"[Reconnect] Attempt {self._reconnect_attempts}/{self._max_reconnect_attempts} "
              f"in {delay:.1f}s (handle={'yes' if self._session_handle else 'no'})")

        await asyncio.sleep(delay)

        try:
            # Clean disconnect first
            if self._session_context:
                try:
                    await self._session_context.__aexit__(None, None, None)
                except Exception:
                    pass
                self._session_context = None
                self.session = None

            # Stop announcement task before reconnecting
            if self._announcement_task:
                self._announcement_task.cancel()
                try:
                    await self._announcement_task
                except asyncio.CancelledError:
                    pass
                self._announcement_task = None

            # Reconnect with session handle if available
            if self._last_tools is None:
                print(f"[Reconnect] Failed: No tools stored for reconnection")
                return False

            await self.connect(
                tools=self._last_tools,
                tool_handler=self.tool_handler,
                resume_handle=self._session_handle
            )

            print(f"[Reconnect] Success! Session resumed")
            return True

        except Exception as e:
            print(f"[Reconnect] Failed: {e}")
            import traceback
            traceback.print_exc()
            return False

    @property
    def can_reconnect(self) -> bool:
        """Check if reconnection is possible."""
        return (
            self._reconnect_attempts < self._max_reconnect_attempts
            and self._last_tools is not None
        )

    @property
    def seconds_since_last_response(self) -> float:
        """Get seconds since last response from Gemini.

        Returns:
            Seconds since last response, or 0 if no responses received yet.
        """
        if self._last_response_time == 0:
            return 0
        return time.time() - self._last_response_time

    def is_connection_healthy(self, max_idle_seconds: float = 60.0) -> bool:
        """Check if the connection appears healthy.

        Args:
            max_idle_seconds: Max seconds without response before considered unhealthy

        Returns:
            True if connection appears healthy
        """
        if not self._connected:
            return False
        if self._go_away_received:
            return False
        # If we've been idle too long, connection might be stale
        if self._last_response_time > 0:
            idle_time = self.seconds_since_last_response
            if idle_time > max_idle_seconds:
                print(f"[Health] Connection idle for {idle_time:.0f}s (max: {max_idle_seconds}s)")
                return False
        return True

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
        self._last_response_time = time.time()
        async for response in self.session.receive():
            self._last_response_time = time.time()
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
                self._go_away_received = True
                time_left = getattr(response.go_away, 'time_left', None)
                if time_left:
                    print(f"[GO_AWAY: Server ending session, time left: {time_left}]")
                else:
                    print(f"[GO_AWAY: Server ending session]")
                print(f"[Session handle available: {'yes' if self._session_handle else 'no'}]")

            # Capture session resumption updates for reconnection
            if hasattr(response, 'session_resumption_update') and response.session_resumption_update:
                update = response.session_resumption_update
                if hasattr(update, 'new_handle') and update.new_handle:
                    self._session_handle = update.new_handle
                    print(f"[Session resumption handle updated]")

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
                    # Log to conversation logger for dashboard
                    if self.conversation_logger:
                        await self.conversation_logger.log_user_speech(sc.input_transcription)
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
            handled_tool_call_this_response = False
            if hasattr(response, 'tool_call') and response.tool_call:
                await self._handle_tool_calls(response.tool_call)
                handled_tool_call_this_response = True

            # Break on TURN_COMPLETE to restart the receive loop
            # TURN_COMPLETE means Gemini's turn is done and it's waiting for user input
            # BUT: If we just handled a tool call, we need to wait for Gemini's response
            # to the tool result, so don't break on the same response that had the tool_call
            if hasattr(response, 'server_content') and response.server_content:
                sc = response.server_content
                if hasattr(sc, 'turn_complete') and sc.turn_complete:
                    if handled_tool_call_this_response:
                        print("[Turn complete on tool_call response - continuing to wait for tool result response]")
                    else:
                        print(f"[Turn complete after {response_count} responses - ready for next turn]")
                        return  # Clean exit on TURN_COMPLETE

        # Response iterator completed without TURN_COMPLETE - connection closed
        self._connected = False
        if self._go_away_received:
            print(f"[Session ended after GO_AWAY ({response_count} responses) - reconnection available]")
            raise ConnectionResetError(
                f"Session ended by GO_AWAY after {response_count} responses"
            )
        else:
            print(f"[WARNING: Gemini session ended unexpectedly after {response_count} responses without TURN_COMPLETE]")
            print("[WebSocket connection was closed unexpectedly]")
            raise ConnectionResetError(
                f"Gemini session ended unexpectedly after {response_count} responses"
            )

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
            self._is_generating = False  # Model finished outputting
            print("[Turn complete - ready for next input]")

        if hasattr(content, "interrupted") and content.interrupted:
            print("[Interrupted by user - stopping playback]")
            # Stop playback immediately so user can speak
            # Note: Without hardware AEC, interrupts during playback are unreliable
            # because we can't send audio during playback (would cause echo loops)
            # Interrupts work best in the brief gaps between playback chunks
            if self._voice_source and hasattr(self._voice_source, 'stop_playback'):
                self._voice_source.stop_playback()

        # Handle model turn with parts
        if hasattr(content, "model_turn") and content.model_turn:
            for part in content.model_turn.parts:
                # Handle audio output
                if hasattr(part, "inline_data") and part.inline_data:
                    mime = getattr(part.inline_data, "mime_type", "")
                    if mime.startswith("audio/"):
                        self._is_generating = True  # Model is outputting audio
                        await audio_callback(part.inline_data.data)

                # Handle text output
                if hasattr(part, "text") and part.text:
                    print(f"[Conversator]: {part.text}")
                    if text_callback:
                        await text_callback(part.text)
                    # Log to conversation logger for dashboard
                    if self.conversation_logger:
                        await self.conversation_logger.log_assistant_response(part.text)

    async def _handle_tool_calls(
        self,
        tool_call: types.LiveServerToolCall
    ) -> None:
        """Handle tool calls from Gemini and send results back.

        Uses ToolResponse to cleanly separate result data from side effects
        like voice feedback and ambient audio control.

        Args:
            tool_call: Tool call from Gemini
        """
        if not self.tool_handler:
            return

        import time as _time
        start_time = _time.time()
        call_names = [c.name for c in tool_call.function_calls]
        print(f"[ToolCall] Received {len(call_names)} tool call(s): {call_names}")

        function_responses = []

        for call in tool_call.function_calls:
            call_start = _time.time()
            print(f"[ToolCall] Dispatching {call.name}...")

            response = await self._dispatch_tool_call(call.name, call.args or {})

            call_duration = _time.time() - call_start
            result_summary = str(response.result)[:200] + "..." if len(str(response.result)) > 200 else str(response.result)
            print(f"[ToolCall] {call.name} completed in {call_duration:.1f}s: {result_summary}")

            # Handle side effects separately from the result
            if response.voice_feedback:
                await self.announce(response.voice_feedback)
                print(f"[ToolCall] Announced: {response.voice_feedback[:100]}...")

            if self.ambient_audio:
                if response.start_ambient:
                    await self.ambient_audio.start_work_music()
                elif response.stop_ambient:
                    await self.ambient_audio.stop_work_music()

            # Send clean result to Gemini (no special fields)
            function_responses.append(
                types.FunctionResponse(
                    id=call.id,
                    name=call.name,
                    response=response.result
                )
            )

        total_duration = _time.time() - start_time
        print(f"[ToolCall] All tool calls completed in {total_duration:.1f}s, sending {len(function_responses)} response(s) to Gemini")

        # Send tool responses back to Gemini
        try:
            await self.session.send(
                input=types.LiveClientToolResponse(
                    function_responses=function_responses
                )
            )
            print(f"[ToolCall] Tool responses sent successfully - waiting for Gemini's response")
        except Exception as e:
            print(f"[ToolCall] ERROR sending tool responses: {e}")
            import traceback
            traceback.print_exc()

    async def _dispatch_tool_call(
        self,
        name: str,
        args: dict[str, Any]
    ) -> ToolResponse:
        """Dispatch a tool call to the appropriate handler.

        Args:
            name: Tool name
            args: Tool arguments

        Returns:
            ToolResponse with result and optional side effects
        """
        # Log tool call start for dashboard
        if self.conversation_logger:
            await self.conversation_logger.log_tool_call_start(name, args)

        handlers = {
            # Project management
            "list_projects": self.tool_handler.handle_list_projects,
            "select_project": self.tool_handler.handle_select_project,
            "start_builder": self.tool_handler.handle_start_builder,
            "create_project": self.tool_handler.handle_create_project,
            # Planning and context
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
            # Quick dispatch for simple operations (replaces run_command)
            "quick_dispatch": self.tool_handler.handle_quick_dispatch,
            "engage_brainstormer": self.tool_handler.handle_engage_brainstormer,
            "get_builder_plan": self.tool_handler.handle_get_builder_plan,
            "approve_builder_plan": self.tool_handler.handle_approve_builder_plan,
        }

        handler = handlers.get(name)
        if handler:
            try:
                response = await handler(**args)

                # Log tool call completion for dashboard
                if self.conversation_logger:
                    await self.conversation_logger.log_tool_call_complete(name, response.result)
                return response
            except Exception as e:
                error_response = ToolResponse(result={"error": str(e)})
                # Log tool call error for dashboard
                if self.conversation_logger:
                    await self.conversation_logger.log_tool_call_complete(name, error_response.result)
                return error_response

        unknown_response = ToolResponse(result={"error": f"Unknown tool: {name}"})
        # Log unknown tool for dashboard
        if self.conversation_logger:
            await self.conversation_logger.log_tool_call_complete(name, unknown_response.result)
        return unknown_response


class ConversatorSession:
    """Manages a complete Conversator voice session."""

    def __init__(
        self,
        api_key: str,
        opencode_url: str = "http://localhost:8001",
        workspace_path: str = ".conversator",
        config: ConversatorConfig | None = None
    ):
        """Initialize session.

        Args:
            api_key: Google API key
            opencode_url: OpenCode server URL
            workspace_path: Path to .conversator workspace directory
            config: Optional configuration (will load from file if not provided)
        """
        from .opencode_client import OpenCodeClient
        from .tools import CONVERSATOR_TOOLS

        self.api_key = api_key
        self.workspace_path = Path(workspace_path)
        self.config = config or ConversatorConfig.load()
        self.root_project_dir = self.config.root_project_dir
        self.opencode = OpenCodeClient(opencode_url)

        # Initialize state store first
        self.state = StateStore(self.workspace_path / "state.sqlite")
        self.current_task: ConversatorTask | None = None

        # Initialize prompt manager
        self.prompt_manager = PromptManager(self.workspace_path, state=self.state)

        # Pass state, prompt_manager, and config to tool handler
        self.tool_handler = ToolHandler(
            self.opencode,
            state=self.state,
            prompt_manager=self.prompt_manager,
            config=self.config
        )

        # Use system prompt path from config
        system_prompt_path = self.config.voice_system_prompt
        self.conversator = ConversatorVoice(api_key, system_prompt_path=system_prompt_path)
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
