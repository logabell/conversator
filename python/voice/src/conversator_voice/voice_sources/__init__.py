"""Voice source implementations for different input methods."""

from typing import Protocol, AsyncIterator


class VoiceSource(Protocol):
    """Protocol for voice input sources."""

    async def start(self) -> None:
        """Initialize and start capturing audio."""
        ...

    async def stop(self) -> None:
        """Stop capturing audio and clean up."""
        ...

    async def get_audio_chunks(self) -> AsyncIterator[bytes]:
        """Yield audio chunks as they become available."""
        ...

    async def play_audio(self, audio_data: bytes) -> None:
        """Play audio output through this source."""
        ...


def create_voice_source(source_type: str, **kwargs) -> VoiceSource:
    """Factory to create voice source by type."""
    if source_type == "local":
        from .local import LocalVoiceSource
        return LocalVoiceSource(**kwargs)
    elif source_type == "discord":
        from .discord import DiscordVoiceSource
        return DiscordVoiceSource(**kwargs)
    elif source_type == "telegram":
        from .telegram import TelegramVoiceSource
        return TelegramVoiceSource(**kwargs)
    else:
        raise ValueError(f"Unknown voice source type: {source_type}")
