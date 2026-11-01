"""
Terminal UI rendering with Rich.
"""
import sys
from typing import Optional
from rich.console import Console
from rich.syntax import Syntax
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text


def _prepare_windows_console() -> None:
    """Make the Windows console UTF-8 safe.

    Rich's LegacyWindowsTerm captures ``sys.stdout`` at import time, so the
    stream must be reconfigured *in place*. Without this, printing glyphs like
    ``▶`` or ``—`` raises UnicodeEncodeError on cp1252 consoles.
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.kernel32.SetConsoleOutputCP(65001)
        ctypes.windll.kernel32.SetConsoleCP(65001)
    except Exception:
        pass
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass


class UI:
    """Rich-based terminal UI."""

    def __init__(self, console: Optional[Console] = None):
        if console is None:
            _prepare_windows_console()
        self.console = console or Console()
        self._prose_buffer: list[str] = []

    def print_header(self, text: str):
        self.console.print(Panel(Text(text, style="bold cyan"), border_style="cyan"))

    def print_status(self, text: str, style: str = "yellow"):
        self.console.print(f"[{style}]{text}[/{style}]")

    def print_prose(self, text: str):
        """Print prose inline without forcing a newline per fragment.

        The parser streams small fragments; Rich's console.print adds a newline
        after every call, which turns each fragment into its own line. We instead
        append to a buffer and render once (on the next non-prose event or via
        flush) so output stays horizontal and readable.
        """
        self._prose_buffer.append(text)
        # Auto-flush on newline within the buffer to keep things responsive
        while "\n" in "".join(self._prose_buffer):
            buf = "".join(self._prose_buffer)
            before, after = buf.split("\n", 1)
            if before:
                self.console.print(before, soft_wrap=True)
            self._prose_buffer = [after]

    def flush_prose(self):
        """Flush any buffered prose to the terminal."""
        buf = "".join(self._prose_buffer)
        if buf:
            self.console.print(buf, soft_wrap=True)
        self._prose_buffer = []

    def print_code(self, code: str, language: str = ""):
        syntax = Syntax(code, language or "python", theme="monokai", line_numbers=True)
        self.console.print(syntax)

    def print_diff(self, diff: str):
        from rich.text import Text
        lines = diff.split("\n")
        for line in lines:
            if line.startswith("+"):
                self.console.print(line, style="green")
            elif line.startswith("-"):
                self.console.print(line, style="red")
            elif line.startswith("@@"):
                self.console.print(line, style="bold blue")
            else:
                self.console.print(line)

    def print_warning(self, text: str):
        self.console.print(f"[bold yellow]Warning:[/bold yellow] {text}")

    def print_error(self, text: str):
        self.console.print(f"[bold red]Error:[/bold red] {text}")

    def print_success(self, text: str):
        self.console.print(f"[bold green]OK:[/bold green] {text}")

    def print_prompt(self, text: str = ">"):
        return self.console.input(f"[bold green]{text}[/bold green] ")

    def confirm(self, prompt: str, default: bool = False) -> bool:
        """Yes/no confirmation prompt. Returns True for yes."""
        suffix = " [y/N]" if not default else " [Y/n]"
        try:
            raw = self.console.input(f"[bold yellow]{prompt}{suffix}[/bold yellow] ").strip().lower()
        except (EOFError, OSError):
            return default
        if not raw:
            return default
        return raw in ("y", "yes")

    def print_tool(self, text: str):
        """Render a tool step status line."""
        self.console.print(f"[bold magenta]▶ {text}[/bold magenta]")