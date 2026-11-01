"""
Editor for applying changes from model output.
"""
import json
import subprocess
import shutil
import hashlib
import fnmatch
import os
from pathlib import Path
from typing import Optional
from datetime import datetime


class Editor:
    """Applies changes from model output with safety checks."""

    def __init__(self, backup_dir: str = ".code-assassin/backups", root: Optional[Path] = None):
        self.backup_dir = Path(backup_dir)
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        self.edits_enabled = True
        self.overwrite_mode = False
        self._project_root = Path(root).resolve() if root else Path.cwd().resolve()

    def enable(self):
        """Enable auto-applying edits."""
        self.edits_enabled = True

    def disable(self):
        """Disable auto-applying edits."""
        self.edits_enabled = False

    def set_overwrite_mode(self, enabled: bool):
        """Set overwrite mode (allow replacing existing files)."""
        self.overwrite_mode = enabled

    def set_enabled(self, enabled: bool):
        """Enable or disable auto-applying edits."""
        if enabled:
            self.enable()
        else:
            self.disable()

    def apply_with_result(self, code_block) -> tuple[bool, str]:
        """Apply a code block, returning (ok, message)."""
        if not self.edits_enabled:
            return False, "auto-editing is disabled"
        try:
            path = self._validate_path(code_block.path, code_block.is_diff)
        except ValueError as e:
            return False, str(e)
        if not path:
            return False, f"edit rejected for {code_block.path!r}"
        backup_path = self._create_backup(path, code_block.is_diff)
        try:
            if code_block.is_diff:
                self._apply_diff(path, code_block.content, backup_path)
            else:
                self._apply_file(path, code_block.content, backup_path)
            return True, f"wrote {path}"
        except Exception as e:
            self._rollback(backup_path, e)
            return False, f"edit failed: {e}"

    def apply(self, code_block):
        """Apply a code block from model output."""
        ok, _ = self.apply_with_result(code_block)
        return ok

    def write_file(self, path: str, content: str) -> tuple[bool, str]:
        """Write a full file with backup. Always applies (agent writes are versioned)."""
        if not self.edits_enabled:
            return False, "auto-editing is disabled"
        try:
            file_path = self._validate_path(path, is_diff=False, force_overwrite=True)
        except ValueError as e:
            return False, str(e)
        if not file_path:
            return False, f"write rejected for {path!r}"
        backup_path = self._create_backup(file_path, is_diff=False)
        try:
            self._apply_file(file_path, content, backup_path)
            return True, f"wrote {file_path}"
        except Exception as e:
            self._rollback(backup_path, e)
            return False, f"write failed: {e}"

    def _validate_path(self, path: str, is_diff: bool, force_overwrite: bool = False) -> Optional[Path]:
        """Validate and sanitize file path."""
        if not path:
            return None

        file_path = Path(path)
        file_path = (self._get_project_root() / file_path).resolve()

        # Security: must be within project root
        try:
            file_path.relative_to(self._get_project_root())
        except ValueError:
            raise ValueError(f"Path escapes project root: {path}")

        # Check for forbidden patterns (glob-style matching)
        forbidden_patterns = [".git", ".code-assassin", ".env*", "*.pem", "*.key",
                              "id_rsa*", "*.p12", "*.pfx", ".*"]
        for pattern in forbidden_patterns:
            if fnmatch.fnmatch(file_path.name, pattern):
                raise ValueError(f"Path contains forbidden pattern: {path}")

        # Check file size (only if file exists)
        if file_path.exists():
            if file_path.stat().st_size > 256 * 1024:  # 256 KB
                raise ValueError(f"File too large: {path}")

        # Ensure parent directory exists
        if not file_path.parent.exists():
            file_path.parent.mkdir(parents=True, exist_ok=True)

        # Check if file is binary — only if file exists and is not empty
        if file_path.exists() and file_path.stat().st_size > 0:
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    f.read()
            except UnicodeDecodeError:
                raise ValueError(f"Binary file not allowed: {path}")

        # Check if diff would overwrite existing file
        if file_path.exists() and not is_diff and not self.overwrite_mode and not force_overwrite:
            # Check if it's a language fence (new file) or diff fence
            return None  # Print-only

        return file_path

    def _get_project_root(self) -> Path:
        """Get project root directory."""
        return self._project_root

    def _create_backup(self, file_path: Path, is_diff: bool) -> Path:
        """Create backup of file before modification."""
        timestamp = datetime.now().strftime("%Y%m%dT%H%M%S%f")
        backup_path = self.backup_dir / f"{timestamp}_{hashlib.sha256(file_path.name.encode()).hexdigest()}"
        backup_path.mkdir(parents=True, exist_ok=True)

        # Copy file content
        if file_path.exists():
            shutil.copy2(file_path, backup_path / file_path.name)
            with open(backup_path / "manifest.json", "w") as f:
                json.dump({
                    "path": str(file_path.relative_to(self._get_project_root())),
                    "action": "edit" if not is_diff else "diff",
                    "sha256": hashlib.sha256(file_path.read_bytes()).hexdigest(),
                    "created": timestamp
                }, f)

        return backup_path

    def _apply_diff(self, file_path: Path, diff_content: str, backup_path: Path):
        """Apply a unified diff to file directly (no git needed)."""
        import re as _re

        # Normalize line endings and strip any \ No newline markers
        diff_lines = diff_content.replace("\r\n", "\n").split("\n")

        # Skip diff header lines: --- a/..., +++ b/..., and index lines
        parsed = []
        for line in diff_lines:
            stripped = line.strip()
            if (stripped.startswith("--- ") or stripped.startswith("+++ ")
                    or stripped.startswith("index ") or stripped.startswith("diff --git")):
                continue
            if line.startswith("\\ No newline"):
                continue
            parsed.append(line)

        # Read current file content (empty if new)
        if file_path.exists():
            with open(file_path, "r", encoding="utf-8") as f:
                original = f.read().split("\n")
                # Drop trailing empty element from split if file ended with newline
                if original and original[-1] == "":
                    original = original[:-1]
        else:
            original = []

        # Apply hunks
        hunk_re = _re.compile(r"^@@\s+-(\d+)(?:,(\d+))?\s+\+(\d+)(?:,(\d+))?\s+@@")
        output = list(original)
        i = 0
        applied_any = False
        while i < len(parsed):
            line = parsed[i]
            m = hunk_re.match(line.strip())
            if not m:
                i += 1
                continue
            old_start = int(m.group(1)) - 1  # 0-indexed
            new_start = int(m.group(3)) - 1
            i += 1

            # Collect hunk body
            removals = []
            additions = []
            while i < len(parsed):
                body = parsed[i]
                if body.startswith("@@") and hunk_re.match(body.strip()):
                    break
                if body.startswith("-"):
                    removals.append(body[1:])
                elif body.startswith("+"):
                    additions.append(body[1:])
                elif body.startswith(" "):
                    context = body[1:]
                    removals.append(context)
                    additions.append(context)
                elif body == "":
                    # Blank context line
                    removals.append("")
                    additions.append("")
                else:
                    break
                i += 1

            # Locate the hunk start in the file
            # Try at old_start first, else search for a unique anchor
            if old_start <= len(output) and output[old_start:old_start + len(removals)] == removals:
                pos = old_start
            else:
                # Search forward for the removal block
                pos = -1
                for j in range(len(output) - len(removals) + 1):
                    if output[j:j + len(removals)] == removals:
                        pos = j
                        break
                if pos == -1:
                    # Hunk doesn't match; leave file unchanged for this hunk
                    continue

            output[pos:pos + len(removals)] = additions
            applied_any = True

        if not applied_any:
            raise RuntimeError("Diff could not be applied cleanly")

        # Write result
        new_text = "\n".join(output)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(new_text)


    def _apply_file(self, file_path: Path, content: str, backup_path: Path):
        """Apply new or replacement file content."""
        file_path.write_text(content, encoding="utf-8")

    def _rollback(self, backup_path: Path, error: Exception):
        """Rollback changes on error."""
        # Restore from backup
        for backup_file in backup_path.iterdir():
            if backup_file.is_file() and backup_file.name != "manifest.json":
                target_path = self._get_project_root() / backup_file.name
                if target_path.exists():
                    shutil.move(str(target_path), str(backup_path / f"{backup_file.name}.old"))
                shutil.copy2(str(backup_file), str(target_path))

    def undo(self, task: str = "default", force: bool = False):
        """Undo last edit for a task."""
        from .backup import BackupManager
        manager = BackupManager(str(self.backup_dir))
        txn_id = manager.undo_last(force=True)
        if txn_id:
            return True
        return False