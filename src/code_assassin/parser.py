"""
Incremental streaming parser for Code Assassin model output.

State machine tolerant of chunk boundaries and CRLF. Supports both the
tagged protocol (<speak>/<detail>) and raw fenced output.
"""
from dataclasses import dataclass
from enum import Enum
import re
import shlex
import fnmatch


class EventType(Enum):
    SPEAK = "speak"
    PROSE = "prose"
    CODE_BLOCK = "code_block"
    WARNING = "warning"
    DONE = "done"
    TOOL = "tool"


@dataclass
class Event:
    type: EventType
    content: str = ""
    language: str = ""
    path: str = ""
    is_diff: bool = False
    tool_type: str = ""
    tool_path: str = ""
    tool_pattern: str = ""
    tool_cmd: str = ""


class ParserState(Enum):
    IDLE = "idle"
    IN_SPEAK = "in_speak"
    IN_DETAIL = "in_detail"
    IN_FENCE = "in_fence"


_TAGS = ("<speak>", "</speak>", "<detail>", "</detail>")


class Parser:
    """Incremental state machine that parses model output as it streams."""

    def __init__(self):
        self.state = ParserState.IDLE
        self.tag_buffer = ""
        self.speak_content = ""
        self.detail_buffer = ""
        self.line_buffer = ""
        self.fence_buffer = ""
        self.fence_language = ""
        self.fence_path = ""
        self.is_diff = False
        self._fence_content_started = False
        self.events: list[Event] = []
        self.is_tool = False

    def feed(self, chunk: str) -> list[Event]:
        """Feed a chunk of text, return any events produced."""
        self.events = []
        chunk = chunk.replace("\r\n", "\n").replace("\r", "\n")
        for char in chunk:
            self._process_char(char)
        # Flush any buffered non-tag, non-fence line at end of chunk
        if self.line_buffer and self.state == ParserState.IDLE:
            if not self.line_buffer.strip().startswith("```") and not any(
                t.startswith(self.line_buffer) for t in _TAGS
            ):
                self._emit(Event(EventType.PROSE, self.line_buffer))
                self.line_buffer = ""
        return self.events

    def _process_char(self, char: str):
        if self.state == ParserState.IDLE:
            self._handle_idle(char)
        elif self.state == ParserState.IN_SPEAK:
            self._handle_speak(char)
        elif self.state == ParserState.IN_DETAIL:
            self._handle_detail(char)
        elif self.state == ParserState.IN_FENCE:
            self._handle_fence(char)

    def _handle_idle(self, char: str):
        if char == "<":
            self.tag_buffer = "<"
        elif self.tag_buffer:
            self.tag_buffer += char
            if self.tag_buffer == "<speak>":
                self.state = ParserState.IN_SPEAK
                self.speak_content = ""
                self.tag_buffer = ""
            elif self.tag_buffer == "<detail>":
                self.state = ParserState.IN_DETAIL
                self.detail_buffer = ""
                self.tag_buffer = ""
            elif self.tag_buffer == "</speak>":
                self._emit(Event(EventType.SPEAK, self.speak_content))
                self.speak_content = ""
                self.tag_buffer = ""
            elif self.tag_buffer == "</detail>":
                content = self.detail_buffer.rstrip("\n")
                if content:
                    self._emit(Event(EventType.PROSE, content))
                self.detail_buffer = ""
                self.tag_buffer = ""
            elif not any(t.startswith(self.tag_buffer) for t in _TAGS):
                self._emit(Event(EventType.PROSE, self.tag_buffer))
                self.tag_buffer = ""
        else:
            if char == "\n":
                if self.line_buffer.strip().startswith("```"):
                    self._start_fence(self.line_buffer)
                else:
                    self._emit(Event(EventType.PROSE, self.line_buffer + "\n"))
                self.line_buffer = ""
            else:
                self.line_buffer += char

    def _handle_speak(self, char: str):
        if char == "<":
            self.tag_buffer = "<"
        elif self.tag_buffer:
            self.tag_buffer += char
            if self.tag_buffer == "</speak>":
                self._emit(Event(EventType.SPEAK, self.speak_content))
                self.speak_content = ""
                self.tag_buffer = ""
                self.state = ParserState.IDLE
            elif self.tag_buffer == "<detail>":
                # Unexpected <detail> inside <speak>; switch to detail
                self.speak_content += "<detail>"
                self.tag_buffer = ""
                self.state = ParserState.IN_DETAIL
                self.detail_buffer = ""
            elif not any(t.startswith(self.tag_buffer) for t in _TAGS):
                self.speak_content += self.tag_buffer
                self.tag_buffer = ""
        else:
            self.speak_content += char

    def _handle_detail(self, char: str):
        if char == "<":
            self.tag_buffer = "<"
        elif self.tag_buffer:
            self.tag_buffer += char
            if self.tag_buffer == "</detail>":
                content = self.detail_buffer.rstrip("\n")
                if content:
                    self._emit(Event(EventType.PROSE, content))
                self.detail_buffer = ""
                self.tag_buffer = ""
                self.state = ParserState.IDLE
            elif self.tag_buffer == "<detail>":
                self.tag_buffer = ""
            elif not any(t.startswith(self.tag_buffer) for t in _TAGS):
                self.detail_buffer += self.tag_buffer
                self.tag_buffer = ""
        else:
            if char == "\n":
                self.detail_buffer += "\n"
                lines = self.detail_buffer.split("\n")
                if len(lines) >= 2 and lines[-2].strip().startswith("```"):
                    preceding = "\n".join(lines[:-2])
                    if preceding:
                        self._emit(Event(EventType.PROSE, preceding + "\n"))
                    self._start_fence(lines[-2].strip())
                    self.detail_buffer = ""
            else:
                self.detail_buffer += char

    def _handle_fence(self, char: str):
        self.fence_buffer += char
        if char == "\n":
            lines = self.fence_buffer.split("\n")
            completed = lines[-2] if len(lines) >= 2 else ""
            # Consume file= attribute lines before the content starts
            if not self._fence_content_started and completed.strip().startswith("file="):
                self.fence_path = completed.strip()[len("file="):].strip()
                self.fence_buffer = "\n".join(lines[1:])
                return
            if not self._fence_content_started and completed.strip():
                self._fence_content_started = True
            if len(lines) >= 2 and lines[-2].strip().startswith("```"):
                self._close_fence()
        else:
            # Detect a closing fence that arrives without a trailing newline
            # Close immediately when we see a closing fence (```), even without content
            if self.fence_buffer.endswith("```") and (
                self.fence_buffer == "```" or self.fence_buffer.endswith("\n```")
            ):
                self._close_fence()

    def _start_fence(self, line: str):
        info = line.strip()
        if not info.startswith("```"):
            return
        info = info[3:].strip()
        self.is_diff = info.startswith("diff")
        parts = info.split()
        self.fence_language = parts[0] if parts else ""
        self.fence_path = ""
        self.tool_type = ""
        self.tool_path = ""
        self.tool_pattern = ""
        self.tool_cmd = ""
        if self.fence_language == "tool":
            self.is_tool = True
            # Use shlex to properly tokenize attributes (handles quoted values)
            try:
                tokens = shlex.split(info)
            except ValueError:
                tokens = parts
            for part in tokens[1:]:
                self._parse_tool_attr(part)
        else:
            self.is_tool = False
            for part in parts[1:]:
                if part.startswith("file="):
                    try:
                        self.fence_path = shlex.split(part)[0].split("=", 1)[1]
                    except Exception:
                        self.fence_path = part.split("=", 1)[1]
        self.fence_buffer = ""
        self._fence_content_started = False
        self.state = ParserState.IN_FENCE

    def _parse_tool_attr(self, part: str):
        if "=" not in part:
            return
        key, _, value = part.partition("=")
        key = key.strip().lower()
        if key == "type":
            self.tool_type = value.strip()
        elif key == "path":
            self.tool_path = value.strip()
        elif key == "pattern":
            self.tool_pattern = value.strip()
        elif key in ("cmd", "command"):
            # Models often write `command=`; treat it as `cmd=`.
            self.tool_cmd = value.strip()
        elif key == "args":
            # Append extra args to the command the model already gave.
            self.tool_cmd = (self.tool_cmd + " " + value.strip()).strip()

    def _close_fence(self):
        content = self.fence_buffer
        lines = content.split("\n")
        # Strip trailing empty lines
        while lines and lines[-1].strip() == "":
            lines.pop()
        # Strip the closing fence line
        if lines and lines[-1].strip().startswith("```"):
            lines.pop()
        content = "\n".join(lines).rstrip("\n")
        if self.is_tool:
            self._emit(Event(
                EventType.TOOL,
                content=content,
                tool_type=self.tool_type,
                tool_path=self.tool_path,
                tool_pattern=self.tool_pattern,
                tool_cmd=self.tool_cmd,
            ))
        else:
            self._emit(Event(
                EventType.CODE_BLOCK,
                content=content,
                language=self.fence_language,
                path=self.fence_path,
                is_diff=self.is_diff,
            ))
        self.fence_buffer = ""
        self.fence_language = ""
        self.fence_path = ""
        self.is_diff = False
        self.is_tool = False
        self.tool_type = ""
        self.tool_path = ""
        self.tool_pattern = ""
        self.tool_cmd = ""
        self._fence_content_started = False
        self.state = ParserState.IN_DETAIL

    def _emit(self, event: Event):
        self.events.append(event)

    def flush(self) -> list[Event]:
        """Flush any unclosed tags/fences at EOF."""
        events = []
        if self.line_buffer:
            if self.line_buffer.strip().startswith("```"):
                self._start_fence(self.line_buffer)
            else:
                self._emit(Event(EventType.PROSE, self.line_buffer))
            self.line_buffer = ""
        if self.state == ParserState.IN_SPEAK:
            if self.speak_content:
                events.append(Event(EventType.SPEAK, self.speak_content))
            events.append(Event(EventType.WARNING, "Unclosed <speak> tag"))
        elif self.state == ParserState.IN_DETAIL:
            if self.detail_buffer:
                events.append(Event(EventType.PROSE, self.detail_buffer))
            events.append(Event(EventType.WARNING, "Unclosed <detail> tag"))
        elif self.state == ParserState.IN_FENCE:
            if self.fence_buffer:
                events.append(Event(EventType.CODE_BLOCK, content=self.fence_buffer))
            events.append(Event(EventType.WARNING, "Unclosed code fence"))
        self.events.extend(events)
        self.state = ParserState.IDLE
        return events