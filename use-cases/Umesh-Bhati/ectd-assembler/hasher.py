import os
import hashlib

def calculate_file_hash(filepath: str) -> str:
    """Calculate SHA-256 hash of a file."""
    hasher = hashlib.sha256()
    with open(filepath, 'rb') as f:
        buf = f.read()
        hasher.update(buf)
    return hasher.hexdigest()

def get_file_hashes(filepaths: set) -> dict:
    """Return dictionary of file paths to their hashes."""
    hashes = {}
    for filepath in filepaths:
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"Source file missing: {filepath}")
        hashes[filepath] = calculate_file_hash(filepath)
    return hashes
