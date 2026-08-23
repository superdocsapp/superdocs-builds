"""
test_journal_loader.py
Tests for journal profile loading and validation.
"""
import json
import os
import pytest
from journal_loader import load_profile, list_profiles, JournalProfileError


class TestLoadProfile:
    def test_load_nature(self):
        profile = load_profile("nature")
        assert profile["id"] == "nature"
        assert profile["name"] == "Nature"
        assert isinstance(profile["section_order"], list)
        assert len(profile["section_order"]) > 0
        assert profile["blinded_review"] is False
        assert isinstance(profile["required_declarations"], list)

    def test_load_plos_one(self):
        profile = load_profile("plos-one")
        assert profile["id"] == "plos-one"
        assert profile["name"] == "PLOS ONE"
        assert profile["blinded_review"] is True
        assert "author-year" in profile["reference_style"]

    def test_nature_has_required_fields(self):
        profile = load_profile("nature")
        required = [
            "id", "name", "section_order", "reference_style",
            "figure_placement", "table_placement",
            "blinded_review", "required_declarations",
        ]
        for field in required:
            assert field in profile, f"Missing field: {field}"

    def test_plos_has_required_fields(self):
        profile = load_profile("plos-one")
        required = [
            "id", "name", "section_order", "reference_style",
            "figure_placement", "table_placement",
            "blinded_review", "required_declarations",
        ]
        for field in required:
            assert field in profile, f"Missing field: {field}"

    def test_missing_journal_raises_error(self):
        with pytest.raises(JournalProfileError, match="No journal profile found"):
            load_profile("nonexistent-journal-xyz")

    def test_invalid_json_raises_error(self, tmp_path, monkeypatch):
        # Write a malformed JSON file to a temp profiles dir
        profiles_dir = tmp_path / "journal_profiles"
        profiles_dir.mkdir()
        bad_file = profiles_dir / "bad-journal.json"
        bad_file.write_text("{ this is not valid json }", encoding="utf-8")

        import journal_loader
        monkeypatch.setattr(journal_loader, "PROFILES_DIR", str(profiles_dir))
        with pytest.raises(JournalProfileError, match="invalid JSON"):
            load_profile("bad-journal")

    def test_missing_required_field_raises_error(self, tmp_path, monkeypatch):
        profiles_dir = tmp_path / "journal_profiles"
        profiles_dir.mkdir()
        incomplete = profiles_dir / "incomplete.json"
        # Missing 'section_order'
        incomplete.write_text(json.dumps({
            "id": "incomplete",
            "name": "Incomplete Journal",
            "reference_style": "numbered",
            "figure_placement": "end",
            "table_placement": "end",
            "blinded_review": False,
            "required_declarations": [],
        }), encoding="utf-8")

        import journal_loader
        monkeypatch.setattr(journal_loader, "PROFILES_DIR", str(profiles_dir))
        with pytest.raises(JournalProfileError, match="section_order"):
            load_profile("incomplete")

    def test_blinded_review_must_be_bool(self, tmp_path, monkeypatch):
        profiles_dir = tmp_path / "journal_profiles"
        profiles_dir.mkdir()
        bad = profiles_dir / "bad-bool.json"
        bad.write_text(json.dumps({
            "id": "bad-bool",
            "name": "Bad Bool Journal",
            "section_order": ["Abstract"],
            "reference_style": "numbered",
            "figure_placement": "end",
            "table_placement": "end",
            "blinded_review": "yes",  # should be bool
            "required_declarations": [],
        }), encoding="utf-8")

        import journal_loader
        monkeypatch.setattr(journal_loader, "PROFILES_DIR", str(profiles_dir))
        with pytest.raises(JournalProfileError, match="blinded_review.*boolean"):
            load_profile("bad-bool")

    def test_section_order_must_be_list(self, tmp_path, monkeypatch):
        profiles_dir = tmp_path / "journal_profiles"
        profiles_dir.mkdir()
        bad = profiles_dir / "bad-order.json"
        bad.write_text(json.dumps({
            "id": "bad-order",
            "name": "Bad Order Journal",
            "section_order": "Abstract, Introduction",  # should be list
            "reference_style": "numbered",
            "figure_placement": "end",
            "table_placement": "end",
            "blinded_review": False,
            "required_declarations": [],
        }), encoding="utf-8")

        import journal_loader
        monkeypatch.setattr(journal_loader, "PROFILES_DIR", str(profiles_dir))
        with pytest.raises(JournalProfileError, match="section_order.*list"):
            load_profile("bad-order")


class TestListProfiles:
    def test_list_returns_both_profiles(self):
        profiles = list_profiles()
        ids = [p["id"] for p in profiles]
        assert "nature" in ids
        assert "plos-one" in ids

    def test_list_returns_name_and_id(self):
        profiles = list_profiles()
        for p in profiles:
            assert "id" in p
            assert "name" in p

    def test_list_skips_malformed(self, tmp_path, monkeypatch):
        profiles_dir = tmp_path / "journal_profiles"
        profiles_dir.mkdir()
        # One valid, one malformed
        valid = profiles_dir / "valid.json"
        valid.write_text(json.dumps({
            "id": "valid",
            "name": "Valid Journal",
            "section_order": ["Abstract"],
            "reference_style": "numbered",
            "figure_placement": "end",
            "table_placement": "end",
            "blinded_review": False,
            "required_declarations": [],
        }), encoding="utf-8")
        bad = profiles_dir / "bad.json"
        bad.write_text("not json", encoding="utf-8")

        import journal_loader
        monkeypatch.setattr(journal_loader, "PROFILES_DIR", str(profiles_dir))
        profiles = list_profiles()
        assert len(profiles) == 1
        assert profiles[0]["id"] == "valid"
