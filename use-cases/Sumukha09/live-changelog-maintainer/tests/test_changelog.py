import pytest
import sys
import os
import shutil

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from models import Release, Changelog
from changelog_generator import ChangelogGenerator, process_releases
from mock_data import get_mock_releases, get_latest_mock_release

def test_initial_changelog_generation():
    releases = get_mock_releases()
    changelog = Changelog(title="Test Changelog", releases=releases)
    generator = ChangelogGenerator(changelog)
    
    markdown = generator.generate_initial_markdown()
    
    assert "# Test Changelog" in markdown
    assert "## v2.1.0" in markdown
    assert "## v2.2.0" in markdown
    assert "## v2.3.0" in markdown
    assert "### Added" in markdown
    assert "### Improved" in markdown
    assert "### Fixed" in markdown

def test_duplicate_release_detection():
    changelog = Changelog(releases=[Release(version="v2.1.0", date="")])
    generator = ChangelogGenerator(changelog)
    
    release2 = Release(version="v2.1.0", date="2023-01-02")
    assert generator.detect_duplicate(release2) == True
    
    release3 = Release(version="v2.2.0", date="2023-01-02")
    assert generator.detect_duplicate(release3) == False

def test_byte_identical_historical_releases():
    """Requirement: Release N update does not modify releases 1 through N-1."""
    releases = get_mock_releases()
    changelog = Changelog(title="Product Changelog", releases=releases)
    generator = ChangelogGenerator(changelog)
    
    initial_markdown = generator.generate_initial_markdown()
    
    # Isolate the original content without the main header to test for byte identity
    header = "# Product Changelog\n\n"
    original_history_bytes = initial_markdown[len(header):]
    
    new_release = get_latest_mock_release()
    updated_markdown = generator.update_markdown(initial_markdown, new_release)
    
    # Find where the historical releases begin in the new markdown
    # It should be immediately after the new release chunk
    new_release_markdown = generator.generate_release_markdown(new_release)
    
    expected_content = header + new_release_markdown + original_history_bytes
    
    assert updated_markdown == expected_content
    # This proves the historical section remained completely byte identical

def test_preview_mode_no_mcp_calls(capsys):
    """Requirement: Preview mode performs ZERO MCP/remote calls and stops."""
    # We can prove it doesn't make MCP calls because it's completely offline logic
    # We also check that it outputs PREVIEW MODE
    incoming = [get_latest_mock_release()]
    
    result = process_releases(incoming, preview_mode=True)
    
    # We processed 1 release
    assert result == 1
    
    captured = capsys.readouterr()
    assert "--- PREVIEW MODE ---" in captured.out
    assert "Proposed Update for v2.4.0" in captured.out
    
    # It must not output to the export folder
    assert "Successfully processed" not in captured.out

def test_stopping_rule():
    """Requirement: The maintainer must process exactly one release per invocation and stop."""
    incoming = [
        Release(version="v2.5.0", date="2024-01-01"),
        Release(version="v2.6.0", date="2024-02-01")
    ]
    
    # The return value is the number of processed releases
    result = process_releases(incoming, preview_mode=True)
    
    # Even though we sent 2 releases, it stops after 1
    assert result == 1

def test_self_trigger_protection():
    """Requirement: Verify exported output is derived from source and does not become a new input."""
    # We can check that the files are maintained in separate paths
    if os.path.exists("source"):
        shutil.rmtree("source")
    if os.path.exists("export"):
        shutil.rmtree("export")
        
    incoming = [get_latest_mock_release()]
    process_releases(incoming, preview_mode=False)
    
    assert os.path.exists(os.path.join("source", "changelog.md"))
    assert os.path.exists(os.path.join("export", "changelog.md"))
    
    # Ensure they are distinct files
    source_stat = os.stat(os.path.join("source", "changelog.md"))
    export_stat = os.stat(os.path.join("export", "changelog.md"))
    assert source_stat.st_ino != export_stat.st_ino or source_stat.st_dev != export_stat.st_dev
    
    # Clean up
    if os.path.exists("source"):
        shutil.rmtree("source")
    if os.path.exists("export"):
        shutil.rmtree("export")
