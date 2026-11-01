"""
Tests for the tool executor module.
"""
import os
import tempfile
import pytest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from code_assassin.tools import ToolExecutor
from code_assassin.editor import Editor
from code_assassin.config import Config


def _make_tool(tmp_path, config=None):
    """Create a ToolExecutor with a project root and editor."""
    root = tmp_path
    editor = Editor(backup_dir=str(root / "backups"), root=root)
    ui = MagicMock()
    if config is None:
        config = Config()
        config.run = True
    return ToolExecutor(
        project_root=root,
        editor=editor,
        ui=ui,
        config=config,
    )


def test_read_existing_file(tmp_path):
    """Read a file returns its content."""
    (tmp_path / "a.txt").write_text("hello world", encoding="utf-8")
    te = _make_tool(tmp_path)
    ev = SimpleNamespace(tool_type="read", tool_path="a.txt")
    ok, msg, result = te.execute(ev)
    assert ok
    assert "hello world" in result


def test_read_missing_file(tmp_path):
    """Read a missing file returns an error."""
    te = _make_tool(tmp_path)
    ev = SimpleNamespace(tool_type="read", tool_path="nope.txt")
    ok, msg, result = te.execute(ev)
    assert not ok


def test_read_forbidden_path(tmp_path):
    """Read a forbidden file (.env) returns an error."""
    (tmp_path / ".env").write_text("SECRET=1", encoding="utf-8")
    te = _make_tool(tmp_path)
    ev = SimpleNamespace(tool_type="read", tool_path=".env")
    ok, msg, result = te.execute(ev)
    assert not ok


def test_read_traversal_blocked(tmp_path):
    """Read a path that escapes root is blocked."""
    (tmp_path / "a.txt").write_text("hello", encoding="utf-8")
    te = _make_tool(tmp_path)
    ev = SimpleNamespace(tool_type="read", tool_path="../a.txt")
    ok, msg, result = te.execute(ev)
    assert not ok


def test_write_creates_new_file(tmp_path):
    """Write a new file creates it."""
    te = _make_tool(tmp_path)
    ev = SimpleNamespace(tool_type="write", tool_path="new.py", content="print('hi')")
    ok, msg, result = te.execute(ev)
    assert ok
    assert (tmp_path / "new.py").read_text(encoding="utf-8") == "print('hi')"


def test_write_forbidden_path(tmp_path):
    """Write to a forbidden path is blocked."""
    te = _make_tool(tmp_path)
    ev = SimpleNamespace(tool_type="write", tool_path=".env", content="SECRET=1")
    ok, msg, result = te.execute(ev)
    assert not ok


def test_list_directory(tmp_path):
    """List a directory returns its entries."""
    (tmp_path / "a.txt").write_text("a")
    (tmp_path / "sub").mkdir()
    te = _make_tool(tmp_path)
    ev = SimpleNamespace(tool_type="list", tool_path="")
    ok, msg, result = te.execute(ev)
    assert ok
    assert "a.txt" in result
    assert "sub/" in result


def test_glob_pattern(tmp_path):
    """Glob returns matching files."""
    (tmp_path / "x.py").write_text("a")
    (tmp_path / "y.txt").write_text("b")
    te = _make_tool(tmp_path)
    ev = SimpleNamespace(tool_type="glob", tool_pattern="*.py")
    ok, msg, result = te.execute(ev)
    assert ok
    assert "x.py" in result
    assert "y.txt" not in result


def test_grep_pattern(tmp_path):
    """Grep returns matching lines."""
    (tmp_path / "x.py").write_text("def foo():\n    return 1\n", encoding="utf-8")
    te = _make_tool(tmp_path)
    ev = SimpleNamespace(tool_type="grep", tool_pattern="def foo", tool_path="x.py")
    ok, msg, result = te.execute(ev)
    assert ok
    assert "def foo" in result


def test_run_auto_allowed(tmp_path):
    """Run an allowlisted command (git status) executes without prompt."""
    te = _make_tool(tmp_path)
    ev = SimpleNamespace(tool_type="run", tool_cmd="git status", tool_path="", tool_pattern="", content="")
    ok, msg, result = te.execute(ev)
    assert ok
    assert "git status" in msg


def test_run_blocked_command(tmp_path):
    """Run a blocked command is refused."""
    te = _make_tool(tmp_path)
    ev = SimpleNamespace(tool_type="run", tool_cmd="rm -rf /", tool_path="", tool_pattern="", content="")
    ok, msg, result = te.execute(ev)
    assert not ok
    assert "blocked" in msg


def test_run_disabled(tmp_path):
    """Run tool disabled returns error."""
    config = Config()
    config.run = False
    te = _make_tool(tmp_path, config=config)
    ev = SimpleNamespace(tool_type="run", tool_cmd="git status", tool_path="", tool_pattern="", content="")
    ok, msg, result = te.execute(ev)
    assert not ok
    assert "disabled" in msg


def test_run_non_allowed_prompts(tmp_path):
    """Run a non-allowlisted command prompts the user (declined -> refused)."""
    te = _make_tool(tmp_path)
    te.ui.confirm = MagicMock(return_value=False)
    ev = SimpleNamespace(tool_type="run", tool_cmd="echo hi", tool_path="", tool_pattern="", content="")
    ok, msg, result = te.execute(ev)
    assert not ok
    assert "declined" in msg


def test_unknown_tool_type(tmp_path):
    """Unknown tool type returns an error."""
    te = _make_tool(tmp_path)
    ev = SimpleNamespace(tool_type="frobnicate", tool_path="", tool_pattern="", content="")
    ok, msg, result = te.execute(ev)
    assert not ok
    assert "unknown" in msg


def test_truncate_helper(tmp_path):
    """_truncate caps long text."""
    te = _make_tool(tmp_path)
    long = "x" * 100000
    truncated = te._truncate(long, limit=100)
    assert len(truncated) <= 100 + len("\n... [truncated]")