import os
from abc import ABC, abstractmethod
from pathlib import Path
from backend.app.config import settings

class StorageService(ABC):
    @abstractmethod
    async def save_file(self, filename: str, content: bytes) -> str:
        """Save file contents and return reference/path string."""
        pass

    @abstractmethod
    async def read_file(self, file_reference: str) -> bytes:
        """Read file contents by reference."""
        pass

    @abstractmethod
    async def delete_file(self, file_reference: str) -> None:
        """Delete file by reference."""
        pass

class LocalStorageService(StorageService):
    def __init__(self, upload_dir: str = settings.UPLOAD_DIR):
        self.upload_dir = Path(upload_dir)
        self.upload_dir.mkdir(parents=True, exist_ok=True)

    async def save_file(self, filename: str, content: bytes) -> str:
        # Prevent path traversal
        safe_filename = Path(filename).name
        file_path = self.upload_dir / safe_filename
        
        # Resolve collisions
        base = file_path.stem
        ext = file_path.suffix
        counter = 1
        while file_path.exists():
            file_path = self.upload_dir / f"{base}_{counter}{ext}"
            counter += 1

        with open(file_path, "wb") as f:
            f.write(content)
        
        return str(file_path.as_posix())

    async def read_file(self, file_reference: str) -> bytes:
        path = Path(file_reference)
        if not path.exists():
            raise FileNotFoundError(f"File not found at reference: {file_reference}")
        with open(path, "rb") as f:
            return f.read()

    async def delete_file(self, file_reference: str) -> None:
        path = Path(file_reference)
        if path.exists():
            os.remove(path)

def get_storage_service() -> StorageService:
    return LocalStorageService()
