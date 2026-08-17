import pytest
import tempfile
import hashlib
from pathlib import Path
from agents.ingestor.watcher import DocWatcher


class TestDocWatcher:
    def test_scan_and_hash_empty_dir(self):
        with tempfile.TemporaryDirectory() as d:
            w = DocWatcher(watched_dir=d)
            hashes = w.scan_and_hash()
            assert hashes == {}

    def test_scan_and_hash_finds_files(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "test.md"
            p.write_text("# Hello")
            w = DocWatcher(watched_dir=d)
            hashes = w.scan_and_hash()
            assert str(p) in hashes
            assert hashes[str(p)] == hashlib.sha256(b"# Hello").hexdigest()

    def test_diff_detects_new_file(self):
        with tempfile.TemporaryDirectory() as d:
            w = DocWatcher(watched_dir=d)
            w._known_hashes = {}
            p = Path(d) / "new.md"
            p.write_text("content")
            changed = w.diff()
            assert str(p) in changed

    def test_diff_detects_modified_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "mod.md"
            p.write_text("v1")
            w = DocWatcher(watched_dir=d)
            w._known_hashes = {str(p): "oldhash"}
            changed = w.diff()
            assert str(p) in changed

    def test_diff_detects_no_change(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "stable.md"
            p.write_text("unchanged")
            actual = hashlib.sha256(b"unchanged").hexdigest()
            w = DocWatcher(watched_dir=d)
            w._known_hashes = {str(p): actual}
            changed = w.diff()
            assert str(p) not in changed

    def test_is_doc_filters_extensions(self):
        assert DocWatcher._is_doc(Path("test.md")) is True
        assert DocWatcher._is_doc(Path("test.html")) is True
        assert DocWatcher._is_doc(Path("test.docx")) is True
        assert DocWatcher._is_doc(Path("test.pdf")) is True
        assert DocWatcher._is_doc(Path("test.txt")) is True
        assert DocWatcher._is_doc(Path("test.py")) is False
        assert DocWatcher._is_doc(Path("test.js")) is False
        assert DocWatcher._is_doc(Path("test.exe")) is False