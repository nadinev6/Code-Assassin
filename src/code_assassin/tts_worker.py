"""
TTS worker for Piper voice synthesis.

Piper 1.8 buffers synthesis and flushes audio only when stdin reaches EOF,
so each utterance runs as a short-lived one-shot subprocess:
spawn piper, write text line, close stdin, read all raw PCM, return it.
"""
import json
import subprocess
import sys
from pathlib import Path
from typing import Optional


class TTSWorker:
    """One-shot Piper synthesis for a single utterance."""

    def __init__(self, voice_path: str, voice_dir: str = ".tools/voices"):
        self.voice_dir = Path(voice_dir)
        # voice_path may be a bare voice name (e.g. "en_GB-alan-medium") or a
        # full path. Resolve names against voice_dir and the .onnx extension.
        p = Path(voice_path)
        if p.suffix == ".onnx":
            self.voice_path = p
        else:
            self.voice_path = self.voice_dir / f"{voice_path}.onnx"
        self.sample_rate = 22050
        self.sample_width = 2  # int16
        self.sample_channels = 1  # mono
        self._ready = True

    def start(self):
        """Compatibility no-op: one-shot synthesis needs no persistent process."""
        self._ready = True

    def synthesize(self, text: str) -> bytes:
        """Synthesize text and return raw PCM bytes."""
        cmd = [
            sys.executable, "-m", "piper",
            "-m", str(self.voice_path),
            "--output_raw",
            "-f", "-",
        ]
        result = subprocess.run(
            cmd,
            input=(text + "\n").encode("utf-8"),
            capture_output=True,
            timeout=120,
        )
        return result.stdout

    def send(self, text: str, request_id: str):
        """Deprecated: replaced by synthesize(). Kept for API compatibility."""
        raise NotImplementedError("Use synthesize() instead")

    def shutdown(self):
        """Compatibility no-op."""
        pass

    def read_pcm(self, timeout: float = 0.1) -> bytes:
        """Deprecated: replaced by synthesize(). Kept for API compatibility."""
        return b""

    def is_ready(self) -> bool:
        """Check if worker is ready."""
        return self._ready