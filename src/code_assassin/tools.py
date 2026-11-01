"""
Tool executor for agentic code-assassin operations.

All filesystem operations are confined to the project root. Read-only tools never
write; edit tools reuse the Editor's backup+undo pipeline and always back up before
writing (so writes are versioned, never destructive).
"""
import fnmatch
import os
import shlex
import subprocess
import re
from pathlib import Path
from typing import Callable, Optional, Tuple

MAX_FILE_SIZE = 256 * 1024      # 256 KB read cap
MAX_RESULT_CHARS = 8000         # per-tool result cap (read output)
RUN_OUTPUT_CHARS = 64 * 1024    # shell output cap
RUN_TIMEOUT = 60                # seconds per run command

FORBIDDEN_PATTERNS = [".git", ".code-assassin", ".env*", "*.pem", "*.key",
                      "id_rsa*", "*.p12", "*.pfx", ".*"]
RUN_BLOCKLIST_TOKENS = [
    "rm -rf", "rmdir", "format", "mkfs", "fdisk", "shutdown", "taskkill",
    "git push --force", "git reset --hard", "git clean", "pip uninstall -g",
    "npm uninstall -g", "sudo", "chmod -R", "/etc/", "/boot/", "/dev/",
]
READ_ONLY_GIT_TOKENS = {
    "git status", "git diff", "git diff --staged", "git log", "git show",
    "git ls-files", "git branch -a", "git remote -v", "git stash list",
    "git tag -l", "git blame", "git rev-parse", "git describe",
}
TEST_LINT_TOKENS = {"pytest", "uv run pytest", "python -m pytest", "ruff check",
                    "uv run ruff check", "mypy", "pyright"}
ALLOWLIST_TOKENS = READ_ONLY_GIT_TOKENS | TEST_LINT_TOKENS


class ToolExecutor:
    """Executes tool blocks produced by the model."""

    def __init__(
        self,
        project_root: Path,
        editor,
        ui,
        config,
        tool_log_callback: Optional[Callable[[dict], None]] = None,
    ):
        self.project_root = Path(project_root)
        self.editor = editor
        self.ui = ui
        self.config = config
        self.tool_log_callback = tool_log_callback

    def execute(self, tool_event) -> Tuple[bool, str, str]:
        kind = tool_event.tool_type
        if kind == "read":
            return self._read(tool_event)
        if kind == "list":
            return self._list(tool_event)
        if kind == "glob":
            return self._glob(tool_event)
        if kind == "grep":
            return self._grep(tool_event)
        if kind == "write":
            return self._write(tool_event)
        if kind == "run":
            return self._run(tool_event)
        if kind == "undo":
            return self._undo(tool_event)
        return False, f"unknown tool type: {kind}", ""

    def _safe_path(self, path_str: str) -> Optional[Path]:
        if not path_str:
            return None
        file_path = Path(path_str)
        try:
            file_path = (self.project_root / file_path).resolve()
            file_path.relative_to(self.project_root)
        except ValueError:
            return None
        for pattern in FORBIDDEN_PATTERNS:
            if fnmatch.fnmatch(file_path.name, pattern):
                return None
        return file_path

    def _truncate(self, text: str, limit: int = MAX_RESULT_CHARS) -> str:
        if len(text) <= limit:
            return text
        return text[:limit].rstrip() + "\n... [truncated]"

    def _format_result(self, kind: str, args: str, message: str, result: str = "") -> str:
        suffix = ""
        if result:
            suffix = "\n" + result
        return f"[tool result for {kind} {args}] {message}{suffix}"

    def _format_error(self, kind: str, args: str, message: str) -> str:
        return f"[tool error for {kind} {args}] {message}"

    def _read(self, tool_event) -> Tuple[bool, str, str]:
        path = self._safe_path(tool_event.tool_path)
        if not path:
            return False, self._format_error("read", repr(tool_event.tool_path), "invalid path"), ""
        if not path.exists():
            return False, self._format_error("read", repr(tool_event.tool_path), "not found"), ""
        if path.is_dir():
            return False, self._format_error("read", repr(tool_event.tool_path), "directory; use list"), ""
        try:
            size = path.stat().st_size
        except OSError:
            return False, self._format_error("read", repr(tool_event.tool_path), "stat failed"), ""
        if size > MAX_FILE_SIZE:
            return False, self._format_error("read", repr(tool_event.tool_path), "file too large"), ""
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return False, self._format_error("read", repr(tool_event.tool_path), "binary file not allowed"), ""
        msg = "read ok" if len(content) <= MAX_RESULT_CHARS else "read ok (truncated)"
        return True, self._format_result("read", repr(tool_event.tool_path), msg), self._truncate(content)

    def _list(self, tool_event) -> Tuple[bool, str, str]:
        if not tool_event.tool_path:
            path = self.project_root
        else:
            path = self._safe_path(tool_event.tool_path)
        if not path:
            return False, self._format_error("list", repr(tool_event.tool_path), "invalid path"), ""
        if not path.exists():
            return False, self._format_error("list", repr(tool_event.tool_path), "not found"), ""
        if not path.is_dir():
            return False, self._format_error("list", repr(tool_event.tool_path), "file; use read"), ""
        items = [p.name + "/" for p in path.iterdir() if p.is_dir()]
        items += [p.name for p in path.iterdir() if p.is_file()]
        items.sort()
        parts = "\n".join(items[:500])
        if len(items) > 500:
            parts += f"\n... ({len(items)} entries, shown first 500)"
        if not parts:
            parts = "<empty>"
        return True, self._format_result("list", repr(tool_event.tool_path), "list ok"), parts

    def _glob(self, tool_event) -> Tuple[bool, str, str]:
        pattern = tool_event.tool_pattern or "*"
        try:
            results = sorted(self.project_root.glob(pattern))
        except Exception as e:
            return False, self._format_error("glob", repr(pattern), f"glob failed: {e}"), ""
        paths = [str(p.relative_to(self.project_root).as_posix()) for p in results]
        parts = "\n".join(paths[:500])
        if len(paths) > 500:
            parts += f"\n... ({len(paths)} matches, shown first 500)"
        if not parts:
            parts = "<no matches>"
        return True, self._format_result("glob", repr(pattern), "glob ok"), parts

    def _grep(self, tool_event) -> Tuple[bool, str, str]:
        pattern = tool_event.tool_pattern or "."
        path = self._safe_path(tool_event.tool_path) or self.project_root
        if not path.exists():
            return False, self._format_error("grep", repr(tool_event.tool_path), "not found"), ""
        regex = re.compile(pattern)
        matches = []
        files_to_search = []
        if path.is_file():
            files_to_search = [path]
        else:
            for root, dirs, files in os.walk(path):
                dirs[:] = sorted(d for d in dirs if not d.startswith("."))
                files_to_search.extend(sorted(Path(root) / f for f in files))
        for full in files_to_search:
            try:
                text = full.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            lines = text.split("\n")
            for i, line in enumerate(lines):
                if regex.search(line):
                    rel = full.relative_to(self.project_root).as_posix()
                    matches.append(f"{rel}:{i + 1}: {line}")
                    if len(matches) >= 500:
                        break
            if len(matches) >= 500:
                break
        parts = "\n".join(matches[:500])
        if len(matches) > 500:
            parts += f"\n... ({len(matches)} matches, shown first 500)"
        if not parts:
            parts = "<no matches>"
        return True, self._format_result("grep", repr(pattern), "grep ok"), parts

    def _write(self, tool_event) -> Tuple[bool, str, str]:
        path = tool_event.tool_path
        content = tool_event.content
        safe = self._safe_path(path)
        if not safe:
            return False, self._format_error("write", repr(path), "invalid path"), ""
        if not content:
            return False, self._format_error("write", repr(path), "empty content"), ""
        ok, msg = self.editor.write_file(path, content)
        if ok:
            return True, self._format_result("write", repr(path), msg), "<written>"
        return False, self._format_error("write", repr(path), msg), ""

    def _run(self, tool_event) -> Tuple[bool, str, str]:
        cmd = tool_event.tool_cmd
        if not cmd:
            return False, self._format_error("run", "", "missing command"), ""
        if not self.config.run:
            return False, self._format_error("run", repr(cmd), "run tool disabled"), ""
        for token in RUN_BLOCKLIST_TOKENS:
            if token in cmd:
                return False, self._format_error("run", repr(cmd), f"command blocked: {token}"), ""
        if self._is_auto_allowed(cmd):
            return self._do_run(cmd)
        if self.ui is not None and hasattr(self.ui, "confirm"):
            try:
                confirmed = self.ui.confirm(f"Run: {cmd}")
            except Exception:
                confirmed = False
        else:
            confirmed = False
        if not confirmed:
            return False, self._format_error("run", repr(cmd), "command declined by user"), ""
        return self._do_run(cmd)

    def _is_auto_allowed(self, cmd: str) -> bool:
        cmd_l = cmd.lower()
        for token in ALLOWLIST_TOKENS:
            if cmd_l.startswith(token.lower()):
                return True
        # Also match 'uv run pytest ...' style where the token is a prefix after 'uv run'
        return False

    def _do_run(self, cmd: str) -> Tuple[bool, str, str]:
        cwd = str(self.project_root)
        try:
            proc = subprocess.run(
                shlex.split(cmd),
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=RUN_TIMEOUT,
            )
        except subprocess.TimeoutExpired:
            entry = {"command": cmd, "exit": None, "captured": "command timed out"}
            if self.tool_log_callback:
                try:
                    self.tool_log_callback(entry)
                except Exception:
                    pass
            return False, self._format_error("run", repr(cmd), "command timed out"), ""
        except Exception as e:
            entry = {"command": cmd, "exit": None, "captured": str(e)}
            if self.tool_log_callback:
                try:
                    self.tool_log_callback(entry)
                except Exception:
                    pass
            return False, self._format_error("run", repr(cmd), f"run failed: {e}"), ""
        output = proc.stdout + ("\n" + proc.stderr if proc.stderr else "")
        if len(output) > RUN_OUTPUT_CHARS:
            output = output[:RUN_OUTPUT_CHARS].rstrip() + "\n... [truncated]"
        exit_info = f" (exit {proc.returncode})" if proc.returncode not in (0, None) else ""
        entry = {"command": cmd, "exit": proc.returncode, "captured": output}
        if self.tool_log_callback:
            try:
                self.tool_log_callback(entry)
            except Exception:
                pass
        msg = f"run ok{exit_info}"
        return True, self._format_result("run", repr(cmd), msg), output

    def _undo(self, tool_event) -> Tuple[bool, str, str]:
        ok = self.editor.undo("default")
        return True if ok else False, "undo processed" if ok else "no edits to undo", ""
