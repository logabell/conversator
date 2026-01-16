"""Gemini Live conversational agent for Conversator."""

import asyncio
import time
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from google import genai
from google.genai import types

from .config import ConversatorConfig
from .dashboard.conversation_logger import ConversationLogger
from .handlers import ToolHandler
from .models import ConversatorTask, ToolResponse
from .prompt_manager import PromptManager
from .state import StateStore

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
        system_prompt_path: str = ".conversator/prompts/conversator.md",
        vad_silence_duration_ms: int = 5000,
        live_model: str = "gemini-2.5-flash-native-audio-preview-12-2025",
    ):
        """Initialize Conversator voice agent.

        Args:
            api_key: Google API key for Gemini
            system_prompt_path: Path to system prompt file
        """
        self.client = genai.Client(api_key=api_key)
        self.live_model = live_model
        self.system_prompt = self._load_system_prompt(system_prompt_path)
        self.session = None
        self.tool_handler: ToolHandler | None = None
        self.vad_silence_duration_ms = vad_silence_duration_ms
        self.conversation_logger: ConversationLogger | None = None
        self._connected = False
        self._session_context = None

        # Ambient audio controller for background music during work
        self.ambient_audio: AmbientAudioController | None = None

        # Voice source for playback control (needed for interrupt handling)
        self._voice_source = None

        # Announcement queue for voice feedback
        self._announcement_queue: asyncio.Queue[str] = asyncio.Queue()
        self._announcement_task: asyncio.Task | None = None

        # Session resumption and reconnection state
        self._session_handle: str | None = (
            None  # Handle from SessionResumptionUpdate for reconnection
        )
        self._reconnect_attempts: int = 0
        self._max_reconnect_attempts: int = 3
        self._reconnect_delay: float = 1.0  # Base delay in seconds
        self._max_reconnect_delay: float = 30.0  # Max delay after exponential backoff
        self._last_tools: list[dict] | None = None  # Store tools for reconnection
        self._go_away_received: bool = False  # Track if GO_AWAY was received
        self._reconnect_lock: asyncio.Lock = asyncio.Lock()

        # Generation state tracking (for audio coordination)
        self._is_generating: bool = False
        self._in_tool_call: bool = False
        self._last_response_time: float = 0
        self._last_turn_complete_time: float = 0

        # Turn-level tracking for auto-routing (relay guardrails)
        self._current_turn_transcript: str = ""
        self._last_turn_transcript: str = ""
        self._turn_had_tool_call: bool = False
        self._last_turn_had_tool_call: bool = False

        # Transcription buffers for cleaner logging.
        self._input_transcript_buffer: str = ""
        self._output_transcript_buffer: str = ""

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
            print("[GeminiLive] Cannot announce - not connected")
            return

        if priority == "immediate":
            # Send directly (used for important feedback)
            try:
                await self.session.send(
                    input=types.LiveClientContent(
                        turns=[
                            types.Content(
                                role="user",
                                parts=[
                                    types.Part(text=f"[SYSTEM: Announce this to the user: {text}]")
                                ],
                            )
                        ],
                        turn_complete=True,
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
                announcement = await asyncio.wait_for(self._announcement_queue.get(), timeout=0.5)
                print(f"[GeminiLive] Processing queued announcement: {announcement[:100]}...")
                if self._connected and self.session:
                    # Send announcement as a system message that Gemini should speak
                    system_text = f"[SYSTEM: Announce this to the user: {announcement}]"
                    await self.session.send(
                        input=types.LiveClientContent(
                            turns=[
                                types.Content(
                                    role="user",
                                    parts=[types.Part(text=system_text)],
                                )
                            ],
                            turn_complete=True,
                        )
                    )
                    print("[GeminiLive] Queued announcement sent")
                else:
                    print("[GeminiLive] Cannot send queued announcement - not connected")
            except TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[GeminiLive] Announcement queue error: {e}")

    def get_last_turn_transcript(self) -> str:
        """Return the normalized transcript for the last user turn."""
        return " ".join(self._last_turn_transcript.split()).strip()

    async def maybe_auto_route_last_turn(self) -> None:
        """Backstop routing (relay-only).

        Goals:
        - Subagents are the brain.
        - Avoid starting waiting music too early.

        If Gemini fails to call tools, we stage a relay draft instead of sending
        immediately. This allows a quick clarification and a confirmation step
        before dispatching to a subagent.
        """
        if self._last_turn_had_tool_call:
            return

        if not self.tool_handler:
            return

        transcript = self.get_last_turn_transcript()
        if not transcript:
            return

        is_ack = self.tool_handler._is_acknowledgment

        state = self.tool_handler.session_state
        draft = state.active_draft

        # If we're already drafting, continue the draft flow.
        if draft is not None:
            if draft.stage == "awaiting_detail":
                if is_ack(transcript):
                    message = (draft.message.strip() or draft.topic.strip()).strip()
                    state.active_draft = None
                    if not message:
                        await self.announce(
                            "What should we brainstorm about?",
                            priority="immediate",
                        )
                        return

                    result = await self.tool_handler.handle_send_to_thread(
                        message=message,
                        create_new_thread=True,
                        subagent=draft.target_subagent,
                        topic=draft.topic,
                        focus=True,
                    )
                    if isinstance(result, dict):
                        say = result.get("say")
                        thread_id = result.get("thread_id")
                        if isinstance(say, str) and say.strip():
                            state.enqueue_announcement(
                                say,
                                kind="wait_started",
                                thread_id=thread_id,
                            )
                    return

                draft.message = (
                    (draft.message + "\n" + transcript).strip() if draft.message else transcript
                )
                draft.stage = "awaiting_confirmation"
                draft.auto_confirm_sent = False
                confirm_prompt = (
                    "Got it. Anything else to add before I send this to the "
                    f"{draft.target_subagent}?"
                )
                await self.announce(confirm_prompt, priority="immediate")
                return

            if draft.stage == "awaiting_confirmation":
                if is_ack(transcript):
                    message = (draft.message.strip() or draft.topic.strip()).strip()
                    state.active_draft = None
                    if not message:
                        await self.announce(
                            "What should we brainstorm about?",
                            priority="immediate",
                        )
                        return

                    result = await self.tool_handler.handle_send_to_thread(
                        message=message,
                        create_new_thread=True,
                        subagent=draft.target_subagent,
                        topic=draft.topic,
                        focus=True,
                    )
                    if isinstance(result, dict):
                        say = result.get("say")
                        thread_id = result.get("thread_id")
                        if isinstance(say, str) and say.strip():
                            state.enqueue_announcement(
                                say,
                                kind="wait_started",
                                thread_id=thread_id,
                            )
                    return

                draft.message = (draft.message + "\n" + transcript).strip()
                draft.auto_confirm_sent = False
                confirm_prompt = (
                    "Got it. Anything else to add before I send this to the "
                    f"{draft.target_subagent}?"
                )
                await self.announce(confirm_prompt, priority="immediate")
                return

        return

    async def connect(
        self,
        tools: list[dict[str, Any]],
        tool_handler: ToolHandler,
        resume_handle: str | None = None,
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
        # Format:
        # [{"function_declarations": [{"name": "...", "description": "...", "parameters": {...}}]}]
        tools_config = [{"function_declarations": tools}]

        tool_names = [t["name"] for t in tools]
        preview = ", ".join(tool_names[:5])
        suffix = "..." if len(tools) > 5 else ""
        print(f"[DEBUG] Registering {len(tools)} tools with Live API: {preview}{suffix}")

        # Build session resumption config if we have a handle
        session_resumption_config = None
        if resume_handle:
            session_resumption_config = types.SessionResumptionConfig(handle=resume_handle)
            print("[GeminiLive] Resuming session with handle")
        else:
            # Request session resumption updates for future reconnection
            session_resumption_config = types.SessionResumptionConfig()
            print("[GeminiLive] Starting new session with resumption enabled")

        # Build config with tools, voice activity detection, and session resumption
        config = types.LiveConnectConfig(
            # NOTE: Some Live API configurations reject TEXT modality.
            # Keep AUDIO-only and rely on tool payloads + transcripts for debugging.
            response_modalities=["AUDIO"],
            system_instruction=types.Content(parts=[types.Part(text=self.system_prompt)]),
            # Enable input transcription for debugging + UX.
            input_audio_transcription=types.AudioTranscriptionConfig(),
            # Enable output transcription so logs reflect what was spoken.
            output_audio_transcription=types.AudioTranscriptionConfig(),
            # Tools must be raw dicts for Live API
            tools=tools_config,
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
            # - Longer silence_duration_ms: gives the user thinking time
            realtime_input_config=types.RealtimeInputConfig(
                automatic_activity_detection=types.AutomaticActivityDetection(
                    disabled=False,  # Keep server-side VAD enabled
                    start_of_speech_sensitivity=types.StartSensitivity.START_SENSITIVITY_LOW,
                    end_of_speech_sensitivity=types.EndSensitivity.END_SENSITIVITY_LOW,
                    prefix_padding_ms=100,  # Capture speech onset (default 20ms)
                    silence_duration_ms=self.vad_silence_duration_ms,
                ),
            ),
            # Session resumption for reconnection support
            session_resumption=session_resumption_config,
        )

        # Connect using async context manager
        self._session_context = self.client.aio.live.connect(model=self.live_model, config=config)
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

        This method is safe to call from multiple tasks (audio loop + response loop)
        because it is serialized with a lock.

        Returns:
            True if reconnection was successful, False otherwise
        """
        async with self._reconnect_lock:
            # Another task may have already reconnected.
            if self._connected and self.session is not None and self.is_connection_healthy():
                return True

            if self._reconnect_attempts >= self._max_reconnect_attempts:
                print(f"[Reconnect] Max attempts ({self._max_reconnect_attempts}) exceeded")
                return False

            if self.tool_handler is None:
                print("[Reconnect] Failed: tool_handler is not set")
                return False

            if self._last_tools is None:
                print("[Reconnect] Failed: No tools stored for reconnection")
                return False

            self._reconnect_attempts += 1
            delay = min(
                self._reconnect_delay * (2 ** (self._reconnect_attempts - 1)),
                self._max_reconnect_delay,
            )

            print(
                f"[Reconnect] Attempt {self._reconnect_attempts}/{self._max_reconnect_attempts} "
                f"in {delay:.1f}s (handle={'yes' if self._session_handle else 'no'})"
            )

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

                await self.connect(
                    tools=self._last_tools,
                    tool_handler=self.tool_handler,
                    resume_handle=self._session_handle,
                )

                print("[Reconnect] Success! Session resumed")
                return True

            except Exception as e:
                msg = str(e)

                # Some backends reject/expire the resumption handle and close with 1008.
                # In that case, clear the handle and start a fresh session.
                if self._session_handle and "not found" in msg.lower():
                    print("[Reconnect] Resume handle rejected; starting fresh session")
                    self._session_handle = None
                    try:
                        await self.connect(
                            tools=self._last_tools,
                            tool_handler=self.tool_handler,
                            resume_handle=None,
                        )
                        print("[Reconnect] Success! New session started")
                        return True
                    except Exception as e2:
                        print(f"[Reconnect] Fresh session failed: {e2}")

                print(f"[Reconnect] Failed: {e}")
                import traceback

                traceback.print_exc()
                self._connected = False
                return False

    @property
    def can_reconnect(self) -> bool:
        """Check if reconnection is possible."""
        return (
            self._reconnect_attempts < self._max_reconnect_attempts and self._last_tools is not None
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
                turns=[types.Content(role="user", parts=[types.Part(text=text)])],
                turn_complete=True,
            )
        )

    async def process_responses(
        self,
        audio_callback: Callable[[bytes], Any],
        text_callback: Callable[[str], Any] | None = None,
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
        self._current_turn_transcript = ""
        self._turn_had_tool_call = False
        self._input_transcript_buffer = ""
        self._output_transcript_buffer = ""

        # Some Live server implementations can emit TURN_COMPLETE slightly before the
        # last audio chunk(s) arrive. If we return immediately, playback sounds like it
        # "cuts off" and then resumes when the next receive loop starts.
        turn_complete_seen_at: float = 0.0
        generation_complete_seen = False
        last_audio_part_time: float = 0.0
        drain_after_turn_complete_s = 1.5
        max_drain_after_turn_complete_s = 10.0

        def _finish_turn() -> None:
            self._is_generating = False
            self._last_turn_transcript = self._current_turn_transcript
            self._last_turn_had_tool_call = self._turn_had_tool_call

        async def _flush_spoken() -> None:
            if not self._output_transcript_buffer.strip():
                return

            spoken = " ".join(self._output_transcript_buffer.split()).strip()
            self._output_transcript_buffer = ""
            print(f"[Gemini]: {spoken}")
            if self.conversation_logger:
                await self.conversation_logger.log_assistant_response(spoken)

        try:
            recv_iter = self.session.receive()
            while True:
                timeout_s: float | None = None
                if (
                    turn_complete_seen_at > 0 or generation_complete_seen
                ) and not self._in_tool_call:
                    timeout_s = drain_after_turn_complete_s

                try:
                    response = await asyncio.wait_for(recv_iter.__anext__(), timeout=timeout_s)
                except TimeoutError:
                    if (
                        turn_complete_seen_at > 0 or generation_complete_seen
                    ) and not self._in_tool_call:
                        await _flush_spoken()
                        _finish_turn()
                        print("[Turn finished (drain_timeout)]")
                        return
                    continue
                except StopAsyncIteration:
                    # If the stream ends after we already observed turn completion, treat it as a
                    # clean end-of-turn (some backends close the iterator immediately after
                    # TURN_COMPLETE).
                    if turn_complete_seen_at > 0 or generation_complete_seen:
                        await _flush_spoken()
                        _finish_turn()
                        print("[Turn finished (stream_end)]")
                        return
                    break

                self._last_response_time = time.time()
                response_count += 1

                # Debug: show what type of response we got
                response_types: list[str] = []
                if hasattr(response, "server_content") and response.server_content:
                    response_types.append("server_content")
                if hasattr(response, "tool_call") and response.tool_call:
                    response_types.append("tool_call")
                if hasattr(response, "setup_complete") and response.setup_complete:
                    response_types.append("setup_complete")
                if hasattr(response, "go_away") and response.go_away:
                    response_types.append("GO_AWAY")
                    self._go_away_received = True
                    time_left = getattr(response.go_away, "time_left", None)
                    if time_left:
                        print(f"[GO_AWAY: Server ending session, time left: {time_left}]")
                    else:
                        print("[GO_AWAY: Server ending session]")
                    print(f"[Session handle available: {'yes' if self._session_handle else 'no'}]")

                # Capture session resumption updates for reconnection
                if (
                    hasattr(response, "session_resumption_update")
                    and response.session_resumption_update
                ):
                    update = response.session_resumption_update
                    if hasattr(update, "new_handle") and update.new_handle:
                        self._session_handle = update.new_handle
                        print("[Session resumption handle updated]")

                # Check for turn state flags and always show them
                if hasattr(response, "server_content") and response.server_content:
                    sc = response.server_content
                    flags = []
                    if hasattr(sc, "turn_complete") and sc.turn_complete:
                        flags.append("TURN_COMPLETE")
                    if hasattr(sc, "generation_complete") and sc.generation_complete:
                        flags.append("GEN_COMPLETE")
                    if hasattr(sc, "interrupted") and sc.interrupted:
                        flags.append("INTERRUPTED")
                    if hasattr(sc, "input_transcription") and sc.input_transcription:
                        transcript = sc.input_transcription
                        transcript_text = getattr(transcript, "text", None)
                        transcript_finished = bool(getattr(transcript, "finished", False))

                        if transcript_text:
                            self._input_transcript_buffer += transcript_text

                        if transcript_finished and self._input_transcript_buffer.strip():
                            final_text = " ".join(self._input_transcript_buffer.split()).strip()
                            self._input_transcript_buffer = ""

                            # Keep one log line per user utterance.
                            print(f"[User]: {final_text}")

                            if self.tool_handler is not None:
                                state = self.tool_handler.session_state
                                state.last_user_transcript = final_text

                                # If we're awaiting confirmation to send a relay draft,
                                # dispatch immediately on explicit acknowledgment.
                                draft = state.active_draft
                                if draft is not None and draft.stage == "awaiting_confirmation":
                                    if self.tool_handler._is_acknowledgment(final_text):
                                        message = (
                                            draft.message.strip() or draft.topic.strip()
                                        ).strip()
                                        if message:
                                            target = draft.target_subagent
                                            topic = draft.topic
                                            try:
                                                result = (
                                                    await self.tool_handler.handle_send_to_thread(
                                                        message=message,
                                                        create_new_thread=True,
                                                        subagent=target,
                                                        topic=topic,
                                                        focus=True,
                                                    )
                                                )
                                                state.active_draft = None
                                                if isinstance(result, dict):
                                                    say = result.get("say")
                                                    thread_id = result.get("thread_id")
                                                    if isinstance(say, str) and say.strip():
                                                        state.enqueue_announcement(
                                                            say,
                                                            kind="wait_started",
                                                            thread_id=thread_id,
                                                        )
                                            except Exception as e:
                                                state.enqueue_announcement(
                                                    f"I couldn't reach the {target}: {e}",
                                                    kind="error",
                                                )

                            # Accumulate for turn-level routing.
                            self._current_turn_transcript = (
                                f"{self._current_turn_transcript} {final_text}".strip()
                            )

                            if self.conversation_logger:
                                await self.conversation_logger.log_user_speech(final_text)
                    if (
                        hasattr(sc, "turn_complete")
                        and sc.turn_complete
                        and self._input_transcript_buffer.strip()
                    ):
                        final_text = " ".join(self._input_transcript_buffer.split()).strip()
                        self._input_transcript_buffer = ""
                        print(f"[User]: {final_text}")
                        if self.tool_handler is not None:
                            state = self.tool_handler.session_state
                            state.last_user_transcript = final_text

                            draft = state.active_draft
                            if draft is not None and draft.stage == "awaiting_confirmation":
                                if self.tool_handler._is_acknowledgment(final_text):
                                    message = (draft.message.strip() or draft.topic.strip()).strip()
                                    if message:
                                        target = draft.target_subagent
                                        topic = draft.topic
                                        try:
                                            result = await self.tool_handler.handle_send_to_thread(
                                                message=message,
                                                create_new_thread=True,
                                                subagent=target,
                                                topic=topic,
                                                focus=True,
                                            )
                                            state.active_draft = None
                                            if isinstance(result, dict):
                                                say = result.get("say")
                                                thread_id = result.get("thread_id")
                                                if isinstance(say, str) and say.strip():
                                                    state.enqueue_announcement(
                                                        say,
                                                        kind="wait_started",
                                                        thread_id=thread_id,
                                                    )
                                        except Exception as e:
                                            state.enqueue_announcement(
                                                f"I couldn't reach the {target}: {e}",
                                                kind="error",
                                            )
                        self._current_turn_transcript = (
                            f"{self._current_turn_transcript} {final_text}".strip()
                        )
                        if self.conversation_logger:
                            await self.conversation_logger.log_user_speech(final_text)

                    if hasattr(sc, "generation_complete") and sc.generation_complete:
                        generation_complete_seen = True

                    if flags:
                        print(f"[Response #{response_count}: {flags}]")

                if response_count <= 10 or response_count % 20 == 0:
                    if response_types:
                        print(f"[Response #{response_count}: {response_types}]")
                    else:
                        attrs = [a for a in dir(response) if not a.startswith("_")]
                        print(f"[Response #{response_count}: attrs={attrs[:10]}]")

                # Handle server content (audio/text responses)
                if hasattr(response, "server_content") and response.server_content:
                    audio_emitted = await self._handle_server_content(
                        response.server_content, audio_callback, text_callback
                    )
                    if audio_emitted:
                        last_audio_part_time = time.time()

                # Handle tool calls
                handled_tool_call_this_response = False
                if hasattr(response, "tool_call") and response.tool_call:
                    self._turn_had_tool_call = True
                    await self._handle_tool_calls(response.tool_call)
                    handled_tool_call_this_response = True

                # Break on TURN_COMPLETE to restart the receive loop
                if hasattr(response, "server_content") and response.server_content:
                    sc = response.server_content
                    if hasattr(sc, "turn_complete") and sc.turn_complete:
                        if handled_tool_call_this_response:
                            print("[Turn complete on tool_call response - waiting for tool result]")
                        else:
                            if turn_complete_seen_at <= 0:
                                turn_complete_seen_at = time.time()
                            message = (
                                f"[Turn complete after {response_count} responses - "
                                "draining trailing audio if needed]"
                            )
                            print(message)

                # Drain trailing output after TURN_COMPLETE.
                # Exit once generation is complete, or once no new audio has arrived recently.
                if (
                    turn_complete_seen_at > 0 or generation_complete_seen
                ) and not self._in_tool_call:
                    now = time.time()
                    reference_time = (
                        turn_complete_seen_at if turn_complete_seen_at > 0 else last_audio_part_time
                    )

                    should_exit = False
                    reason = ""

                    # Give the backend a grace window to deliver trailing audio.
                    # TURN_COMPLETE can arrive slightly before the last audio chunks.
                    no_audio_grace_s = 0.8

                    if (
                        last_audio_part_time > 0
                        and now - last_audio_part_time >= drain_after_turn_complete_s
                    ):
                        should_exit = True
                        reason = "audio_drain"
                    elif (
                        last_audio_part_time <= 0
                        and reference_time > 0
                        and now - reference_time >= no_audio_grace_s
                    ):
                        should_exit = True
                        reason = (
                            "generation_complete_no_audio"
                            if generation_complete_seen
                            else "no_audio"
                        )
                    elif (
                        reference_time > 0
                        and now - reference_time >= max_drain_after_turn_complete_s
                    ):
                        should_exit = True
                        reason = "max_drain_timeout"

                    if should_exit:
                        await _flush_spoken()
                        _finish_turn()
                        print(f"[Turn finished ({reason})]")
                        return

        except asyncio.CancelledError:
            raise
        except Exception as e:
            # Convert unexpected websocket closes into a reconnectable error.
            self._connected = False
            module = e.__class__.__module__
            name = e.__class__.__name__
            msg = str(e)
            if module.startswith("websockets") and "ConnectionClosed" in name:
                raise ConnectionResetError(msg) from e
            if "no close frame received" in msg.lower():
                raise ConnectionResetError(msg) from e
            raise

        # Response iterator completed without TURN_COMPLETE - connection closed
        self._connected = False
        if self._go_away_received:
            message = (
                f"[Session ended after GO_AWAY ({response_count} responses) - "
                "reconnection available]"
            )
            print(message)
            raise ConnectionResetError(f"Session ended by GO_AWAY after {response_count} responses")

        warning = (
            f"[WARNING: Gemini session ended unexpectedly after {response_count} responses "
            "without TURN_COMPLETE]"
        )
        print(warning)
        print("[WebSocket connection was closed unexpectedly]")
        raise ConnectionResetError(
            f"Gemini session ended unexpectedly after {response_count} responses"
        )

    async def _handle_server_content(
        self,
        content,
        audio_callback: Callable[[bytes], Any],
        text_callback: Callable[[str], Any] | None,
    ) -> bool:
        """Handle audio and text responses from Gemini.

        Args:
            content: Server content
            audio_callback: Callback for audio playback
            text_callback: Optional callback for text
        """
        audio_emitted = False

        # Check turn state flags
        if hasattr(content, "generation_complete") and content.generation_complete:
            # Model finished generating output for this turn.
            self._is_generating = False
            print("[Generation complete]")

        if hasattr(content, "turn_complete") and content.turn_complete:
            # TURN_COMPLETE indicates the server has ended the user's turn, but audio chunks
            # may still arrive immediately afterward. We record the safe-point timestamp here,
            # and let the receive loop decide when it's safe to exit.
            self._last_turn_complete_time = time.time()

            if self._output_transcript_buffer.strip():
                spoken = " ".join(self._output_transcript_buffer.split()).strip()
                self._output_transcript_buffer = ""
                print(f"[Gemini]: {spoken}")
                if self.conversation_logger:
                    await self.conversation_logger.log_assistant_response(spoken)

            print("[Turn complete - ready for next input]")

        if hasattr(content, "output_transcription") and content.output_transcription:
            output = content.output_transcription
            output_text = getattr(output, "text", None)
            output_finished = bool(getattr(output, "finished", False))
            if output_text:
                self._output_transcript_buffer += output_text
            if output_finished and self._output_transcript_buffer.strip():
                spoken = " ".join(self._output_transcript_buffer.split()).strip()
                self._output_transcript_buffer = ""
                print(f"[Gemini]: {spoken}")
                if self.conversation_logger:
                    await self.conversation_logger.log_assistant_response(spoken)

        if hasattr(content, "interrupted") and content.interrupted:
            print("[Interrupted]")
            # Clear any buffered transcription because the model cancelled output.
            self._output_transcript_buffer = ""

            # Stop playback immediately so the user can speak.
            if self._voice_source and hasattr(self._voice_source, "stop_playback"):
                self._voice_source.stop_playback()

        # Handle model turn with parts
        if hasattr(content, "model_turn") and content.model_turn:
            for part in content.model_turn.parts:
                # Handle audio output
                if hasattr(part, "inline_data") and part.inline_data:
                    mime = getattr(part.inline_data, "mime_type", "")
                    if mime.startswith("audio/"):
                        self._is_generating = True
                        audio_emitted = True
                        await audio_callback(part.inline_data.data)

                # Handle text output (rare with AUDIO-only).
                # Prefer output_audio_transcription for logging what was spoken.
                if hasattr(part, "text") and part.text and text_callback:
                    await text_callback(part.text)

        return audio_emitted

    async def _handle_tool_calls(self, tool_call: types.LiveServerToolCall) -> None:
        """Handle tool calls from Gemini and send results back.

        Uses ToolResponse to cleanly separate result data from side effects
        like voice feedback and ambient audio control.

        Args:
            tool_call: Tool call from Gemini
        """
        if not self.tool_handler:
            return

        self._in_tool_call = True

        import time as _time

        start_time = _time.time()
        call_names = [c.name for c in tool_call.function_calls]
        print(f"[ToolCall] Received {len(call_names)} tool call(s): {call_names}")

        function_responses = []

        # NOTE: Waiting music is managed centrally by the relay safe-point loop
        # based on active thread wait state. Avoid starting music for ordinary tool
        # calls (like select_project), which feels like lag.
        long_wait_tools: set[str] = set()

        for call in tool_call.function_calls:
            call_start = _time.time()
            print(f"[ToolCall] Dispatching {call.name}...")

            auto_ambient_started = False
            if (
                self.ambient_audio
                and call.name in long_wait_tools
                and not self.ambient_audio.is_playing
            ):
                auto_ambient_started = True
                await self.ambient_audio.start_work_music()

            response = await self._dispatch_tool_call(call.name, call.args or {})

            call_duration = _time.time() - call_start
            result_summary = (
                str(response.result)[:200] + "..."
                if len(str(response.result)) > 200
                else str(response.result)
            )
            print(f"[ToolCall] {call.name} completed in {call_duration:.1f}s: {result_summary}")

            # Handle side effects separately from the result.
            # IMPORTANT: Do not send additional Gemini "user" turns while handling tool calls.
            # That can cause Gemini to start new turns and re-issue tool calls before it has
            # processed our function responses (leading to loops and timing drift).
            result_payload = dict(response.result or {})

            if response.voice_feedback:
                # Provide voice guidance as part of the tool result so Gemini can speak it
                # in its normal post-tool response.
                if "say" in result_payload and isinstance(result_payload["say"], str):
                    if result_payload["say"].strip() != response.voice_feedback.strip():
                        result_payload["say"] = (
                            f"{result_payload['say']} {response.voice_feedback}".strip()
                        )
                else:
                    result_payload["say"] = response.voice_feedback

            # Make relay instructions extra obvious to the Live model.
            if "say" in result_payload and isinstance(result_payload["say"], str):
                result_payload.setdefault("relay_to_user", result_payload["say"])

            if self.ambient_audio:
                if response.start_ambient:
                    await self.ambient_audio.start_work_music()
                elif response.stop_ambient:
                    await self.ambient_audio.stop_work_music()
                elif auto_ambient_started:
                    # Default behavior: long-wait music only during the tool call.
                    await self.ambient_audio.stop_work_music()

            function_responses.append(
                types.FunctionResponse(
                    id=call.id,
                    name=call.name,
                    response=result_payload,
                )
            )

        total_duration = _time.time() - start_time
        summary = (
            f"[ToolCall] All tool calls completed in {total_duration:.1f}s, "
            f"sending {len(function_responses)} response(s) to Gemini"
        )
        print(summary)

        # Send tool responses back to Gemini
        try:
            await self.session.send_tool_response(
                function_responses=function_responses,
            )
            print("[ToolCall] Tool responses sent successfully - waiting for Gemini's response")
        except Exception as e:
            print(f"[ToolCall] ERROR sending tool responses: {e}")
            import traceback

            traceback.print_exc()
        finally:
            self._in_tool_call = False

    async def _dispatch_tool_call(self, name: str, args: dict[str, Any]) -> ToolResponse:
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
            # Combined intent tools
            "engage_with_project": self.tool_handler.handle_engage_with_project,
            # Planning and context
            "engage_planner": self.tool_handler.handle_engage_planner,
            "continue_planner": self.tool_handler.handle_continue_planner,
            "finalize_builder_prompt": self.tool_handler.handle_finalize_builder_prompt,
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
            # Brainstormer
            "engage_brainstormer": self.tool_handler.handle_engage_brainstormer,
            "continue_brainstormer": self.tool_handler.handle_continue_brainstormer,
            # Subagent conversation flow
            "confirm_send_to_subagent": self.tool_handler.handle_confirm_send_to_subagent,
            # Threaded subagent sessions
            "start_subagent_thread": self.tool_handler.handle_start_subagent_thread,
            "send_to_thread": self.tool_handler.handle_send_to_thread,
            "list_threads": self.tool_handler.handle_list_threads,
            "focus_thread": self.tool_handler.handle_focus_thread,
            "open_thread": self.tool_handler.handle_open_thread,
            # Builder plan management
            "send_to_builder": self.tool_handler.handle_send_to_builder,
            "get_builder_plan": self.tool_handler.handle_get_builder_plan,
            "approve_builder_plan": self.tool_handler.handle_approve_builder_plan,
        }

        handler = handlers.get(name)
        if handler:
            try:
                raw_response = await handler(**args)

                if isinstance(raw_response, ToolResponse):
                    response = raw_response
                elif isinstance(raw_response, dict):
                    response = ToolResponse(result=raw_response)
                else:
                    type_name = type(raw_response).__name__
                    response = ToolResponse(
                        result={
                            "error": f"Tool '{name}' returned invalid response type: {type_name}"
                        }
                    )

                # Log tool call completion for dashboard
                if self.conversation_logger:
                    await self.conversation_logger.log_tool_call_complete(name, response.result)
                return response
            except Exception as e:
                error_response = ToolResponse(result={"error": str(e)})
                # Log tool call error for dashboard
                if self.conversation_logger:
                    await self.conversation_logger.log_tool_call_complete(
                        name, error_response.result
                    )
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
        opencode_url: str = "http://localhost:4158",
        workspace_path: str = ".conversator",
        config: ConversatorConfig | None = None,
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
            self.opencode, state=self.state, prompt_manager=self.prompt_manager, config=self.config
        )

        # Use system prompt path from config
        system_prompt_path = self.config.voice_system_prompt

        vad_seconds = getattr(self.config, "voice_end_of_speech_silence_seconds_normal", 5.0)
        vad_ms = int(vad_seconds * 1000)

        live_model = getattr(self.config, "voice_live_model", "gemini-2.0-flash-exp")

        self.conversator = ConversatorVoice(
            api_key,
            system_prompt_path=system_prompt_path,
            vad_silence_duration_ms=vad_ms,
            live_model=live_model,
        )
        self.tools = CONVERSATOR_TOOLS

    async def start(self) -> None:
        """Start the session and create initial task."""
        await self.conversator.connect(self.tools, self.tool_handler)

        # Create a new task for this session
        self.current_task = self.state.create_task(
            title="Voice Session",
            working_prompt_path=str(self.workspace_path / "prompts" / "current" / "working.md"),
        )

        # Set up prompt manager for this task
        self.tool_handler.current_task_id = self.current_task.task_id
        await self.prompt_manager.init_working_prompt(
            self.current_task.task_id, title="Voice Session"
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
