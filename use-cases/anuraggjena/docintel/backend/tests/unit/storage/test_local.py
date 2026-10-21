import pytest
from pathlib import Path
import tempfile
from backend.storage.local import LocalStorageBackend


@pytest.fixture
def temp_storage():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield LocalStorageBackend(base_path=tmpdir)


def test_save_file(temp_storage):
    content = b"Hello, World!"
    file_path = temp_storage.save(content, "test.txt", "workspace-123")

    assert file_path is not None
    assert "workspace-123" in file_path


def test_read_file(temp_storage):
    content = b"Hello, World!"
    file_path = temp_storage.save(content, "test.txt", "workspace-123")

    read_content = temp_storage.read(file_path)

    assert read_content == content


def test_file_exists(temp_storage):
    content = b"Hello, World!"
    file_path = temp_storage.save(content, "test.txt", "workspace-123")

    assert temp_storage.exists(file_path) is True
    assert temp_storage.exists("nonexistent.txt") is False


def test_read_nonexistent_file(temp_storage):
    """Test reading a file that doesn't exist raises FileNotFoundError"""
    with pytest.raises(FileNotFoundError):
        temp_storage.read("nonexistent.txt")


def test_path_traversal_attack_read(temp_storage):
    """Test that path traversal attempts are blocked in read()"""
    with pytest.raises(ValueError, match="Path traversal detected|Invalid path"):
        temp_storage.read("../../../etc/passwd")


def test_path_traversal_attack_exists(temp_storage):
    """Test that path traversal attempts return False in exists()"""
    assert temp_storage.exists("../../../etc/passwd") is False


def test_path_traversal_attack_delete(temp_storage):
    """Test that path traversal attempts are blocked in delete()"""
    with pytest.raises(ValueError, match="Path traversal detected|Invalid path"):
        temp_storage.delete("../../../etc/passwd")


def test_path_traversal_attack_save_workspace(temp_storage):
    """Test path traversal protection in save (workspace_id)"""
    with pytest.raises(ValueError, match="path traversal"):
        temp_storage.save(b"attack", "test.txt", "../../etc")


def test_path_traversal_attack_save_filename(temp_storage):
    """Test path traversal protection in save (filename)"""
    with pytest.raises(ValueError, match="Invalid filename"):
        temp_storage.save(b"attack", "../../../etc/passwd", "workspace-123")
