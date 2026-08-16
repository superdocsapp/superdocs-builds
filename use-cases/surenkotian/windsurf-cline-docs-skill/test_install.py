"""
Offline tests for install.py's merge logic -- run against a temp file, never
the real global config paths, so this is safe to run on any machine
including one with a real Windsurf/Cline setup already configured.
"""

import json
import tempfile
from pathlib import Path

from install import SUPERDOCS_ENTRY_CLINE, SUPERDOCS_ENTRY_WINDSURF, merge


def test_merge_preserves_existing_servers_and_adds_superdocs():
    tmp = Path(tempfile.mkdtemp()) / "mcp_config.json"
    tmp.write_text(json.dumps({"mcpServers": {"some-other-server": {"command": "npx", "args": ["other-mcp"]}}}))

    merge(tmp, SUPERDOCS_ENTRY_WINDSURF, dry_run=False)

    result = json.loads(tmp.read_text())
    assert result["mcpServers"]["some-other-server"] == {"command": "npx", "args": ["other-mcp"]}
    assert result["mcpServers"]["superdocs"] == SUPERDOCS_ENTRY_WINDSURF


def test_merge_creates_backup_of_existing_file():
    tmp = Path(tempfile.mkdtemp()) / "mcp_config.json"
    original_content = json.dumps({"mcpServers": {"x": {"command": "y"}}})
    tmp.write_text(original_content)

    merge(tmp, SUPERDOCS_ENTRY_WINDSURF, dry_run=False)

    backup = tmp.with_suffix(tmp.suffix + ".bak")
    assert backup.exists()
    assert backup.read_text() == original_content


def test_merge_is_idempotent():
    tmp = Path(tempfile.mkdtemp()) / "mcp_config.json"
    merge(tmp, SUPERDOCS_ENTRY_CLINE, dry_run=False)
    first = tmp.read_text()

    merge(tmp, SUPERDOCS_ENTRY_CLINE, dry_run=False)
    second = tmp.read_text()

    assert first == second


def test_dry_run_never_writes():
    tmp = Path(tempfile.mkdtemp()) / "mcp_config.json"
    assert not tmp.exists()

    merge(tmp, SUPERDOCS_ENTRY_WINDSURF, dry_run=True)

    assert not tmp.exists()


def test_creates_new_file_when_none_exists():
    tmp = Path(tempfile.mkdtemp()) / "nested" / "mcp_config.json"
    assert not tmp.exists()

    merge(tmp, SUPERDOCS_ENTRY_CLINE, dry_run=False)

    result = json.loads(tmp.read_text())
    assert result["mcpServers"]["superdocs"] == SUPERDOCS_ENTRY_CLINE
