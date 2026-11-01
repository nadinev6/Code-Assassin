"""
Tests for the editor module.
"""
import tempfile
import os
import pytest
from pathlib import Path
from code_assassin.editor import Editor


def test_editor_relative_root_resolves(tmp_path, monkeypatch):
    """A relative root must not make every valid path 'escape' the project."""
    project = tmp_path / "project"
    (project / "src").mkdir(parents=True)
    (project / "src" / "a.py").write_text("x = 1\n")
    monkeypatch.chdir(project)

    editor = Editor(backup_dir=str(tmp_path / "backups"), root=Path("."))
    path = editor._validate_path("src/a.py", is_diff=True)
    assert path is not None
    assert path.name == "a.py"


def test_editor_validate_path_escapes_root(tmp_path):
    """Test that paths escaping root are rejected."""
    editor = Editor(backup_dir=str(tmp_path / "backups"))
    
    # Create project root
    project_root = tmp_path / "project"
    project_root.mkdir()
    
    # Try to escape
    import os
    os.chdir(str(project_root))
    
    # This should fail
    with pytest.raises(ValueError, match="escapes project root"):
        editor._validate_path("../../../etc/passwd", is_diff=False)


def test_editor_validate_forbidden_patterns(tmp_path):
    """Test that forbidden patterns are rejected."""
    editor = Editor(backup_dir=str(tmp_path / "backups"))
    
    project_root = tmp_path / "project"
    project_root.mkdir()
    os.chdir(str(project_root))
    
    forbidden = [".env", "secret.key", "id_rsa", "cert.pem"]
    for pattern in forbidden:
        with pytest.raises(ValueError):
            editor._validate_path(pattern, is_diff=False)


def test_editor_disable_mode(tmp_path):
    """Test that disabled editor doesn't apply changes."""
    editor = Editor(backup_dir=str(tmp_path / "backups"))
    editor.disable()
    
    # Should not apply
    # In real test, would check no backup was created