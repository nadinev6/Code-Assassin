"""
Tests for the router module.
"""
import pytest
from code_assassin.router import Router
from code_assassin.parser import Event, EventType


def test_router_speak():
    """Test router speak event."""
    router = Router()
    received = []
    router.on_speak = lambda text: received.append(text)
    
    router.route(Event(EventType.SPEAK, "Hello"))
    assert "Hello" in received


def test_router_prose():
    """Test router prose event."""
    router = Router()
    received = []
    router.on_prose = lambda text: received.append(text)
    
    router.route(Event(EventType.PROSE, "Some prose"))
    assert "Some prose" in received


def test_router_code_block():
    """Test router code block event."""
    router = Router()
    received = []
    router.on_code_block = lambda e: received.append(e)
    
    event = Event(EventType.CODE_BLOCK, content="print('hi')", language="python", path="test.py")
    router.route(event)
    assert len(received) == 1
    assert received[0].path == "test.py"