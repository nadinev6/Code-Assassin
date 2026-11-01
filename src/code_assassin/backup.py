"""
Backup and undo functionality.
"""
import json
import shutil
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


class BackupTransaction:
    """Manages backup transactions for undo functionality."""

    def __init__(self, backup_dir: str = ".code-assassin/backups"):
        self.backup_dir = Path(backup_dir)
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        self.transaction_id = self._generate_id()
        self.transaction_path = self.backup_dir / self.transaction_id
        self.transaction_path.mkdir(parents=True, exist_ok=True)
        self.manifest_path = self.transaction_path / "manifest.json"
        self.manifest = {
            "transaction_id": self.transaction_id,
            "created": datetime.now(timezone.utc).isoformat(),
            "files": [],
            "created_dirs": [],
        }

    def _generate_id(self) -> str:
        """Generate unique transaction ID."""
        return datetime.now().strftime("%Y%m%dT%H%M%S%f")

    def backup_file(self, file_path: Path, action: str = "edit"):
        """Backup a file before modification."""
        if not file_path.exists():
            return

        # Copy file to backup
        backup_file = self.transaction_path / file_path.name
        shutil.copy2(file_path, backup_file)

        # Record in manifest
        self.manifest["files"].append({
            "path": str(file_path),
            "action": action,
            "sha256": hashlib.sha256(file_path.read_bytes()).hexdigest(),
            "backup": str(backup_file),
        })

        self._save_manifest()

    def record_created_dir(self, dir_path: Path):
        """Record a directory that was created."""
        self.manifest["created_dirs"].append(str(dir_path))
        self._save_manifest()

    def _save_manifest(self):
        """Save manifest to disk."""
        with open(self.manifest_path, "w", encoding="utf-8") as f:
            json.dump(self.manifest, f, indent=2, ensure_ascii=False)

    def restore(self, force: bool = False):
        """Restore files from backup."""
        for file_info in self.manifest["files"]:
            file_path = Path(file_info["path"])
            backup_file = Path(file_info["backup"])

            if backup_file.exists():
                # Restore file (overwrite whatever is there)
                file_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(backup_file, file_path)

        # Remove created directories
        for dir_path in self.manifest["created_dirs"]:
            dir_path = Path(dir_path)
            if dir_path.exists():
                shutil.rmtree(dir_path, ignore_errors=True)

    def delete(self):
        """Delete this transaction's backup."""
        if self.transaction_path.exists():
            shutil.rmtree(self.transaction_path)


class BackupManager:
    """Manages backup transactions and undo operations."""

    def __init__(self, backup_dir: str = ".code-assassin/backups"):
        self.backup_dir = Path(backup_dir)
        self.backup_dir.mkdir(parents=True, exist_ok=True)

    def create_transaction(self) -> BackupTransaction:
        """Create a new backup transaction."""
        return BackupTransaction(str(self.backup_dir))

    def list_transactions(self) -> list:
        """List all backup transactions.

        Legacy or malformed manifests (e.g. a single-file backup without a
        ``transaction_id``) are skipped rather than crashing the caller.
        """
        transactions = []
        for path in self.backup_dir.iterdir():
            if not path.is_dir():
                continue
            manifest = path / "manifest.json"
            if not manifest.exists():
                continue
            try:
                with open(manifest, "r") as f:
                    data = json.load(f)
            except (OSError, json.JSONDecodeError):
                continue
            txn_id = data.get("transaction_id")
            files = data.get("files")
            if not isinstance(txn_id, str) or not isinstance(files, list):
                continue
            transactions.append({
                "id": txn_id,
                "created": data.get("created", ""),
                "files": len(files),
            })
        return sorted(transactions, key=lambda x: x["created"], reverse=True)

    def undo_last(self, force: bool = False):
        """Undo the last transaction."""
        transactions = self.list_transactions()
        if not transactions:
            return None

        last = transactions[0]
        transaction_path = self.backup_dir / last["id"]
        transaction = BackupTransaction(str(self.backup_dir))
        transaction.transaction_id = last["id"]
        transaction.transaction_path = transaction_path
        transaction.manifest_path = transaction_path / "manifest.json"

        with open(transaction.manifest_path, "r") as f:
            transaction.manifest = json.load(f)

        transaction.restore(force=force)
        transaction.delete()
        return last["id"]

    def undo_transaction(self, transaction_id: str, force: bool = False):
        """Undo a specific transaction."""
        transaction_path = self.backup_dir / transaction_id
        if not transaction_path.exists():
            return None

        transaction = BackupTransaction(str(self.backup_dir))
        transaction.transaction_id = transaction_id
        transaction.transaction_path = transaction_path
        transaction.manifest_path = transaction_path / "manifest.json"

        with open(transaction.manifest_path, "r") as f:
            transaction.manifest = json.load(f)

        transaction.restore(force=force)
        transaction.delete()
        return transaction_id