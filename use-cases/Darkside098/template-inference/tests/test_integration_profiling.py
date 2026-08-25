"""Integration tests for profiling with real benchmark documents."""

from pathlib import Path

import pytest

from superdocs_template_inference.ingestion import DOCXLoader
from superdocs_template_inference.profiling.profiler import DocumentProfiler


class TestProfilingIntegration:
    """Integration tests using real benchmark documents."""

    @pytest.fixture
    def corpus_path(self):
        """Get path to benchmark corpus."""
        current_dir = Path(__file__).parent.parent
        corpus_dir = current_dir / "corpus" / "offer_letters" / "docx"
        return corpus_dir

    @pytest.fixture
    def offer_001_path(self, corpus_path):
        """Get path to offer_001.docx."""
        doc_path = corpus_path / "offer_001.docx"
        if not doc_path.exists():
            pytest.skip(f"Benchmark document not found: {doc_path}")
        return str(doc_path)

    @pytest.fixture
    def offer_002_path(self, corpus_path):
        """Get path to offer_002.docx."""
        doc_path = corpus_path / "offer_002.docx"
        if not doc_path.exists():
            pytest.skip(f"Benchmark document not found: {doc_path}")
        return str(doc_path)

    @pytest.fixture
    def onboarding_001_path(self):
        """Get path to onboarding_001.docx."""
        current_dir = Path(__file__).parent.parent
        corpus_dir = current_dir / "corpus" / "onboarding_letters" / "docx"
        doc_path = corpus_dir / "onboarding_001.docx"
        if not doc_path.exists():
            pytest.skip(f"Benchmark document not found: {doc_path}")
        return str(doc_path)

    def test_profile_real_offer_document(self, offer_001_path):
        """Test profiling a real offer letter."""
        loader = DOCXLoader()
        doc = loader.load(offer_001_path)

        profiler = DocumentProfiler()
        profile = profiler.profile(doc)

        assert profile.document_id == doc.document_id
        assert profile.filename == "offer_001.docx"
        assert profile.file_type == "docx"

    def test_profile_has_structural_data(self, offer_001_path):
        """Test that profile contains structural data."""
        loader = DOCXLoader()
        doc = loader.load(offer_001_path)

        profiler = DocumentProfiler()
        profile = profiler.profile(doc)

        # Offer letter should have blocks
        assert profile.structural.total_blocks > 0
        assert profile.structural.paragraph_count > 0

    def test_profile_has_content_data(self, offer_001_path):
        """Test that profile contains content data."""
        loader = DOCXLoader()
        doc = loader.load(offer_001_path)

        profiler = DocumentProfiler()
        profile = profiler.profile(doc)

        # Should have text content
        assert profile.content.total_text_length > 0
        assert profile.content.word_count > 0
        assert profile.content.unique_words_count > 0

    def test_profile_has_formatting_data(self, offer_001_path):
        """Test that profile contains formatting data."""
        loader = DOCXLoader()
        doc = loader.load(offer_001_path)

        profiler = DocumentProfiler()
        profile = profiler.profile(doc)

        # Offer letter should have headings
        assert profile.formatting.has_headings is True

    def test_profile_detects_sections(self, offer_001_path):
        """Test that section detection finds sections."""
        loader = DOCXLoader()
        doc = loader.load(offer_001_path)

        profiler = DocumentProfiler()
        profile = profiler.profile(doc)

        # Should detect at least one section
        assert len(profile.sections) > 0

    def test_profile_sections_have_content(self, offer_001_path):
        """Test that detected sections contain content."""
        loader = DOCXLoader()
        doc = loader.load(offer_001_path)

        profiler = DocumentProfiler()
        profile = profiler.profile(doc)

        # Sections should be non-empty
        for section in profile.sections:
            assert section.block_count > 0
            assert section.content_length > 0

    def test_vocabulary_extracted(self, offer_001_path):
        """Test that vocabulary is extracted."""
        loader = DOCXLoader()
        doc = loader.load(offer_001_path)

        profiler = DocumentProfiler()
        profile = profiler.profile(doc)

        # Should have vocabulary
        assert len(profile.content.vocabulary) > 0
        assert len(profile.content.top_vocabulary) > 0

    def test_heading_texts_extracted(self, offer_001_path):
        """Test that heading texts are extracted."""
        loader = DOCXLoader()
        doc = loader.load(offer_001_path)

        profiler = DocumentProfiler()
        profile = profiler.profile(doc)

        # Offer letter should have heading texts
        assert len(profile.content.heading_texts) > 0

    def test_profile_serializes_to_json(self, offer_001_path):
        """Test that profile can be serialized to JSON."""
        loader = DOCXLoader()
        doc = loader.load(offer_001_path)

        profiler = DocumentProfiler()
        profile = profiler.profile(doc)

        json_str = profiler.to_json(profile)
        assert isinstance(json_str, str)
        assert len(json_str) > 0

    def test_profile_serializes_to_dict(self, offer_001_path):
        """Test that profile can be serialized to dict."""
        loader = DOCXLoader()
        doc = loader.load(offer_001_path)

        profiler = DocumentProfiler()
        profile = profiler.profile(doc)

        profile_dict = profiler.to_dict(profile)
        assert isinstance(profile_dict, dict)
        assert "structural" in profile_dict
        assert "content" in profile_dict
        assert "formatting" in profile_dict

    def test_multiple_documents_have_different_profiles(
        self, offer_001_path, offer_002_path
    ):
        """Test that different documents produce different profiles."""
        loader = DOCXLoader()
        doc1 = loader.load(offer_001_path)
        doc2 = loader.load(offer_002_path)

        profiler = DocumentProfiler()
        profile1 = profiler.profile(doc1)
        profile2 = profiler.profile(doc2)

        # Different documents should have different document IDs
        assert profile1.document_id != profile2.document_id

    def test_profile_different_families(self, offer_001_path, onboarding_001_path):
        """Test profiling documents from different families."""
        loader = DOCXLoader()
        offer_doc = loader.load(offer_001_path)
        onboarding_doc = loader.load(onboarding_001_path)

        profiler = DocumentProfiler()
        offer_profile = profiler.profile(offer_doc)
        onboarding_profile = profiler.profile(onboarding_doc)

        # Both should be validly profiled
        assert offer_profile.structural.total_blocks > 0
        assert onboarding_profile.structural.total_blocks > 0

        # They may have different characteristics
        # (Note: we don't assert family membership as that's out of scope for M2)

    def test_profile_round_trip_consistency(self, offer_001_path):
        """Test that profile serialization round-trips consistently."""
        loader = DOCXLoader()
        doc = loader.load(offer_001_path)

        profiler = DocumentProfiler()
        profile1 = profiler.profile(doc)
        dict1 = profiler.to_dict(profile1)

        # Key fields should match
        assert dict1["document_id"] == profile1.document_id
        assert dict1["filename"] == profile1.filename
        assert dict1["structural"]["total_blocks"] == profile1.structural.total_blocks
        assert dict1["content"]["word_count"] == profile1.content.word_count

    def test_no_ground_truth_dependency(self, offer_001_path):
        """Test that profiling does not depend on ground truth."""
        # This test verifies that the profiler works independently
        loader = DOCXLoader()
        doc = loader.load(offer_001_path)

        profiler = DocumentProfiler()
        profile = profiler.profile(doc)

        # Should produce valid profile without ground truth
        assert profile.profile_id is not None
        assert profile.structural is not None
        assert profile.content is not None

    def test_profile_content_is_observational(self, offer_001_path):
        """Test that profile content is purely observational (no semantic inference)."""
        loader = DOCXLoader()
        doc = loader.load(offer_001_path)

        profiler = DocumentProfiler()
        profile = profiler.profile(doc)

        # Vocabulary should be from actual text, not semantic classification
        # All content should be derived from document structure
        assert profile.content.vocabulary is not None
        assert profile.formatting.paragraph_styles is not None
        # No semantic fields like "inferred_document_type" or "family"
        assert not hasattr(profile, "inferred_family")
        assert not hasattr(profile, "document_type")
