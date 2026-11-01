"""
Voice download and management.
"""
import json
import urllib.request
import urllib.error
from pathlib import Path
from typing import List
import shutil


# Curated voice list
CURATED_VOICES = [
    {"name": "en_GB-alan-medium", "lang": "English (UK)", "quality": "medium"},
    {"name": "en_US-ryan-high", "lang": "English (US)", "quality": "high"},
    {"name": "en_US-lessac-medium", "lang": "English (US)", "quality": "medium"},
    {"name": "en_US-amy-low", "lang": "English (US)", "quality": "low"},
    {"name": "en_GB-northern_english_male-medium", "lang": "English (UK)", "quality": "medium"},
]


PIPER_VOICES_BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0"


def _voice_url_path(voice: str) -> str:
    """Map a voice name to its repo subdirectory.

    Piper voices live under <lang>/<locale>-<speaker>-<quality> layout, e.g.
    en/en_GB/alan/medium/en_GB-alan-medium.onnx
    """
    locale_part = voice.split("-")[0]  # en_GB
    lang_code = locale_part.split("_")[0]  # en
    parts = voice.split("-")
    if len(parts) >= 3:
        speaker, quality = parts[1], parts[2]
    else:
        return voice  # fallback to flat layout
    return f"{lang_code}/{locale_part}/{speaker}/{quality}/{voice}"


def download_voice(voice: str, voice_dir: str = ".tools/voices") -> bool:
    """Download voice files from HuggingFace."""
    voice_dir = Path(voice_dir)
    voice_dir.mkdir(parents=True, exist_ok=True)
    
    onnx_path = voice_dir / f"{voice}.onnx"
    json_path = voice_dir / f"{voice}.onnx.json"
    
    # Skip if already exists
    if onnx_path.exists() and json_path.exists():
        return True
    
    # Try direct HuggingFace URL first
    subdir = _voice_url_path(voice)
    onnx_url = f"{PIPER_VOICES_BASE}/{subdir}.onnx"
    json_url = f"{PIPER_VOICES_BASE}/{subdir}.onnx.json"
    
    try:
        _download_file(onnx_url, onnx_path)
        _download_file(json_url, json_path)
        return True
    except urllib.error.HTTPError:
        pass
    
    # Fallback to piper.download_voices
    return _download_via_piper(voice, voice_dir)


def _download_file(url: str, dest: Path):
    """Download file with atomic write."""
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    try:
        urllib.request.urlretrieve(url, tmp)
        tmp.rename(dest)
    except Exception:
        if tmp.exists():
            tmp.unlink()
        raise


def _download_via_piper(voice: str, voice_dir: Path) -> bool:
    """Fallback to python -m piper.download_voices."""
    try:
        import subprocess
        import sys
        result = subprocess.run(
            [sys.executable, "-m", "piper.download_voices", voice, "--data-dir", str(voice_dir)],
            capture_output=True, text=True, timeout=300
        )
        return result.returncode == 0
    except Exception:
        return False


def list_voices() -> List[dict]:
    """List available voices."""
    return CURATED_VOICES


def list_local_voices(voice_dir: str = ".tools/voices") -> List[str]:
    """List locally downloaded voices."""
    voice_dir = Path(voice_dir)
    if not voice_dir.exists():
        return []
    
    voices = []
    for onnx in voice_dir.glob("*.onnx"):
        if onnx.with_suffix(".onnx.json").exists():
            voices.append(onnx.stem)
    return sorted(voices)