"""
TTS manager: manages worker, queue, and audio output.
"""
import re
import sys
import threading
import queue
import time
from pathlib import Path
from typing import Optional
from .tts_worker import TTSWorker


class TTS:
    """Manages TTS worker and audio output."""

    def __init__(self, voice: str = "en_GB-alan-medium", voice_dir: str = ".tools/voices"):
        self.voice = voice
        self.voice_dir = voice_dir
        self.enabled = True
        self.worker: Optional[TTSWorker] = None
        self._speech_queue: queue.Queue = queue.Queue()
        self._audio_thread: Optional[threading.Thread] = None
        self._worker_thread: Optional[threading.Thread] = None
        self._running = False
        self._first_pcm_latency: Optional[float] = None

    def enable(self):
        """Enable TTS output."""
        self.enabled = True

    def disable(self):
        """Disable TTS output."""
        self.enabled = False

    def start(self):
        """Start TTS pipeline."""
        if not self.enabled:
            return
        self._running = True
        self.worker = TTSWorker(self.voice, self.voice_dir)
        try:
            self.worker.start()
        except Exception:
            self.worker = None
            return
        # Start worker thread
        self._worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker_thread.start()

    def stop(self, wait: bool = True):
        """Stop TTS pipeline. If wait=True, blocks until queued speech is played."""
        self._running = False
        # Wait for the worker thread to drain any queued speech
        if wait and self._worker_thread and self._worker_thread.is_alive():
            # Give queued items time to synthesize + play; cap to avoid hang
            self._worker_thread.join(timeout=30)
        if self.worker:
            self.worker.shutdown()

    def speak(self, text: str):
        """Queue text for speech."""
        if not self.enabled or not text:
            return
        # Clean text for TTS
        clean = self._clean_text(text)
        if clean:
            self._speech_queue.put(clean)

    def _clean_text(self, text: str) -> str:
        """Clean text for TTS: strip markdown, URLs, code."""
        # Remove code blocks
        text = re.sub(r'```.*?```', '', text, flags=re.DOTALL)
        # Remove inline code
        text = re.sub(r'`[^`]+`', '', text)
        # Remove markdown links
        text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
        # Remove URLs
        text = re.sub(r'https?://\S+', '', text)
        # Remove markdown formatting
        text = re.sub(r'[*_~#>]', '', text)
        # Collapse whitespace
        text = re.sub(r'\s+', ' ', text).strip()
        # Cap at 60 words
        words = text.split()
        if len(words) > 60:
            text = ' '.join(words[:60])
        return text

    def _worker_loop(self):
        """Worker loop for TTS pipeline."""
        while True:
            try:
                text = self._speech_queue.get(timeout=0.1)
            except queue.Empty:
                if not self._running:
                    break
                continue

            # One-shot synthesis: spawn piper, close stdin, read all PCM
            try:
                if not self.worker:
                    self.worker = TTSWorker(self.voice, self.voice_dir)
                    self.worker.start()
                pcm = self.worker.synthesize(text)
                if pcm:
                    self._play_pcm(pcm)
                else:
                    print(f"[tts] empty synthesis for voice {self.worker.voice_path}", file=sys.stderr)
            except Exception as e:
                # Piper/voice unavailable - report instead of failing silently
                try:
                    print(f"[tts] voice unavailable: {e}", file=sys.stderr)
                except Exception:
                    pass

    def _play_pcm(self, pcm_data: bytes):
        """Play PCM audio through sounddevice."""
        try:
            import sounddevice as sd
            import numpy as np
            if not pcm_data:
                return
            audio = np.frombuffer(pcm_data, dtype=np.int16)
            sd.play(audio, samplerate=self.worker.sample_rate)
            sd.wait()
        except Exception:
            # Audio device not available - silent fallback
            pass

    def check_health(self) -> bool:
        """Check if TTS is healthy."""
        try:
            import sounddevice as sd
            return True
        except Exception:
            return False

    def check_voice(self) -> bool:
        """Check if voice files exist."""
        voice_path = Path(self.voice_dir) / f"{self.voice}.onnx"
        return voice_path.exists()