"""
Tests for the session module.
"""
import json
import os
import tempfile
import pytest
from code_assassin.session import Session


def test_session_save_and_load(tmp_path):
    """Test saving and loading a session."""
    memory_dir = tmp_path / ".code-assassin"
    session = Session(task="test", memory_dir=str(memory_dir))
    session.add_turn("user", "Hello")
    session.add_turn("assistant", "Hi there")
    session.save()
    
    # Load fresh session
    session2 = Session(task="test", memory_dir=str(memory_dir))
    session2.load()
    assert len(session2.turns) == 2
    assert session2.turns[0]["role"] == "user"
    assert session2.turns[0]["content"] == "Hello"


def test_session_turn_cap(tmp_path):
    """Test that turns are capped at MAX_STORED_TURNS."""
    memory_dir = tmp_path / ".code-assassin"
    session = Session(task="test", memory_dir=str(memory_dir))
    
    # Add more than MAX_STORED_TURNS
    for i in range(60):
        session.add_turn("user", f"Message {i}")
    
    assert len(session.turns) <= Session.MAX_STORED_TURNS


def test_session_prompt_turns(tmp_path):
    """Test getting prompt turns."""
    memory_dir = tmp_path / ".code-assassin"
    session = Session(task="test", memory_dir=str(memory_dir))
    
    for i in range(10):
        session.add_turn("user", f"Message {i}")
    
    prompt_turns = session.get_prompt_turns(max_turns=3)
    assert len(prompt_turns) == 3
    assert prompt_turns[-1]["content"] == "Message 9"


def test_session_corrupt_file(tmp_path):
    """Test handling corrupt session file."""
    memory_dir = tmp_path / ".code-assassin"
    memory_dir.mkdir(parents=True, exist_ok=True)
    session_path = memory_dir / "memory_test.json"
    
    # Write corrupt JSON
    session_path.write_text("not valid json{{{")
    
    session = Session(task="test", memory_dir=str(memory_dir))
    session.load()
    # Should not crash, starts fresh
    assert len(session.turns) == 0


def test_session_clear(tmp_path):
    """Test clearing a session."""
    memory_dir = tmp_path / ".code-assassin"
    session = Session(task="test", memory_dir=str(memory_dir))
    session.add_turn("user", "Hello")
    session.clear()
    
    session.load()
    assert len(session.turns) == 0


def test_session_sanitize_task():
    """Test task name sanitization."""
    session = Session(task="../../../etc/passwd")
    assert session.task != "../../../etc/passwd"
    assert "/" not in session.task
    
    session2 = Session(task="my-task")
    assert session2.task == "my-task"