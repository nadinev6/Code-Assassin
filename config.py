from typing import Optional
from pathlib import Path
import os
from dataclasses import dataclass, field
import tomllib
from typer import Option

@dataclass
class Config:
    model: str = "qwen2.5-coder:3b"
    ollama_url: str = "http://127.0.0.1:11434"
    num_ctx: int = 8192
    num_predict: int = 1024
    temperature: float = 0.2
    voice: str = "en_GB-alan-medium"
    voice_dir: str = ".tools/voices"
    speak: bool = True
    edits: bool = True
    agent: bool = True
    run: bool = True
    max_steps: int = 30
    tool_result_max: int = 8000
    run_timeout: int = 60
    root: Path = Path(".")

    @classmethod
    def load(cls, config_path: str = "assassin.toml") -> "Config":
        defaults = cls()
        if not os.path.exists(config_path):
            return defaults
        
        with open(config_path, "rb") as f:
            config_data = tomllib.load(f)
        
        # Handle [general] section
        general = config_data.get("general", {})
        for key, value in general.items():
            if hasattr(defaults, key):
                setattr(defaults, key, value)
        
        # Handle [paths] section
        paths = config_data.get("paths", {})
        for key, value in paths.items():
            if hasattr(defaults, key):
                setattr(defaults, key, value)
        
        return defaults

    @classmethod
    def merge(cls, cli_config: Optional["Config"] = None) -> "Config":
        defaults = cls.load()
        if cli_config:
            for key, value in vars(cli_config).items():
                if value is not None:
                    setattr(defaults, key, value)
        return defaults