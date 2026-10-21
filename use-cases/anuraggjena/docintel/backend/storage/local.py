from pathlib import Path
from typing import Optional
import hashlib
from backend.storage.backend import StorageBackend


class LocalStorageBackend(StorageBackend):
    def __init__(self, base_path: str):
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)

    def save(self, content: bytes, filename: str, workspace_id: str) -> str:
        # Validate workspace_id doesn't escape base_path
        workspace_dir = self.base_path / workspace_id
        workspace_dir_resolved = workspace_dir.resolve()

        if not workspace_dir_resolved.is_relative_to(self.base_path.resolve()):
            raise ValueError(f"Invalid workspace_id: path traversal detected in {workspace_id}")

        workspace_dir.mkdir(parents=True, exist_ok=True)

        # Validate filename
        if '..' in filename or filename.startswith('/') or filename.startswith('\\'):
            raise ValueError(f"Invalid filename: {filename}")

        content_hash = hashlib.sha256(content).hexdigest()[:8]
        stem = Path(filename).stem
        suffix = Path(filename).suffix
        unique_filename = f"{stem}_{content_hash}{suffix}"

        file_path = workspace_dir / unique_filename
        file_path_resolved = file_path.resolve()

        # Double-check final path is within workspace
        if not file_path_resolved.is_relative_to(workspace_dir_resolved):
            raise ValueError(f"Invalid path: {file_path}")

        file_path.write_bytes(content)
        return str(file_path.relative_to(self.base_path))

    def read(self, path: str) -> bytes:
        file_path = self.base_path / path

        # Security: Prevent path traversal attacks
        try:
            file_path = file_path.resolve()
            if not file_path.is_relative_to(self.base_path.resolve()):
                raise ValueError(f"Path traversal detected: {path}")
        except (ValueError, RuntimeError) as e:
            raise ValueError(f"Invalid path: {path}") from e

        # Check if file exists
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {path}")

        return file_path.read_bytes()

    def exists(self, path: str) -> bool:
        file_path = self.base_path / path

        # Security: Prevent path traversal attacks
        try:
            file_path = file_path.resolve()
            if not file_path.is_relative_to(self.base_path.resolve()):
                return False
        except (ValueError, RuntimeError):
            return False

        return file_path.exists()

    def delete(self, path: str) -> None:
        file_path = self.base_path / path

        # Security: Prevent path traversal attacks
        try:
            file_path = file_path.resolve()
            if not file_path.is_relative_to(self.base_path.resolve()):
                raise ValueError(f"Path traversal detected: {path}")
        except (ValueError, RuntimeError) as e:
            raise ValueError(f"Invalid path: {path}") from e

        if file_path.exists():
            file_path.unlink()

    def get_url(self, path: str) -> Optional[str]:
        return None
