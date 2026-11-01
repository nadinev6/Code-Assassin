"""
Tests for CLI module.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock
from code_assassin.cli import AssassinApp


class _FakeSession:
    """In-memory session that never touches .code-assassin/ on disk."""

    def __init__(self, task: str = "default", memory_dir=None):
        self.task = task
        self.turns: list[dict] = []

    def load(self):
        return self

    def add_turn(self, role: str, content: str):
        self.turns.append({"role": role, "content": content})

    def get_prompt_turns(self, max_turns: int = 6):
        return self.turns[-max_turns:]

    def clear(self):
        self.turns = []

    def delete(self):
        self.turns = []


@pytest.mark.asyncio
async def test_ask_one_shot(monkeypatch):
    """Test one-shot ask command without writing to the real session file."""
    monkeypatch.setattr("code_assassin.cli.Session", _FakeSession)
    app = AssassinApp()
    app.ollama = AsyncMock()
    app.ollama.chat = AsyncMock(return_value=["Hello", " world"])
    app.context = MagicMock()
    app.context.build_prompt = MagicMock(return_value=[])

    result = await app.one_shot("test prompt")
    assert "Hello world" in result


@pytest.mark.asyncio
async def test_start_disabled_voice(monkeypatch):
    """Test start with no-voice flag without writing to the real session file."""
    monkeypatch.setattr("code_assassin.cli.Session", _FakeSession)
    app = AssassinApp()
    app.tts = MagicMock()

    await app.start(no_voice=True)
    assert not app.tts.enabled
