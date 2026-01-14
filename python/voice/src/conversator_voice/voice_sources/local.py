"""Local microphone via sounddevice (cross-platform audio).

Uses client-side echo suppression: skips sending audio to Gemini during
playback to prevent feedback loops, while still allowing user interruption.
"""

import asyncio
import queue
import threading
import time
from typing import AsyncIterator

import numpy as np
import sounddevice as sd


class LocalVoiceSource:
    """Voice source using local microphone via sounddevice.

    Captures audio from the default input device and plays audio
    to the default output device using non-blocking callbacks.

    Key design decisions:
    - Audio input is suppressed during playback (echo suppression)
    - Short cooldown after playback to catch residual echo
    - User can still interrupt by speaking loudly (detected via RMS threshold)
    - Output uses callback-based streaming for low-latency playback
    """

    # RMS threshold for detecting user speech during playback (for interruption)
    # Must be higher than max speaker echo (observed ~8700 RMS)
    INTERRUPT_THRESHOLD = 10000

    # Cooldown period after playback stops (seconds)
    # Longer cooldown helps prevent picking up echo tail
    POST_PLAYBACK_COOLDOWN = 0.5

    # Minimum playback duration before allowing interrupts (seconds)
    # Prevents false interrupts from initial echo burst
    MIN_PLAYBACK_BEFORE_INTERRUPT = 0.5

    # Echo window: time after receiving audio chunk when echo is expected (ms)
    # Echo arrives immediately; real interrupts come after a brief moment
    ECHO_WINDOW_MS = 200

    def __init__(
        self,
        input_sample_rate: int = 16000,
        output_sample_rate: int = 24000,
        chunk_duration_ms: int = 100
    ):
        """Initialize local voice source.

        Args:
            input_sample_rate: Input audio sample rate (Hz) - Gemini expects 16kHz
            output_sample_rate: Output audio sample rate (Hz) - Gemini sends 24kHz
            chunk_duration_ms: Duration of each audio chunk in milliseconds
        """
        self.input_sample_rate = input_sample_rate
        self.output_sample_rate = output_sample_rate
        self.chunk_duration_ms = chunk_duration_ms
        self.chunk_size = int(input_sample_rate * chunk_duration_ms / 1000)

        self._input_queue: queue.Queue[bytes] = queue.Queue()
        self._output_queue: queue.Queue[bytes] = queue.Queue()
        self._running = False
        self._input_stream = None
        self._output_stream = None

        # Output buffer for non-blocking playback callback
        self._output_buffer: bytes = b""
        self._output_lock = threading.Lock()

        # Track if audio is being played (for echo suppression and ambient ducking)
        self._is_playing = False
        self._playback_started_time: float = 0.0  # When current playback session started
        self._playback_ended_time: float = 0.0  # When playback last stopped
        self._last_audio_received_time: float = 0.0  # When we last received audio to play
        self._was_interrupted: bool = False  # True if playback was interrupted by user

    async def start(self) -> None:
        """Initialize and start capturing audio."""
        self._running = True

        def input_callback(indata, frames, time_info, status):
            """Capture audio with echo suppression during playback."""
            if status:
                print(f"Audio input status: {status}")
            if not self._running:
                return

            # Convert float32 to int16 PCM
            audio_int16 = (indata[:, 0] * 32767).astype(np.int16)
            audio_bytes = audio_int16.tobytes()

            # Time-gated echo suppression with interrupt window
            # Echo arrives immediately after audio is played; real interrupts come later
            current_time = time.time()

            # If user interrupted, skip cooldown - they're actively speaking
            # Otherwise, apply cooldown to catch echo tail after natural playback end
            if self._was_interrupted:
                in_cooldown = False
            else:
                in_cooldown = (current_time - self._playback_ended_time) < self.POST_PLAYBACK_COOLDOWN

            if self._is_playing or in_cooldown:
                # Check if we're past the echo window (when echo is expected)
                time_since_audio_ms = (current_time - self._last_audio_received_time) * 1000

                if time_since_audio_ms < self.ECHO_WINDOW_MS:
                    # In echo window - suppress everything (echo arrives immediately)
                    return

                # Also check minimum playback duration before allowing interrupts
                # This prevents false interrupts during initial echo burst
                playback_duration = current_time - self._playback_started_time
                if playback_duration < self.MIN_PLAYBACK_BEFORE_INTERRUPT:
                    return

                # Past echo window AND minimum playback - allow loud interrupts
                rms = np.sqrt(np.mean(audio_int16.astype(np.float32)**2))
                if rms > self.INTERRUPT_THRESHOLD:
                    # User is trying to interrupt - send audio
                    self._input_queue.put(audio_bytes)
                # Otherwise, suppress (likely still echo or background noise)
                return

            # Not playing - send audio normally
            self._input_queue.put(audio_bytes)

        def output_callback(outdata, frames, time_info, status):
            """Non-blocking callback to pull audio for playback."""
            if status:
                print(f"Audio output status: {status}")

            bytes_needed = frames * 2  # 16-bit = 2 bytes per sample

            with self._output_lock:
                was_playing = self._is_playing

                if len(self._output_buffer) >= bytes_needed:
                    # Have enough data
                    data = self._output_buffer[:bytes_needed]
                    self._output_buffer = self._output_buffer[bytes_needed:]
                    self._is_playing = True
                elif len(self._output_buffer) > 0:
                    # Have some data, pad with silence
                    data = self._output_buffer + b'\x00' * (bytes_needed - len(self._output_buffer))
                    self._output_buffer = b""
                    self._is_playing = True
                else:
                    # No data - output silence
                    data = b'\x00' * bytes_needed
                    self._is_playing = False
                    # Track when playback ended for cooldown
                    if was_playing:
                        self._playback_ended_time = time.time()

            # Convert to float32 for sounddevice
            audio_array = np.frombuffer(data, dtype=np.int16)
            outdata[:, 0] = audio_array.astype(np.float32) / 32767.0

        # Start input stream
        self._input_stream = sd.InputStream(
            samplerate=self.input_sample_rate,
            channels=1,
            dtype=np.float32,
            blocksize=self.chunk_size,
            callback=input_callback
        )
        self._input_stream.start()

        # Start output stream with callback (non-blocking)
        # Use smaller blocksize for lower latency
        output_blocksize = int(self.output_sample_rate * 0.025)  # 25ms blocks
        self._output_stream = sd.OutputStream(
            samplerate=self.output_sample_rate,
            channels=1,
            dtype=np.float32,
            blocksize=output_blocksize,
            callback=output_callback
        )
        self._output_stream.start()

        print(f"Audio started (in: {self.input_sample_rate}Hz, out: {self.output_sample_rate}Hz)")

    async def stop(self) -> None:
        """Stop capturing audio and clean up."""
        self._running = False
        if self._input_stream:
            self._input_stream.stop()
            self._input_stream.close()
            self._input_stream = None
        if self._output_stream:
            self._output_stream.stop()
            self._output_stream.close()
            self._output_stream = None

    def stop_playback(self) -> None:
        """Stop playback immediately (called on user interrupt).

        Clears the output buffer so playback stops at next callback.
        When interrupted, we skip cooldown because the user is actively speaking.
        """
        with self._output_lock:
            self._output_buffer = b""
            self._is_playing = False
            self._was_interrupted = True  # Skip cooldown - user is speaking
            self._playback_ended_time = time.time()  # Update timer for consistency

    async def get_audio_chunks(self) -> AsyncIterator[bytes]:
        """Yield audio chunks as they become available.

        Yields:
            Raw audio bytes in 16-bit PCM format
        """
        while self._running:
            try:
                # Non-blocking get with timeout
                chunk = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: self._input_queue.get(timeout=0.1)
                )
                yield chunk
            except queue.Empty:
                await asyncio.sleep(0.01)  # Yield to event loop
                continue
            except Exception as e:
                if self._running:
                    print(f"Audio capture error: {e}")
                break

    def flush_input_queue(self) -> None:
        """Clear any pending input audio.

        Called when starting playback to prevent queued audio from
        being sent to Gemini and causing false interruptions.
        """
        try:
            while True:
                self._input_queue.get_nowait()
        except queue.Empty:
            pass

    async def play_audio(self, audio_data: bytes) -> None:
        """Queue audio for playback.

        Audio is added to the output buffer and played by the callback.
        This is non-blocking - returns immediately.

        Args:
            audio_data: Raw audio bytes (16-bit PCM at output_sample_rate)
        """
        if audio_data:
            with self._output_lock:
                was_playing = self._is_playing
                self._output_buffer += audio_data
                # Set playing flag immediately to enable echo suppression
                # Don't wait for output callback - we need to suppress input NOW
                self._is_playing = True
                # Track when we received audio for echo window calculation
                self._last_audio_received_time = time.time()
                # Reset interrupted flag - new playback starting
                self._was_interrupted = False

            # When playback first starts, track start time and flush queue
            if not was_playing:
                self._playback_started_time = time.time()
                self.flush_input_queue()

    def is_playback_complete(self) -> bool:
        """Check if all queued audio has been played."""
        with self._output_lock:
            return not self._is_playing and len(self._output_buffer) == 0

    async def wait_for_playback_complete(self, timeout: float = 5.0) -> bool:
        """Wait for playback to complete.

        Args:
            timeout: Maximum time to wait in seconds

        Returns:
            True if playback completed, False if timeout
        """
        start = time.time()
        while time.time() - start < timeout:
            if self.is_playback_complete():
                return True
            await asyncio.sleep(0.05)  # Check every 50ms
        return False
