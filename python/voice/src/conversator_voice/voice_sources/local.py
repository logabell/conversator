"""Local microphone via sounddevice (cross-platform audio)."""

import asyncio
import queue
import threading
from typing import AsyncIterator

import numpy as np
import sounddevice as sd


class LocalVoiceSource:
    """Voice source using local microphone via sounddevice.

    Captures audio from the default input device and plays audio
    to the default output device.
    """

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
        self._playback_thread = None
        self._is_playing = False  # Track playback state
        self._pending_input: list[bytes] = []  # Buffer input during playback

    async def start(self) -> None:
        """Initialize and start capturing audio."""
        self._running = True

        def input_callback(indata, frames, time, status):
            if status:
                print(f"Audio input status: {status}")
            if self._running:
                # Convert float32 to int16 PCM
                audio_int16 = (indata[:, 0] * 32767).astype(np.int16)
                audio_bytes = audio_int16.tobytes()

                if self._is_playing:
                    # Buffer audio during playback (will be sent after)
                    self._pending_input.append(audio_bytes)
                else:
                    # Send any buffered audio first
                    while self._pending_input:
                        self._input_queue.put(self._pending_input.pop(0))
                    self._input_queue.put(audio_bytes)

        # Start input stream
        self._input_stream = sd.InputStream(
            samplerate=self.input_sample_rate,
            channels=1,
            dtype=np.float32,
            blocksize=self.chunk_size,
            callback=input_callback
        )
        self._input_stream.start()

        # Start playback thread that processes the output queue
        self._playback_thread = threading.Thread(target=self._playback_worker, daemon=True)
        self._playback_thread.start()

        print(f"Audio started (in: {self.input_sample_rate}Hz, out: {self.output_sample_rate}Hz)")

    def _playback_worker(self) -> None:
        """Background thread that plays audio from the output queue."""
        audio_buffer = []

        while self._running:
            try:
                # Collect audio chunks
                chunk = self._output_queue.get(timeout=0.05)
                audio_buffer.append(chunk)

                # Drain the queue to collect all pending chunks
                while not self._output_queue.empty():
                    try:
                        audio_buffer.append(self._output_queue.get_nowait())
                    except queue.Empty:
                        break

                # Combine and play all collected audio
                if audio_buffer:
                    combined = b"".join(audio_buffer)
                    audio_buffer.clear()

                    # Convert to numpy and play
                    audio_array = np.frombuffer(combined, dtype=np.int16)
                    audio_float = audio_array.astype(np.float32) / 32767.0

                    # Mark as playing (audio captured during this time will be discarded)
                    self._is_playing = True
                    print(f"[Playback starting... {len(audio_float)} samples]")
                    sd.play(audio_float, self.output_sample_rate)
                    sd.wait()
                    self._is_playing = False
                    # Discard buffered audio (contains echo of Gemini's voice)
                    # TODO: Implement acoustic echo cancellation (AEC) to preserve
                    # user speech during playback while filtering out the AI's voice
                    discarded = len(self._pending_input)
                    self._pending_input.clear()
                    print(f"[Playback finished - discarded {discarded} echo chunks, SPEAK NOW]")

            except queue.Empty:
                # No audio to play - make sure we're not blocking input
                if self._is_playing:
                    self._is_playing = False
                    print("[Playback idle - input resumed]")
                continue
            except Exception as e:
                self._is_playing = False
                if self._running:
                    print(f"Playback error: {e}")

    async def stop(self) -> None:
        """Stop capturing audio and clean up."""
        self._running = False
        if self._input_stream:
            self._input_stream.stop()
            self._input_stream.close()
            self._input_stream = None
        sd.stop()

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
                await asyncio.sleep(0.01)  # Yield to event loop to prevent starvation
                continue
            except Exception as e:
                if self._running:
                    print(f"Audio capture error: {e}")
                break

    async def play_audio(self, audio_data: bytes) -> None:
        """Queue audio for playback.

        Args:
            audio_data: Raw audio bytes (16-bit PCM at output_sample_rate)
        """
        if audio_data:
            self._output_queue.put(audio_data)
