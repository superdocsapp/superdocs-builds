from abc import ABC, abstractmethod
from typing import Optional


class StorageBackend(ABC):
    @abstractmethod
    def save(self, content: bytes, filename: str, workspace_id: str) -> str:
        """Save file and return storage path"""
        pass

    @abstractmethod
    def read(self, path: str) -> bytes:
        """Read file content"""
        pass

    @abstractmethod
    def exists(self, path: str) -> bool:
        """Check if file exists"""
        pass

    @abstractmethod
    def delete(self, path: str) -> None:
        """Delete file"""
        pass

    @abstractmethod
    def get_url(self, path: str) -> Optional[str]:
        """Get URL for file (may be None for local storage)"""
        pass
