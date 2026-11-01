"""
Session storage for per-project memory.
"""
import json
import os
import shutil
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional


SESSION_VERSION = 1
MAX_STORED_TURNS = 50
MAX_PROMPT_TURNS = 6


class Session:
    """Per-project session memory."""

    MAX_STORED_TURNS = MAX_STORED_TURNS
    MAX_PROMPT_TURNS = MAX_PROMPT_TURNS

    def __init__(self, task: str = "default", memory_dir: str = ".code-assassin"):
        self.task = self._sanitize_task(task)
        self.memory_dir = Path(memory_dir)
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.memory_dir / f"memory_{self.task}.json"
        
        self.version = SESSION_VERSION
        self.created_at = datetime.now(timezone.utc).isoformat()
        self.updated_at = self.created_at
        self.model = "qwen2.5-coder:3b"
        self.turns: list[dict] = []

    def _sanitize_task(self, task: str) -> str:
        """Sanitize task name for filename."""
        import re
        sanitized = re.sub(r'[^a-zA-Z0-9_-]', '_', task)
        return sanitized or "default"

    def load(self) -> "Session":
        """Load session from disk. Returns self."""
        if not self.path.exists():
            return self
        
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            self.version = data.get("version", SESSION_VERSION)
            self.created_at = data.get("created_at", self.created_at)
            self.updated_at = data.get("updated_at", self.updated_at)
            self.model = data.get("model", self.model)
            self.turns = data.get("turns", [])
            
            # Cap stored turns
            if len(self.turns) > MAX_STORED_TURNS:
                self.turns = self.turns[-MAX_STORED_TURNS:]
        except (json.JSONDecodeError, KeyError):
            # Corrupt file - rename and start fresh
            backup = self.path.with_suffix(".json.bak")
            try:
                shutil.move(str(self.path), str(backup))
            except Exception:
                pass
            self.turns = []
        
        return self

    def save(self):
        """Atomically save session to disk."""
        self.updated_at = datetime.now(timezone.utc).isoformat()
        data = {
            "version": self.version,
            "task": self.task,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "model": self.model,
            "turns": self.turns,
        }
        
        # Atomic write: temp file + rename
        tmp = self.path.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, self.path)

    def add_turn(self, role: str, content: str):
        """Add a conversation turn."""
        self.turns.append({
            "role": role,
            "content": content,
            "ts": datetime.now(timezone.utc).isoformat(),
        })
        if len(self.turns) > MAX_STORED_TURNS:
            self.turns = self.turns[-MAX_STORED_TURNS:]
        self.save()

    def get_prompt_turns(self, max_turns: int = MAX_PROMPT_TURNS) -> list[dict]:
        """Get the latest turns for the prompt."""
        return self.turns[-max_turns:] if self.turns else []

    def clear(self):
        """Clear all turns."""
        self.turns = []
        self.save()

    def delete(self):
        """Delete the session file."""
        if self.path.exists():
            self.path.unlink()
        self.turns = []