from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import hashlib


@dataclass(frozen=True)
class SourceDocument:
    """
    Immutable representation of the user's original file.

    The original bytes are retained so DocShield never needs to
    reconstruct the user's document from the normalized model.
    """

    path: Path
    filename: str
    extension: str
    data: bytes
    sha256: str

    @classmethod
    def load(cls, path: str | Path) -> "SourceDocument":
        file_path = Path(path)

        if not file_path.exists():
            raise FileNotFoundError(file_path)

        if not file_path.is_file():
            raise ValueError(f"Not a file: {file_path}")

        data = file_path.read_bytes()

        if not data:
            raise ValueError("Document is empty.")

        return cls(
            path=file_path,
            filename=file_path.name,
            extension=file_path.suffix.lower(),
            data=data,
            sha256=hashlib.sha256(data).hexdigest(),
        )

    def verify(self, data: bytes) -> bool:
        """
        Verify that supplied bytes are identical to the original.
        """
        return hashlib.sha256(data).hexdigest() == self.sha256
