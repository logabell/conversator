"""Voice input from Telegram - voice messages streamed to Gemini."""

import asyncio
import io
from typing import AsyncIterator, Optional

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)


class TelegramVoiceSource:
    """Voice source that captures audio from Telegram voice messages.

    The bot receives voice messages and streams them to Gemini Live.
    Responses are sent back as voice messages.
    """

    def __init__(self, bot_token: str, allowed_users: Optional[list[int]] = None):
        """Initialize Telegram voice source.

        Args:
            bot_token: Telegram bot token from @BotFather
            allowed_users: Optional list of user IDs allowed to use the bot
        """
        self.bot_token = bot_token
        self.allowed_users = allowed_users or []
        self._running = False
        self._audio_queue: asyncio.Queue[bytes] = asyncio.Queue()
        self._response_queue: asyncio.Queue[tuple[int, bytes]] = asyncio.Queue()
        self._current_chat_id: Optional[int] = None

        # Build application
        self.app = Application.builder().token(bot_token).build()
        self._setup_handlers()

    def _setup_handlers(self) -> None:
        """Set up message handlers."""

        async def start_command(
            update: Update, context: ContextTypes.DEFAULT_TYPE
        ) -> None:
            """Handle /start command."""
            user = update.effective_user
            if self.allowed_users and user.id not in self.allowed_users:
                await update.message.reply_text("Sorry, you're not authorized.")
                return

            await update.message.reply_text(
                "Hello! I'm Conversator. Send me voice messages and I'll help "
                "you with your development tasks. You can also type messages."
            )

        async def voice_message(
            update: Update, context: ContextTypes.DEFAULT_TYPE
        ) -> None:
            """Handle incoming voice messages."""
            user = update.effective_user
            if self.allowed_users and user.id not in self.allowed_users:
                return

            self._current_chat_id = update.effective_chat.id

            # Download voice file
            voice = update.message.voice
            file = await context.bot.get_file(voice.file_id)

            # Download to bytes
            voice_bytes = io.BytesIO()
            await file.download_to_memory(voice_bytes)
            voice_bytes.seek(0)

            # Convert OGG/Opus to PCM (Telegram uses Opus codec)
            pcm_data = await self._convert_opus_to_pcm(voice_bytes.read())

            # Queue for processing
            await self._audio_queue.put(pcm_data)

            # Send typing indicator while processing
            await context.bot.send_chat_action(
                chat_id=update.effective_chat.id,
                action="record_voice"
            )

        async def text_message(
            update: Update, context: ContextTypes.DEFAULT_TYPE
        ) -> None:
            """Handle text messages (for typed commands)."""
            user = update.effective_user
            if self.allowed_users and user.id not in self.allowed_users:
                return

            self._current_chat_id = update.effective_chat.id

            # For text, we could use TTS or just process as text
            # For now, acknowledge and suggest voice
            await update.message.reply_text(
                "Got it! For the best experience, send voice messages. "
                "I'll process your text request."
            )

            # Convert text to "audio" event for unified processing
            # In real implementation, this would go through different flow
            text = update.message.text
            await self._audio_queue.put(f"TEXT:{text}".encode())

        # Register handlers
        self.app.add_handler(CommandHandler("start", start_command))
        self.app.add_handler(MessageHandler(filters.VOICE, voice_message))
        self.app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, text_message)
        )

    async def _convert_opus_to_pcm(self, opus_data: bytes) -> bytes:
        """Convert Opus audio to PCM for Gemini.

        Args:
            opus_data: OGG/Opus encoded audio

        Returns:
            Raw PCM audio bytes
        """
        # Use ffmpeg to convert
        process = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-i", "pipe:0",
            "-f", "s16le",
            "-ar", "16000",
            "-ac", "1",
            "pipe:1",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )

        stdout, _ = await process.communicate(opus_data)
        return stdout

    async def _convert_pcm_to_opus(self, pcm_data: bytes) -> bytes:
        """Convert PCM audio to Opus for Telegram.

        Args:
            pcm_data: Raw PCM audio bytes

        Returns:
            OGG/Opus encoded audio
        """
        process = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-f", "s16le",
            "-ar", "24000",
            "-ac", "1",
            "-i", "pipe:0",
            "-c:a", "libopus",
            "-f", "ogg",
            "pipe:1",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )

        stdout, _ = await process.communicate(pcm_data)
        return stdout

    async def start(self) -> None:
        """Start the Telegram bot."""
        self._running = True

        # Initialize and start polling
        await self.app.initialize()
        await self.app.start()
        await self.app.updater.start_polling()

        print("Telegram voice source ready")

        # Start response sender task
        asyncio.create_task(self._send_responses())

    async def stop(self) -> None:
        """Stop the Telegram bot."""
        self._running = False
        await self.app.updater.stop()
        await self.app.stop()
        await self.app.shutdown()

    async def _send_responses(self) -> None:
        """Background task to send audio responses."""
        while self._running:
            try:
                chat_id, audio_data = await asyncio.wait_for(
                    self._response_queue.get(),
                    timeout=1.0
                )

                # Convert PCM to Opus
                opus_data = await self._convert_pcm_to_opus(audio_data)

                # Send voice message
                await self.app.bot.send_voice(
                    chat_id=chat_id,
                    voice=io.BytesIO(opus_data)
                )
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                print(f"Error sending response: {e}")

    async def get_audio_chunks(self) -> AsyncIterator[bytes]:
        """Yield audio chunks from Telegram voice messages.

        Yields:
            Raw audio bytes (PCM) from voice messages
        """
        while self._running:
            try:
                chunk = await asyncio.wait_for(
                    self._audio_queue.get(),
                    timeout=1.0
                )
                yield chunk
            except asyncio.TimeoutError:
                continue

    async def play_audio(self, audio_data: bytes) -> None:
        """Send audio response to Telegram chat.

        Args:
            audio_data: Raw PCM audio bytes to send
        """
        if self._current_chat_id:
            await self._response_queue.put((self._current_chat_id, audio_data))
