"""Ambient audio controller for background music during work periods."""

import asyncio
import threading
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import sounddevice as sd

if TYPE_CHECKING:
    from .voice_sources.local import LocalVoiceSource


class AmbientAudioController:
    """Manages ambient background music during work periods.

    Plays gentle background music when work is in progress, with:
    - Smooth fade in when work starts
    - Smooth fade out when work completes
    - Volume ducking when Gemini is speaking
    """

    def __init__(
        self,
        music_path: str | Path | None = None,
        sample_rate: int = 24000,
        volume: float = 0.15,
        ducked_volume: float = 0.03,
        fade_duration: float = 2.0,
    ):
        """Initialize ambient audio controller.

        Args:
            music_path: Path to ambient music file (OGG, MP3, WAV)
            sample_rate: Output sample rate in Hz
            volume: Normal playback volume (0.0-1.0)
            ducked_volume: Volume when Gemini is speaking
            fade_duration: Duration of fade in/out in seconds
        """
        self.music_path = Path(music_path) if music_path else None
        self.sample_rate = sample_rate
        self.normal_volume = volume
        self.ducked_volume = ducked_volume
        self.fade_duration = fade_duration

        # Audio state
        self._music_data: np.ndarray | None = None
        self._playback_position = 0
        self._current_volume = 0.0
        self._target_volume = 0.0
        self._is_playing = False
        self._should_stop = False

        # Voice source for ducking coordination
        self._voice_source: "LocalVoiceSource | None" = None

        # Threading
        self._stream: sd.OutputStream | None = None
        self._lock = threading.Lock()
        self._fade_task: asyncio.Task | None = None

    def set_voice_source(self, voice_source: "LocalVoiceSource") -> None:
        """Set voice source for speech ducking coordination.

        Args:
            voice_source: LocalVoiceSource to monitor for speech playback
        """
        self._voice_source = voice_source

    def _load_music(self) -> bool:
        """Load music file on first use.

        Returns:
            True if music loaded successfully
        """
        if self._music_data is not None:
            return True

        if not self.music_path:
            # Try default locations (ogg, mp3, wav)
            for ext in ["ogg", "mp3", "wav"]:
                default_path = Path(f".conversator/audio/ambient_work.{ext}")
                if default_path.exists():
                    self.music_path = default_path
                    break
            else:
                print("[AmbientAudio] No music file found in .conversator/audio/")
                return False

        if not self.music_path.exists():
            print(f"[AmbientAudio] Music file not found: {self.music_path}")
            return False

        try:
            # Try soundfile first (good for wav, ogg)
            try:
                import soundfile as sf

                data, file_sr = sf.read(str(self.music_path), dtype="float32")
            except Exception:
                # Fall back to pydub for MP3 support
                from pydub import AudioSegment

                audio = AudioSegment.from_file(str(self.music_path))
                # Convert to mono
                if audio.channels > 1:
                    audio = audio.set_channels(1)
                # Get raw samples as float32
                samples = np.array(audio.get_array_of_samples())
                data = samples.astype(np.float32) / (2 ** (audio.sample_width * 8 - 1))
                file_sr = audio.frame_rate

            # Convert to mono if stereo (for soundfile path)
            if len(data.shape) > 1:
                data = np.mean(data, axis=1)

            # Resample if needed
            if file_sr != self.sample_rate:
                # Simple resampling - could use scipy.signal.resample for better quality
                ratio = self.sample_rate / file_sr
                new_length = int(len(data) * ratio)
                indices = np.linspace(0, len(data) - 1, new_length)
                data = np.interp(indices, np.arange(len(data)), data)

            self._music_data = data.astype(np.float32)
            print(
                f"[AmbientAudio] Loaded {self.music_path.name} ({len(self._music_data) / self.sample_rate:.1f}s)"
            )
            return True

        except ImportError as e:
            print(f"[AmbientAudio] Missing audio library: {e}")
            print("[AmbientAudio] Install with: pip install soundfile pydub")
            return False
        except Exception as e:
            print(f"[AmbientAudio] Failed to load music: {e}")
            return False

    def _audio_callback(self, outdata: np.ndarray, frames: int, time, status) -> None:
        """Sounddevice callback for audio output."""
        if status:
            print(f"[AmbientAudio] Status: {status}")

        with self._lock:
            if self._music_data is None or not self._is_playing:
                outdata.fill(0)
                return

            # Check for ducking
            effective_volume = self._current_volume
            if self._voice_source and self._voice_source._is_playing:
                effective_volume = min(effective_volume, self.ducked_volume)

            # Fill output buffer with looping music
            output = np.zeros(frames, dtype=np.float32)
            remaining = frames
            write_pos = 0

            while remaining > 0:
                available = len(self._music_data) - self._playback_position
                to_copy = min(remaining, available)

                output[write_pos : write_pos + to_copy] = self._music_data[
                    self._playback_position : self._playback_position + to_copy
                ]

                self._playback_position += to_copy
                write_pos += to_copy
                remaining -= to_copy

                # Loop
                if self._playback_position >= len(self._music_data):
                    self._playback_position = 0

            # Apply volume and write to output
            outdata[:, 0] = output * effective_volume

    async def start_work_music(self) -> None:
        """Start playing ambient music with fade in."""
        if not self._load_music():
            return

        with self._lock:
            if self._is_playing:
                # Already playing, just ensure target volume
                self._target_volume = self.normal_volume
                return

            self._is_playing = True
            self._should_stop = False
            self._target_volume = self.normal_volume
            self._current_volume = 0.0

        # Start audio stream if not running
        if self._stream is None:
            self._stream = sd.OutputStream(
                samplerate=self.sample_rate,
                channels=1,
                dtype=np.float32,
                callback=self._audio_callback,
                blocksize=1024,
            )
            self._stream.start()

        # Start fade in
        if self._fade_task:
            self._fade_task.cancel()
        self._fade_task = asyncio.create_task(self._fade_volume())

        print("[AmbientAudio] Work music starting...")

    async def stop_work_music(self) -> None:
        """Stop ambient music with fade out."""
        with self._lock:
            if not self._is_playing:
                return
            if self._should_stop:
                # Stop already in progress; avoid spamming fade tasks/logs.
                return
            self._target_volume = 0.0
            self._should_stop = True

        # Start fade out
        if self._fade_task:
            self._fade_task.cancel()
        self._fade_task = asyncio.create_task(self._fade_volume())

        print("[AmbientAudio] Work music stopping...")

    async def _fade_volume(self) -> None:
        """Gradually fade volume to target."""
        fade_step = 0.02  # 20ms steps
        volume_step = (self.normal_volume / self.fade_duration) * fade_step

        while True:
            with self._lock:
                if abs(self._current_volume - self._target_volume) < 0.001:
                    self._current_volume = self._target_volume

                    # Stop stream if faded out completely
                    if self._should_stop and self._current_volume == 0:
                        self._is_playing = False
                        if self._stream:
                            self._stream.stop()
                            self._stream.close()
                            self._stream = None
                        print("[AmbientAudio] Work music stopped")
                    break

                if self._current_volume < self._target_volume:
                    self._current_volume = min(
                        self._current_volume + volume_step, self._target_volume
                    )
                else:
                    self._current_volume = max(
                        self._current_volume - volume_step, self._target_volume
                    )

            await asyncio.sleep(fade_step)

    def stop(self) -> None:
        """Immediately stop and clean up."""
        with self._lock:
            self._is_playing = False
            if self._stream:
                self._stream.stop()
                self._stream.close()
                self._stream = None

    @property
    def is_playing(self) -> bool:
        """Check if music is currently playing."""
        return self._is_playing
