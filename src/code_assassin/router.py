"""
Router: routes events to speech queue, terminal UI, and editor.
"""
from typing import Callable, Optional
from .parser import Event, EventType


class Router:
    """Routes parser events to appropriate handlers."""

    def __init__(self):
        self.on_speak: Optional[Callable[[str], None]] = None
        self.on_prose: Optional[Callable[[str], None]] = None
        self.on_code_block: Optional[Callable[[Event], None]] = None
        self.on_warning: Optional[Callable[[str], None]] = None
        self.on_tool: Optional[Callable[[str], None]] = None
        self.on_done: Optional[Callable[[], None]] = None

    def route(self, event: Event):
        if event.type == EventType.SPEAK:
            if self.on_speak:
                self.on_speak(event.content)
        elif event.type == EventType.PROSE:
            if self.on_prose:
                self.on_prose(event.content)
        elif event.type == EventType.CODE_BLOCK:
            if self.on_code_block:
                self.on_code_block(event)
        elif event.type == EventType.WARNING:
            if self.on_warning:
                self.on_warning(event.content)
        elif event.type == EventType.TOOL:
            if self.on_tool:
                self.on_tool(event.content)
        elif event.type == EventType.DONE:
            if self.on_done:
                self.on_done()