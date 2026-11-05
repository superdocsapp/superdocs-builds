import os
import hashlib

_CHUNK_SIZE = 64 * 1024


def calculate_file_hash(filepath: str) -> str:
    """Return the SHA-256 hash of a file, streaming in chunks so large study
    reports (PDFs can be hundreds of MB) never need to be read into memory."""
    hasher = hashlib.sha256()
    with open(filepath, "rb") as f:
        while True:
            buf = f.read(_CHUNK_SIZE)
            if not buf:
                break
            hasher.update(buf)
    return hasher.hexdigest()


def get_file_hashes(filepaths: set) -> dict:
    """Return a dict of file paths to their SHA-256 hashes."""
    hashes = {}
    for filepath in filepaths:
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"Source file missing: {filepath}")
        hashes[filepath] = calculate_file_hash(filepath)
    return hashes
