"""
Tests for the parser module.
"""
import pytest
from code_assassin.parser import Parser, EventType, Event


def test_parser_basic_prose():
    """Test basic prose parsing."""
    parser = Parser()
    events = parser.feed("Hello world")
    assert len(events) > 0
    assert any(e.type == EventType.PROSE for e in events)


def test_parser_speak_tag():
    """Test <speak> tag parsing."""
    parser = Parser()
    events = parser.feed("<speak>Hello there</speak>")
    speak_events = [e for e in events if e.type == EventType.SPEAK]
    assert len(speak_events) > 0


def test_parser_detail_tag():
    """Test <detail> tag parsing."""
    parser = Parser()
    events = parser.feed("<detail>Some detail</detail>")
    prose_events = [e for e in events if e.type == EventType.PROSE]
    assert any("Some detail" in e.content for e in prose_events)


def test_parser_crlf():
    """Test CRLF handling."""
    parser = Parser()
    events = parser.feed("Line one\r\nLine two\r\n")
    prose_events = [e for e in events if e.type == EventType.PROSE]
    combined = "".join(e.content for e in prose_events)
    assert "Line one" in combined
    assert "Line two" in combined


def test_parser_fence():
    """Test code fence parsing."""
    parser = Parser()
    events = parser.feed("```python\nprint('hello')\n```")
    code_events = [e for e in events if e.type == EventType.CODE_BLOCK]
    assert len(code_events) > 0
    assert code_events[0].language == "python"
    assert "print('hello')" in code_events[0].content


def test_parser_fence_with_file():
    """Test code fence with file attribute."""
    parser = Parser()
    events = parser.feed("```python file=src/test.py\nprint('hello')\n```")
    code_events = [e for e in events if e.type == EventType.CODE_BLOCK]
    assert len(code_events) > 0
    assert code_events[0].path == "src/test.py"


def test_parser_diff_fence():
    """Test diff fence parsing."""
    parser = Parser()
    events = parser.feed("```diff file=src/test.py\n--- a/test.py\n+++ b/test.py\n+new line\n```")
    code_events = [e for e in events if e.type == EventType.CODE_BLOCK]
    assert len(code_events) > 0
    assert code_events[0].is_diff == True


def test_parser_chunk_boundary():
    """Test parsing across chunk boundaries."""
    parser = Parser()
    events1 = parser.feed("<speak>Hel")
    assert len([e for e in events1 if e.type == EventType.SPEAK]) == 0  # Not complete yet
    
    events2 = parser.feed("lo</speak>")
    speak_events = [e for e in events2 if e.type == EventType.SPEAK]
    assert len(speak_events) > 0


def test_parser_flush():
    """Test flush at EOF."""
    parser = Parser()
    parser.feed("<speak>Unclosed")
    events = parser.flush()
    warning_events = [e for e in events if e.type == EventType.WARNING]
    assert len(warning_events) > 0


def test_parser_malformed_tags():
    """Test malformed tag handling."""
    parser = Parser()
    events = parser.feed("<speak>Text</wrong>")
    # Should handle gracefully without crashing
    assert isinstance(events, list)


def test_parser_tool_fence_read():
    """Test tool fence parsing for read."""
    parser = Parser()
    events = parser.feed("```tool type=read path=src/test.py\n```")
    tool_events = [e for e in events if e.type == EventType.TOOL]
    assert len(tool_events) > 0
    assert tool_events[0].tool_type == "read"
    assert tool_events[0].tool_path == "src/test.py"


def test_parser_tool_fence_run():
    """Test tool fence parsing for run."""
    parser = Parser()
    events = parser.feed("```tool type=run cmd=\"uv run pytest -q\"\n```")
    tool_events = [e for e in events if e.type == EventType.TOOL]
    assert len(tool_events) > 0
    assert tool_events[0].tool_type == "run"
    assert tool_events[0].tool_cmd == "uv run pytest -q"


def test_parser_tool_fence_with_content():
    """Test tool fence parsing with write content."""
    parser = Parser()
    events = parser.feed("```tool type=write path=tests/test_x.py\nx = 1\n```")
    tool_events = [e for e in events if e.type == EventType.TOOL]
    assert len(tool_events) > 0
    assert tool_events[0].tool_type == "write"
    assert tool_events[0].tool_path == "tests/test_x.py"
    assert "x = 1" in tool_events[0].content


def test_parser_tool_fence_command_alias():
    """Models write command=/args=; both must map onto cmd."""
    parser = Parser()
    events = parser.feed('```tool type=run command="pytest" args="--cov=x"\n```')
    tool_events = [e for e in events if e.type == EventType.TOOL]
    assert len(tool_events) > 0
    assert tool_events[0].tool_type == "run"
    assert tool_events[0].tool_cmd == "pytest --cov=x"