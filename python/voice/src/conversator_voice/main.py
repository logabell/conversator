"""Main entry point for Conversator voice interface."""

import argparse
import asyncio
import os
import sys
from urllib.parse import urlparse

from .config import ConversatorConfig
from .gemini_live import ConversatorSession
from .monitor import BuilderMonitor
from .opencode_manager import OpenCodeManager
from .voice_sources import create_voice_source
from .dashboard import ConversationLogger, create_dashboard_app
from .ambient_audio import AmbientAudioController


async def run_conversator(
    source_type: str,
    opencode_url: str | None = None,
    config_path: str = ".conversator/config.yaml",
    dashboard_port: int = 8080,
    **source_kwargs,
) -> None:
    """Run the Conversator voice interface.

    Args:
        source_type: Voice source type (local, discord, telegram)
        opencode_url: URL of OpenCode server
        config_path: Path to config file
        dashboard_port: Port for dashboard API server
        **source_kwargs: Additional kwargs for voice source
    """
    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        print("Error: GOOGLE_API_KEY environment variable not set")
        sys.exit(1)

    # Find config file and determine project root BEFORE loading config
    # Config is at .conversator/config.yaml, so project root is parent of .conversator
    from pathlib import Path

    config_file = Path(config_path)
    if config_file.is_absolute() and config_file.exists():
        conversator_project_root = config_file.parent.parent
    else:
        # Relative path - check if it exists relative to cwd
        config_file = Path.cwd() / config_path
        if config_file.exists():
            conversator_project_root = config_file.parent.parent
            config_path = str(config_file)  # Use absolute path
        else:
            # Fall back to searching upward for .conversator/config.yaml (not just .conversator dir)
            # This ensures we find the main project root with full config, not partial directories
            conversator_project_root = Path.cwd()
            found = False
            while conversator_project_root != conversator_project_root.parent:
                potential_config = conversator_project_root / ".conversator" / "config.yaml"
                if potential_config.exists():
                    config_path = str(potential_config)
                    found = True
                    break
                conversator_project_root = conversator_project_root.parent
            if not found:
                # No config found, use cwd
                conversator_project_root = Path.cwd()
                print(f"Warning: No config file found, using defaults")

    print(f"Conversator project root: {conversator_project_root}")

    # Load configuration from the found path
    config = ConversatorConfig.load(config_path)
    print(f"Root project directory: {config.root_project_dir}")
    print(f"Configured builders: {list(config.builders.keys())}")

    # Parse OpenCode port from URL or use config
    if opencode_url:
        parsed_url = urlparse(opencode_url)
        opencode_port = parsed_url.port or config.conversator_port
    else:
        opencode_url = config.opencode_base_url
        opencode_port = config.conversator_port

    # Create OpenCode manager with proper isolation
    # Working dir is the conversator project root (where .conversator/ and conversator/agents/ are)
    opencode_manager = OpenCodeManager(
        port=opencode_port,
        working_dir=str(conversator_project_root),
        start_timeout=config.opencode_start_timeout,
        config_dir=config.opencode_config_dir,
        agents_source="conversator/agents",  # Versioned agent source
    )

    # Check if OpenCode is already running
    opencode_available = await opencode_manager.health_check()

    if opencode_available:
        print(f"OpenCode orchestration connected (port {opencode_port})")
    else:
        # Try to auto-start OpenCode (this is CRITICAL for functionality)
        print(f"Starting OpenCode orchestration layer (port {opencode_port})...")
        opencode_available = await opencode_manager.start()
        if opencode_available:
            if opencode_manager.is_managed:
                print("OpenCode orchestration started successfully")
            else:
                print("OpenCode orchestration connected (external process)")
        else:
            # FAIL FAST - subagents are critical for the voice conversation
            print("\nERROR: Failed to start OpenCode orchestration layer!")
            print(
                "The subagents (planner, context-reader, etc.) are REQUIRED for Conversator to function."
            )
            print("\nPossible solutions:")
            print("  1. Check if port 4096 is already in use: lsof -i :4096")
            print("  2. Check OpenCode installation: which opencode")
            print("  3. Check logs in .conversator/cache/")
            print("  4. Try running manually: scripts/start-conversator.sh")
            sys.exit(1)

    # Create voice source
    voice = create_voice_source(source_type, **source_kwargs)

    # Create conversation logger for dashboard
    conversation_logger = ConversationLogger()

    # Create Conversator session with config
    session = ConversatorSession(api_key, opencode_url, config=config)

    # Wire up conversation logger to the voice agent
    session.conversator.conversation_logger = conversation_logger

    # Create ambient audio controller for background music during work
    # Look for ambient_work.{ogg,mp3,wav} in the audio directory
    ambient_audio_path = None
    for ext in ["ogg", "mp3", "wav"]:
        candidate = conversator_project_root / ".conversator" / "audio" / f"ambient_work.{ext}"
        if candidate.exists():
            ambient_audio_path = candidate
            break

    ambient_audio = AmbientAudioController(
        music_path=str(ambient_audio_path) if ambient_audio_path else None,
        volume=0.15,
        ducked_volume=0.03,
        fade_duration=2.0,
    )

    # Connect ambient audio to voice source for ducking coordination
    # (Will be set after voice source is created)
    session.conversator.set_ambient_audio(ambient_audio)

    print(f"Starting Conversator ({source_type})...")
    print(f"Dashboard will be available at http://localhost:{dashboard_port}")

    try:
        # Start voice capture
        await voice.start()
        print("Voice source ready")

        # Connect ambient audio to voice source for ducking
        # The LocalVoiceSource has _is_playing flag that ambient audio can check
        if hasattr(voice, "_is_playing"):
            ambient_audio.set_voice_source(voice)
            print("Ambient audio ducking enabled")

        # Connect to Gemini Live
        await session.start()
        print("Connected to Gemini Live")

        # Connect voice source to conversator for interrupt handling
        # This allows stopping playback immediately when user interrupts
        if hasattr(voice, "stop_playback"):
            session.conversator.set_voice_source(voice)
            print("Voice interrupt handling enabled")

        print("\nConversator ready. Start speaking...\n")

        # Create background monitor for task completion
        monitor = BuilderMonitor(
            state=session.state, builders=session.tool_handler.builders, interval=5.0
        )

        # Completion handler for voice notification
        async def on_task_complete(task_id: str, status: str, info: dict):
            title = info.get("title", "Task")
            print(f"\n[TASK {status.upper()}] {title}\n")
            # Stop ambient music when task completes
            if ambient_audio:
                await ambient_audio.stop_work_music()

        # Create dashboard app with all dependencies
        dashboard_app = create_dashboard_app(
            state=session.state,
            tool_handler=session.tool_handler,
            config=config,
            conversation_logger=conversation_logger,
            opencode_client=session.opencode,
            opencode_manager=opencode_manager,
            conversator_session=session,
        )

        # Wire up activity callback from OpenCode to WebSocket
        # This enables real-time activity feed updates in the dashboard
        ws_manager = dashboard_app.state.ws_manager

        async def activity_callback(
            agent: str, action: str, message: str, detail: str | None
        ) -> None:
            """Broadcast activity events to dashboard."""
            # Broadcast to dashboard WebSocket clients
            await ws_manager.broadcast_activity(
                agent=agent, action=action, message=message, detail=detail
            )
            # Note: Voice feedback is now handled via ToolResponse.voice_feedback
            # and ambient audio via ToolResponse.start_ambient/stop_ambient

        # Set the callback on the OpenCode client
        session.opencode.set_activity_callback(activity_callback)
        print("Activity feed connected to dashboard and voice")

        # Wire up Gemini transcript to WebSocket for real-time voice transcript viewing
        async def gemini_transcript_listener(entry):
            """Broadcast Gemini transcript entries to dashboard."""
            # Only broadcast user speech and assistant responses (not tool calls, they're separate)
            if entry.role in ("user", "assistant"):
                await ws_manager.broadcast_gemini_transcript(
                    role=entry.role,
                    content=entry.content,
                    is_tool_call=False,
                )
            elif entry.role == "tool_call" and entry.tool_name:
                await ws_manager.broadcast_gemini_transcript(
                    role="tool_call",
                    content=f"Calling {entry.tool_name}",
                    is_tool_call=True,
                    tool_name=entry.tool_name,
                    tool_args=entry.tool_args,
                )

        conversation_logger.add_listener(gemini_transcript_listener)
        print("Gemini transcript connected to dashboard")

        # Clean up any stale processes on the dashboard port
        await _cleanup_port(dashboard_port)

        # Start dashboard server
        import uvicorn

        dashboard_config = uvicorn.Config(
            dashboard_app, host="0.0.0.0", port=dashboard_port, log_level="warning"
        )
        dashboard_server = uvicorn.Server(dashboard_config)

        try:
            # Run all loops concurrently.
            # IMPORTANT: fail fast if any critical loop crashes; otherwise audio
            # forwarding can silently stop and Gemini will never detect speech.
            import traceback

            # Start the monitor loop and treat its internal task as a critical loop.
            await monitor.start(on_completion=on_task_complete)
            monitor_task = monitor._task
            if monitor_task is not None:
                monitor_task.set_name("builder_monitor")

            tasks = [
                asyncio.create_task(
                    _audio_send_loop(voice, session, config),
                    name="audio_send_loop",
                ),
                asyncio.create_task(
                    _response_process_loop(voice, session),
                    name="response_process_loop",
                ),
                asyncio.create_task(
                    dashboard_server.serve(),
                    name="dashboard_server",
                ),
            ]
            if monitor_task is not None:
                tasks.append(monitor_task)

            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)

            # Any loop exiting is unexpected; treat it as fatal.
            for t in done:
                exc = t.exception()
                if exc is None:
                    exc = RuntimeError(f"Task '{t.get_name()}' exited unexpectedly")
                print(f"[FATAL] {t.get_name()} crashed: {exc}")
                traceback.print_exception(exc)

            for t in pending:
                t.cancel()
            await asyncio.gather(*pending, return_exceptions=True)

            # Re-raise the first exception to stop the app.
            first_exc = next((t.exception() for t in done if t.exception() is not None), None)
            raise first_exc or RuntimeError("Conversator stopped unexpectedly")
        finally:
            await monitor.stop()

    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        # Stop ambient audio
        if ambient_audio:
            ambient_audio.stop()
        await session.stop()
        await voice.stop()
        await opencode_manager.stop()


async def _cleanup_port(port: int) -> None:
    """Clean up any stale processes holding a port.

    Args:
        port: Port number to clean up
    """
    import re
    import subprocess

    try:
        # Use ss to find processes listening on the port
        result = subprocess.run(
            ["ss", "-tlnp", f"sport = :{port}"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0 and result.stdout:
            # Extract PID from output like: users:(("python",pid=12345,fd=15))
            match = re.search(r"pid=(\d+)", result.stdout)
            if match:
                pid = int(match.group(1))
                print(f"Found process (PID {pid}) on port {port}, terminating...")
                try:
                    os.kill(pid, 15)  # SIGTERM
                    await asyncio.sleep(1)
                    # Check if still running
                    try:
                        os.kill(pid, 0)  # Just check
                        print(f"Process {pid} didn't terminate, killing...")
                        os.kill(pid, 9)  # SIGKILL
                        await asyncio.sleep(0.5)
                    except OSError:
                        pass  # Process already dead
                    print(f"Port {port} cleared")
                except OSError as e:
                    print(f"Could not kill PID {pid}: {e}")
    except Exception as e:
        print(f"Port cleanup check failed (non-critical): {e}")


async def _audio_send_loop(voice, session: ConversatorSession, config: ConversatorConfig) -> None:
    """Send audio from voice source to Gemini.

    Includes silence detection to help Gemini's VAD by calling send_audio_end()
    after extended silence following speech.

    Args:
        voice: Voice source
        session: Conversator session
        config: Conversator configuration
    """
    import numpy as np

    chunk_count = 0
    last_speech_chunk = 0  # Track when we last detected speech
    consecutive_errors = 0
    audio_end_sent = False  # Track if we've sent audio_end since last speech
    SILENCE_CHUNKS_THRESHOLD = 10  # ~1 second at 100ms chunks
    speech_threshold = config.voice_speech_threshold

    print(f"[Audio send loop starting (speech threshold: {speech_threshold})...]")
    try:
        async for chunk in voice.get_audio_chunks():
            try:
                # Check for text command (from Telegram)
                if isinstance(chunk, bytes) and chunk.startswith(b"TEXT:"):
                    text = chunk[5:].decode()
                    await session.conversator.send_text(text)
                else:
                    # Check audio level (threshold from config)
                    # Use higher threshold when model is generating to reduce false positives from echo
                    audio_array = np.frombuffer(chunk, dtype=np.int16)
                    rms = np.sqrt(np.mean(audio_array.astype(np.float32) ** 2))
                    is_generating = session.conversator._is_generating
                    effective_threshold = (
                        speech_threshold * 3 if is_generating else speech_threshold
                    )
                    is_speech = rms > effective_threshold

                    await session.conversator.send_audio(chunk)
                    chunk_count += 1
                    consecutive_errors = 0  # Reset on success

                    if is_speech:
                        last_speech_chunk = chunk_count
                        audio_end_sent = False  # Reset - new speech detected
                    else:
                        # Check for extended silence after speech - signal end of speech to Gemini
                        if last_speech_chunk > 0 and not audio_end_sent:
                            chunks_since_speech = chunk_count - last_speech_chunk
                            if chunks_since_speech == SILENCE_CHUNKS_THRESHOLD:
                                try:
                                    await session.conversator.send_audio_end()
                                    audio_end_sent = True
                                    print(
                                        f"[Audio] Sent audio_end signal after {SILENCE_CHUNKS_THRESHOLD} silent chunks"
                                    )
                                except Exception as e:
                                    print(f"[Audio] Failed to send audio_end: {e}")

                    # Log every 50 chunks with audio level (more frequent when speech detected)
                    # Also log first 5 chunks for debugging startup
                    log_interval = 25 if is_speech else 50
                    if chunk_count <= 5 or chunk_count % log_interval == 0:
                        level = "SPEECH" if is_speech else "silence"
                        chunks_since_speech = (
                            chunk_count - last_speech_chunk if last_speech_chunk > 0 else "never"
                        )
                        gen_state = "GEN" if session.conversator._is_generating else "idle"
                        print(
                            f"[Audio #{chunk_count}: {level} (rms={rms:.0f}), last speech: {chunks_since_speech}, state: {gen_state}]"
                        )
            except Exception as e:
                consecutive_errors += 1
                print(f"Error sending audio chunk #{chunk_count}: {e}")
                if consecutive_errors >= 5:
                    print(
                        f"[Audio loop] Too many consecutive errors ({consecutive_errors}), breaking"
                    )
                    import traceback

                    traceback.print_exc()
                    break
    except Exception as e:
        print(f"[Audio loop] Fatal error in audio send loop: {e}")
        import traceback

        traceback.print_exc()
    finally:
        print(f"[Audio loop] Ended after {chunk_count} chunks")


async def _response_process_loop(voice, session: ConversatorSession) -> None:
    """Process responses from Gemini and play audio.

    Handles automatic reconnection when the connection is lost.

    Args:
        voice: Voice source for audio playback
        session: Conversator session
    """
    audio_chunks_received = 0

    async def play_audio(data: bytes) -> None:
        nonlocal audio_chunks_received
        audio_chunks_received += 1
        if audio_chunks_received % 10 == 1:
            print(f"[Receiving audio... {len(data)} bytes]")
        await voice.play_audio(data)

    async def handle_text(text: str) -> None:
        # Text is already printed in gemini_live.py
        pass

    # Keep processing responses across multiple turns
    turn_count = 0
    while True:
        try:
            turn_count += 1
            print(f"\n[=== Starting turn #{turn_count} - waiting for Gemini responses ===]")
            await session.conversator.process_responses(play_audio, handle_text)

            # Wait for playback to complete before starting next turn
            # This prevents the microphone from picking up still-playing audio
            # and causing false interrupts that create a feedback loop
            if hasattr(voice, "wait_for_playback_complete"):
                print("[Waiting for playback to complete...]")
                completed = await voice.wait_for_playback_complete(timeout=10.0)
                if not completed:
                    print("[Warning: Playback timeout - continuing anyway]")

            # After turn completes, continue listening for next turn
            print(f"[=== Turn #{turn_count} complete - restarting for next turn ===]")
            print("[Gemini is now listening for your voice input...]")
        except ConnectionResetError as e:
            # Connection was lost - attempt to reconnect
            print(f"\n[Connection lost on turn #{turn_count}: {e}]")

            if session.conversator.can_reconnect:
                print("[Attempting to reconnect...]")
                if await session.conversator.reconnect():
                    print("[Reconnected successfully - resuming conversation]")
                    print("[Gemini is now listening for your voice input...]")
                    continue
                else:
                    print("[Reconnection failed after all attempts - exiting]")
                    break
            else:
                print("[Cannot reconnect (max attempts exceeded or no tools stored) - exiting]")
                break
        except Exception as e:
            print(f"Response processing error on turn #{turn_count}: {e}")
            import traceback

            traceback.print_exc()
            break


def cli() -> None:
    """Command-line interface entry point."""
    parser = argparse.ArgumentParser(
        description="Conversator - Voice-first development assistant",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Local microphone (Linux Wayland via VoxType)
  conversator-voice --source local

  # Discord voice call
  conversator-voice --source discord --discord-token $DISCORD_BOT_TOKEN

  # Telegram voice messages
  conversator-voice --source telegram --telegram-token $TELEGRAM_BOT_TOKEN

Environment variables:
  GOOGLE_API_KEY      Required. Gemini API key.
  DISCORD_BOT_TOKEN   Required for Discord source.
  TELEGRAM_BOT_TOKEN  Required for Telegram source.

Dashboard:
  A web dashboard is available at http://localhost:8080 (configurable with --dashboard-port).
  It shows real-time conversation logs, task status, builder health, and notifications.
""",
    )

    parser.add_argument(
        "--source",
        choices=["local", "discord", "telegram"],
        default="local",
        help="Voice input source (default: local)",
    )

    parser.add_argument(
        "--opencode-url",
        default=None,
        help="OpenCode server URL (default: uses conversator.port from config.yaml)",
    )

    parser.add_argument(
        "--config",
        default=".conversator/config.yaml",
        help="Path to config file (default: .conversator/config.yaml)",
    )

    parser.add_argument(
        "--dashboard-port", type=int, default=8080, help="Dashboard server port (default: 8080)"
    )

    parser.add_argument(
        "--discord-token", help="Discord bot token (or set DISCORD_BOT_TOKEN env var)"
    )

    parser.add_argument(
        "--telegram-token", help="Telegram bot token (or set TELEGRAM_BOT_TOKEN env var)"
    )

    parser.add_argument(
        "--telegram-users", type=int, nargs="*", help="Telegram user IDs allowed to use the bot"
    )

    args = parser.parse_args()

    # Build source kwargs
    source_kwargs = {}

    if args.source == "discord":
        token = args.discord_token or os.environ.get("DISCORD_BOT_TOKEN")
        if not token:
            print("Error: Discord token required. Use --discord-token or set DISCORD_BOT_TOKEN")
            sys.exit(1)
        source_kwargs["bot_token"] = token

    elif args.source == "telegram":
        token = args.telegram_token or os.environ.get("TELEGRAM_BOT_TOKEN")
        if not token:
            print("Error: Telegram token required. Use --telegram-token or set TELEGRAM_BOT_TOKEN")
            sys.exit(1)
        source_kwargs["bot_token"] = token
        if args.telegram_users:
            source_kwargs["allowed_users"] = args.telegram_users

    # Run the main loop
    asyncio.run(
        run_conversator(
            source_type=args.source,
            opencode_url=args.opencode_url,
            config_path=args.config,
            dashboard_port=args.dashboard_port,
            **source_kwargs,
        )
    )


if __name__ == "__main__":
    cli()
