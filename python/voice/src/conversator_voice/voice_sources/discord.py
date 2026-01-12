"""Voice input from Discord call - bot joins voice channel, streams to Gemini."""

import asyncio
from typing import AsyncIterator, Optional

import discord
from discord.ext import commands


class DiscordVoiceSource:
    """Voice source that captures audio from a Discord voice call.

    The bot joins a voice channel and streams the user's audio
    to Gemini Live for processing.
    """

    def __init__(self, bot_token: str, guild_id: Optional[int] = None):
        """Initialize Discord voice source.

        Args:
            bot_token: Discord bot token
            guild_id: Optional guild ID to auto-join
        """
        self.bot_token = bot_token
        self.guild_id = guild_id
        self._running = False
        self._audio_queue: asyncio.Queue[bytes] = asyncio.Queue()
        self._voice_client: Optional[discord.VoiceClient] = None

        # Set up Discord bot
        intents = discord.Intents.default()
        intents.message_content = True
        intents.voice_states = True

        self.bot = commands.Bot(command_prefix="!", intents=intents)
        self._setup_commands()

    def _setup_commands(self) -> None:
        """Set up bot commands."""

        @self.bot.event
        async def on_ready():
            print(f"Discord bot ready: {self.bot.user}")

        @self.bot.command(name="join")
        async def join_voice(ctx: commands.Context):
            """Join the user's voice channel."""
            if ctx.author.voice is None:
                await ctx.send("You need to be in a voice channel!")
                return

            channel = ctx.author.voice.channel
            self._voice_client = await channel.connect()

            # Set up audio sink to capture user's voice
            self._voice_client.start_recording(
                discord.sinks.WaveSink(),
                self._on_recording_finished,
                ctx.channel
            )

            await ctx.send(f"Joined {channel.name} - listening...")

        @self.bot.command(name="leave")
        async def leave_voice(ctx: commands.Context):
            """Leave the voice channel."""
            if self._voice_client:
                self._voice_client.stop_recording()
                await self._voice_client.disconnect()
                self._voice_client = None
                await ctx.send("Left voice channel")

    async def _on_recording_finished(
        self, sink: discord.sinks.WaveSink, channel: discord.TextChannel
    ):
        """Called when recording chunk is ready."""
        for user_id, audio in sink.audio_data.items():
            # Convert to raw PCM and queue for Gemini
            pcm_data = audio.file.read()
            await self._audio_queue.put(pcm_data)

    async def start(self) -> None:
        """Start the Discord bot."""
        self._running = True

        # Run bot in background task
        asyncio.create_task(self.bot.start(self.bot_token))

        # Wait for bot to be ready
        await self.bot.wait_until_ready()
        print("Discord voice source ready")

    async def stop(self) -> None:
        """Stop the Discord bot."""
        self._running = False
        if self._voice_client:
            await self._voice_client.disconnect()
        await self.bot.close()

    async def get_audio_chunks(self) -> AsyncIterator[bytes]:
        """Yield audio chunks from Discord voice.

        Yields:
            Raw audio bytes captured from Discord
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
        """Play audio in the Discord voice channel.

        Args:
            audio_data: Raw audio bytes to play
        """
        if not self._voice_client or not self._voice_client.is_connected():
            print("Not connected to voice channel")
            return

        # Create audio source from bytes
        audio_source = discord.PCMAudio(
            discord.FFmpegPCMAudio(
                audio_data,
                pipe=True,
                options="-f s16le -ar 24000 -ac 1"
            )
        )

        self._voice_client.play(audio_source)

        # Wait for playback to finish
        while self._voice_client.is_playing():
            await asyncio.sleep(0.1)
