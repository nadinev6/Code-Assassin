"""
Context management for file injection and token budgeting.
"""
import asyncio
import json
import re
import subprocess
from pathlib import Path
from typing import List, Optional


class ContextManager:
    """Manage context for Ollama prompts including @file, --file, --diff."""

    def __init__(self, config):
        self.config = config
        self.project_root = Path.cwd()
        self.system_prompt = self._load_system_prompt()
        self.turns: List[dict] = []
        self.file_contexts: List[str] = []
        self.diff_context: str = ""

    def _load_system_prompt(self) -> str:
        """Load system prompt from file."""
        prompt_path = self.project_root / "prompts" / "system.md"
        if prompt_path.exists():
            with open(prompt_path, "r", encoding="utf-8") as f:
                return f.read()
        return ""

    def set_project_root(self, path: Path):
        """Set the project root directory."""
        self.project_root = path

    def add_file_context(self, file_path: Path):
        """Add file content as context using @file syntax."""
        try:
            sanitized = self.sanitize_file_path(str(file_path))
            content = sanitized.read_text(encoding="utf-8")
            self.file_contexts.append(f"@{sanitized.name}:\n{content}")
        except Exception:
            pass

    def add_diff_context(self, staged: bool = False):
        """Add git diff as context."""
        try:
            cmd = ["git", "diff", "--staged"] if staged else ["git", "diff"]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=self.project_root,
            )
            self.diff_context = result.stdout
        except Exception:
            self.diff_context = ""

    def build_prompt(self, user_input: str, session) -> List[dict]:
        """Build the Ollama prompt with context."""
        messages = []

        # Add system prompt
        messages.append({"role": "system", "content": self.system_prompt})

        # Inject context (files / diff)
        context_parts = []
        for fc in self.file_contexts:
            context_parts.append(fc)
        if self.diff_context:
            context_parts.append(f"Git diff:\n{self.diff_context}")
        context_str = "\n\n".join(context_parts)
        if context_str:
            messages.append({"role": "user", "content": f"Context:\n{context_str}\n\n---\n\n"})

        # Add recent conversation turns
        prompt_turns = session.get_prompt_turns()
        for turn in prompt_turns:
            messages.append({"role": turn["role"], "content": turn["content"]})

        # The caller records the current request in the session before building
        # the prompt, so it is already in `prompt_turns`. Only append it when it
        # is genuinely missing; otherwise the user turn is duplicated and small
        # models start echoing themselves.
        if not any(t.get("content") == user_input for t in prompt_turns):
            messages.append({"role": "user", "content": user_input})

        # Trim to stay within context budget, leaving room for generation
        try:
            prompt_budget = max(1, int(self.config.num_ctx) - int(self.config.num_predict))
        except (TypeError, ValueError):
            prompt_budget = 8192
        messages = self.trim_to_budget(messages, prompt_budget)

        return messages

    def estimate_tokens(self, text: str) -> int:
        """Estimate token count using conservative approximation."""
        return int(len(text) / 3.5) + 1

    def trim_to_budget(self, messages: List[dict], max_tokens: int) -> List[dict]:
        """Trim messages to stay within the token budget.

        Keeps the system prompt and the *newest* messages. The current request
        is always the last message, so older turns (including large tool
        results) are dropped first; a long tool result can never silently
        remove the user's current prompt.
        """
        if not messages:
            return messages

        system = messages[0]
        system_tokens = self.estimate_tokens(system["content"])

        # If the system prompt alone is over budget, truncate it rather than
        # dropping the user's request.
        if system_tokens >= max_tokens:
            keep_chars = max(0, int(max_tokens * 3.5) - 32)
            return [{"role": system["role"], "content": system["content"][:keep_chars]}]

        budget = max_tokens - system_tokens
        kept: List[dict] = []
        total = 0

        # Walk backwards from the newest message so the current request wins.
        for m in reversed(messages[1:]):
            t = self.estimate_tokens(m["content"])
            if total + t > budget:
                if not kept:
                    # The newest message alone is too large: truncate it so the
                    # request is never silently dropped.
                    keep_chars = max(0, int(budget * 3.5) - 32)
                    kept.append({"role": m["role"], "content": m["content"][:keep_chars]})
                break
            kept.append(m)
            total += t

        kept.reverse()
        return [system] + kept

    def sanitize_file_path(self, path: str) -> Path:
        """Sanitize and validate file path."""
        file_path = Path(path)
        # Resolve against project root
        file_path = (self.project_root / file_path).resolve()

        # Ensure it's within project root
        try:
            file_path.relative_to(self.project_root)
        except ValueError:
            raise ValueError(f"Path escapes project root: {path}")

        return file_path