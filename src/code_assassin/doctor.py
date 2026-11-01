"""
System health checks and diagnostics.
"""
import subprocess
import shutil
from pathlib import Path
from typing import List, Tuple
from .config import Config


class Doctor:
    """Environment and configuration health checks."""

    def __init__(self, config: Config):
        self.config = config
        self.checks: List[Tuple[str, bool, str]] = []

    def run_all(self) -> int:
        """Run all checks and return exit code."""
        self.checks = []
        
        self._check_ollama()
        self._check_model()
        self._check_piper()
        self._check_voice()
        self._check_audio()
        self._check_git()
        self._check_write_access()
        self._check_vram()
        
# Print results
        for name, passed, message in self.checks:
            status = "OK" if passed else "FAIL"
            print(f"  {status}: {name}: {message}")
        
        # Return error code if any critical check failed
        critical_failed = any(not passed for name, passed, _ in self.checks 
                             if name in ["Ollama reachable", "Model present", "Voice files", "Write access"])
        return 1 if critical_failed else 0

    def _check_ollama(self):
        """Check Ollama server reachability."""
        try:
            import httpx
            import asyncio
            async def check():
                async with httpx.AsyncClient(timeout=5.0) as client:
                    r = await client.get(f"{self.config.ollama_url}/api/tags")
                    return r.status_code == 200
            reachable = asyncio.get_event_loop().run_until_complete(check())
            self.checks.append(("Ollama reachable", reachable, 
                               f"Ollama at {self.config.ollama_url}" if reachable else "Ollama not reachable"))
        except Exception as e:
            self.checks.append(("Ollama reachable", False, f"Error: {e}"))

    def _check_model(self):
        """Check if model is available."""
        try:
            import httpx
            import asyncio
            async def check():
                async with httpx.AsyncClient(timeout=5.0) as client:
                    r = await client.get(f"{self.config.ollama_url}/api/tags")
                    if r.status_code == 200:
                        models = [m["name"] for m in r.json().get("models", [])]
                        return self.config.model in models
                    return False
            present = asyncio.get_event_loop().run_until_complete(check())
            self.checks.append(("Model present", present,
                               f"Model {self.config.model} available" if present else f"Model {self.config.model} not found. Run: ollama pull {self.config.model}"))
        except Exception as e:
            self.checks.append(("Model present", False, f"Error: {e}"))

    def _check_piper(self):
        """Check Piper TTS import."""
        try:
            import piper
            self.checks.append(("Piper import", True, "piper-tts available"))
        except ImportError:
            self.checks.append(("Piper import", False, "piper-tts not installed. Run: uv sync --extra voice"))

    def _check_voice(self):
        """Check voice files exist."""
        voice_path = Path(self.config.voice_dir) / f"{self.config.voice}.onnx"
        exists = voice_path.exists()
        self.checks.append(("Voice files", exists,
                           f"Voice {self.config.voice} found" if exists else f"Voice {self.config.voice} not found. Run: assassin voices download {self.config.voice}"))

    def _check_audio(self):
        """Check audio output device."""
        try:
            import sounddevice as sd
            devices = sd.query_devices(kind='output')
            has_device = len(devices) > 0
            self.checks.append(("Audio device", has_device,
                               "Output device available" if has_device else "No output audio device found"))
        except Exception as e:
            self.checks.append(("Audio device", False, f"Error: {e}"))

    def _check_git(self):
        """Check git availability."""
        git_path = shutil.which("git")
        self.checks.append(("Git", git_path is not None,
                           "git available" if git_path else "git not in PATH"))

    def _check_write_access(self):
        """Check project root write access."""
        try:
            test_file = Path(self.config.root) / ".code_assassin_write_test"
            test_file.write_text("test")
            test_file.unlink()
            self.checks.append(("Write access", True, "Project root writable"))
        except Exception as e:
            self.checks.append(("Write access", False, f"Cannot write to project root: {e}"))

    def _check_vram(self):
        """Check VRAM if nvidia-smi available."""
        nvidia_smi = shutil.which("nvidia-smi")
        if not nvidia_smi:
            self.checks.append(("VRAM", True, "nvidia-smi not available (skipping)"))
            return
        
        try:
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=memory.total,memory.used", "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                lines = result.stdout.strip().split("\n")
                for i, line in enumerate(lines):
                    total, used = map(int, line.split(","))
                    free = total - used
                    self.checks.append((f"GPU {i} VRAM", free >= 4096,
                                       f"Total: {total}MB, Used: {used}MB, Free: {free}MB"))
            else:
                self.checks.append(("VRAM", True, "nvidia-smi failed (skipping)"))
        except Exception as e:
            self.checks.append(("VRAM", True, f"Error: {e}"))