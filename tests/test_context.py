"""
Tests for the context module.
"""
import pytest
from code_assassin.context import ContextManager
from unittest.mock import MagicMock


def test_context_token_estimate():
    """Test token estimation."""
    config = MagicMock()
    config.root = "."
    context = ContextManager(config)
    
    text = "Hello world this is a test"
    tokens = context.estimate_tokens(text)
    assert tokens == int(len(text) / 3.5) + 1


def test_context_empty_input():
    """Test context with empty input."""
    config = MagicMock()
    config.root = "."
    context = ContextManager(config)
    
    tokens = context.estimate_tokens("")
    assert tokens == 1  # ceil(0 / 3.5) + 1 = 1


def test_context_long_text():
    """Test context with long text."""
    config = MagicMock()
    config.root = "."
    context = ContextManager(config)
    
    text = "A" * 1000
    tokens = context.estimate_tokens(text)
    assert tokens > 100


def test_trim_keeps_current_user_prompt():
    """A large tool result must not drop the newest user prompt."""
    config = MagicMock()
    config.root = "."
    context = ContextManager(config)

    messages = [
        {"role": "system", "content": "S" * 3375},
        {"role": "user", "content": "old request"},
        {"role": "user", "content": "X" * 4000},  # big tool result
        {"role": "user", "content": "now add a status command"},
    ]
    trimmed = context.trim_to_budget(messages, 2048)

    assert trimmed[0]["role"] == "system"
    assert trimmed[-1]["content"] == "now add a status command"
    assert any("now add a status command" in m["content"] for m in trimmed)


def test_trim_drops_oldest_first():
    """Older turns are dropped before newer ones."""
    config = MagicMock()
    config.root = "."
    context = ContextManager(config)

    messages = [
        {"role": "system", "content": "S" * 100},
        {"role": "user", "content": "OLDEST " + ("a" * 2000)},
        {"role": "user", "content": "MIDDLE " + ("b" * 200)},
        {"role": "user", "content": "NEWEST"},
    ]
    trimmed = context.trim_to_budget(messages, 200)

    contents = [m["content"] for m in trimmed]
    assert trimmed[0]["role"] == "system"
    assert "NEWEST" in contents
    assert not any(c.startswith("OLDEST") for c in contents)


def test_trim_under_budget_unchanged():
    """Messages under budget are returned untouched."""
    config = MagicMock()
    config.root = "."
    context = ContextManager(config)

    messages = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "hello"},
    ]
    assert context.trim_to_budget(messages, 8192) == messages


def test_trim_truncates_oversized_newest():
    """If the newest message alone exceeds the budget it is truncated, not dropped."""
    config = MagicMock()
    config.root = "."
    context = ContextManager(config)

    messages = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "Z" * 10000},
    ]
    trimmed = context.trim_to_budget(messages, 500)

    assert len(trimmed) == 2
    assert trimmed[1]["content"].startswith("Z")
    assert len(trimmed[1]["content"]) < 10000