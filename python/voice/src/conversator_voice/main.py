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


async def run_conversator(
    source_type: str,
    opencode_url: str = "http://localhost:4096",
    config_path: str = ".conversator/config.yaml",
    dashboard_port: int = 8080,
    **source_kwargs
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
    parsed_url = urlparse(opencode_url)
    opencode_port = parsed_url.port or config.opencode_port

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
            print("The subagents (planner, context-reader, etc.) are REQUIRED for Conversator to function.")
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

    print(f"Starting Conversator ({source_type})...")
    print(f"Dashboard will be available at http://localhost:{dashboard_port}")

    try:
        # Start voice capture
        await voice.start()
        print("Voice source ready")

        # Connect to Gemini Live
        await session.start()
        print("Connected to Gemini Live")

        print("\nConversator ready. Start speaking...\n")

        # Create background monitor for task completion
        monitor = BuilderMonitor(
            state=session.state,
            builders=session.tool_handler.builders,
            interval=5.0
        )

        # Completion handler for voice notification
        async def on_task_complete(task_id: str, status: str, info: dict):
            title = info.get("title", "Task")
            print(f"\n[TASK {status.upper()}] {title}\n")

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

        # Start dashboard server
        import uvicorn
        dashboard_config = uvicorn.Config(
            dashboard_app,
            host="0.0.0.0",
            port=dashboard_port,
            log_level="warning"
        )
        dashboard_server = uvicorn.Server(dashboard_config)

        try:
            # Run all loops concurrently
            await asyncio.gather(
                _audio_send_loop(voice, session),
                _response_process_loop(voice, session),
                monitor.start(on_completion=on_task_complete),
                dashboard_server.serve(),
                return_exceptions=True
            )
        finally:
            await monitor.stop()

    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        await session.stop()
        await voice.stop()
        await opencode_manager.stop()


async def _audio_send_loop(voice, session: ConversatorSession) -> None:
    """Send audio from voice source to Gemini.

    Args:
        voice: Voice source
        session: Conversator session
    """
    import numpy as np
    chunk_count = 0

    async for chunk in voice.get_audio_chunks():
        try:
            # Check for text command (from Telegram)
            if isinstance(chunk, bytes) and chunk.startswith(b"TEXT:"):
                text = chunk[5:].decode()
                await session.conversator.send_text(text)
            else:
                # Check audio level (threshold tuned for typical background noise)
                audio_array = np.frombuffer(chunk, dtype=np.int16)
                rms = np.sqrt(np.mean(audio_array.astype(np.float32)**2))
                is_speech = rms > 1500  # Higher threshold to filter background noise

                await session.conversator.send_audio(chunk)
                chunk_count += 1

                # Log every 50 chunks with audio level
                if chunk_count % 50 == 0:
                    level = "SPEECH" if is_speech else "silence"
                    print(f"[Audio #{chunk_count}: {level} (rms={rms:.0f})]")
        except Exception as e:
            print(f"Error sending audio: {e}")


async def _response_process_loop(voice, session: ConversatorSession) -> None:
    """Process responses from Gemini and play audio.

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
    while True:
        try:
            await session.conversator.process_responses(play_audio, handle_text)
            # After turn completes, continue listening for next turn
            print("[Restarting response listener for next turn...]")
        except Exception as e:
            print(f"Response processing error: {e}")
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
"""
    )

    parser.add_argument(
        "--source",
        choices=["local", "discord", "telegram"],
        default="local",
        help="Voice input source (default: local)"
    )

    parser.add_argument(
        "--opencode-url",
        default="http://localhost:4096",
        help="OpenCode server URL (default: http://localhost:4096)"
    )

    parser.add_argument(
        "--config",
        default=".conversator/config.yaml",
        help="Path to config file (default: .conversator/config.yaml)"
    )

    parser.add_argument(
        "--dashboard-port",
        type=int,
        default=8080,
        help="Dashboard server port (default: 8080)"
    )

    parser.add_argument(
        "--discord-token",
        help="Discord bot token (or set DISCORD_BOT_TOKEN env var)"
    )

    parser.add_argument(
        "--telegram-token",
        help="Telegram bot token (or set TELEGRAM_BOT_TOKEN env var)"
    )

    parser.add_argument(
        "--telegram-users",
        type=int,
        nargs="*",
        help="Telegram user IDs allowed to use the bot"
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
    asyncio.run(run_conversator(
        source_type=args.source,
        opencode_url=args.opencode_url,
        config_path=args.config,
        dashboard_port=args.dashboard_port,
        **source_kwargs
    ))


if __name__ == "__main__":
    cli()
