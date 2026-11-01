"""
Tests for backup module.
"""
import json
import tempfile
import os
import pytest
from code_assassin.backup import BackupManager, BackupTransaction


def test_backup_create_and_restore(tmp_path):
    """Test creating and restoring from backup."""
    backup_dir = tmp_path / "backups"
    manager = BackupManager(backup_dir=str(backup_dir))
    
    # Create a test file
    test_file = tmp_path / "test.txt"
    test_file.write_text("original content")
    
    # Create transaction and backup
    txn = manager.create_transaction()
    txn.backup_file(test_file, action="edit")
    
    # Modify file
    test_file.write_text("modified content")
    
    # Restore
    txn.restore()
    
    # Verify restore
    assert test_file.read_text() == "original content"


def test_backup_created_dir_removed(tmp_path):
    """Test that created directories are removed on undo."""
    backup_dir = tmp_path / "backups"
    manager = BackupManager(backup_dir=str(backup_dir))
    
    txn = manager.create_transaction()
    
    # Record a created dir
    new_dir = tmp_path / "new_directory"
    new_dir.mkdir()
    txn.record_created_dir(new_dir)
    
    # Restore - should remove directory
    txn.restore()
    assert not new_dir.exists()


def test_list_transactions_skips_legacy_manifest(tmp_path):
    """A legacy single-file manifest must not crash list_transactions."""
    backup_dir = tmp_path / "backups"
    manager = BackupManager(backup_dir=str(backup_dir))

    legacy = backup_dir / "20260101T000000000000"
    legacy.mkdir()
    (legacy / "manifest.json").write_text(
        json.dumps({
            "path": "x.py",
            "action": "diff",
            "sha256": "abc",
            "created": "2026-01-01T00:00:00",
        }),
        encoding="utf-8",
    )

    src = tmp_path / "f.txt"
    src.write_text("hello")
    txn = manager.create_transaction()
    txn.backup_file(src, action="edit")

    listed = manager.list_transactions()
    assert len(listed) == 1
    assert listed[0]["id"] == txn.transaction_id
    assert listed[0]["files"] == 1