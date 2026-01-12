"""Main entry point for Conversator voice interface."""

import argparse
import asyncio
import os
import sys

from .gemini_live import ConversatorSession
from .voice_sources import create_voice_source


async def run_conversator(
    source_type: str,
    opencode_url: str = "http://localhost:8001",
    **source_kwargs
) -> None:
    """Run the Conversator voice interface.

    Args:
        source_type: Voice source type (local, discord, telegram)
        opencode_url: URL of OpenCode server
        **source_kwargs: Additional kwargs for voice source
    """
    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        print("Error: GOOGLE_API_KEY environment variable not set")
        sys.exit(1)

    # Create voice source
    voice = create_voice_source(source_type, **source_kwargs)

    # Create Conversator session
    session = ConversatorSession(api_key, opencode_url)

    print(f"Starting Conversator ({source_type})...")

    try:
        # Start voice capture
        await voice.start()
        print("Voice source ready")

        # Connect to Gemini Live
        await session.start()
        print("Connected to Gemini Live")

        # Check if OpenCode is available
        if await session.opencode.health_check():
            print("OpenCode subagents connected")
        else:
            print("Warning: OpenCode not available - subagents won't work")

        print("\nConversator ready. Start speaking...\n")

        # Run audio processing loops concurrently
        await asyncio.gather(
            _audio_send_loop(voice, session),
            _response_process_loop(voice, session),
            return_exceptions=True
        )

    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        await session.stop()
        await voice.stop()


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
        default="http://localhost:8001",
        help="OpenCode server URL (default: http://localhost:8001)"
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
        **source_kwargs
    ))


if __name__ == "__main__":
    cli()
