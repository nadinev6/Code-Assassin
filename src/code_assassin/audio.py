"""
Audio output via sounddevice.
"""
from typing import Optional


def play_pcm(pcm_data: bytes, sample_rate: int, channels: int = 1, dtype: str = "int16"):
    """Play raw PCM audio through sounddevice."""
    try:
        import sounddevice as sd
        import numpy as np
        
        # Convert bytes to numpy array
        audio = np.frombuffer(pcm_data, dtype=np.int16)
        
        # Play audio
        sd.play(audio, samplerate=sample_rate)
        sd.wait()
    except Exception:
        # Silent fallback if audio device not available
        pass


def list_devices() -> list:
    """List available audio output devices."""
    try:
        import sounddevice as sd
        devices = sd.query_devices()
        return [d for d in devices if d.get('max_output_channels', 0) > 0]
    except Exception:
        return []


def get_default_device() -> Optional[dict]:
    """Get default audio output device."""
    try:
        import sounddevice as sd
        return sd.query_devices(kind='output')
    except Exception:
        return None